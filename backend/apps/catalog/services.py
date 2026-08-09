from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.knowledge.models import KnowledgeConcept
from apps.knowledge.services import OntologyContextService, OntologySnapshot

from .models import (
    ROLE_CONCEPT_TYPES,
    Product,
    ProductConceptLink,
    _explicit_product_version_writes,
    _product_link_retirement_writes,
)


@dataclass(frozen=True)
class ProductConceptVersion:
    link_id: UUID
    link_version: int
    role: str
    concept_id: UUID
    concept_code: str
    concept_type: str
    concept_version: int


@dataclass(frozen=True)
class ProductSnapshot:
    product_id: UUID
    product_version: int
    name_zh: str
    name_en: str
    module_min: Decimal
    module_max: Decimal
    tooth_count_min: int
    tooth_count_max: int
    pressure_angle: Decimal
    accuracy_grade: str
    heat_treatment: str
    surface_treatment: str
    manufacturing_capabilities: tuple[str, ...]
    inspection_capabilities: tuple[str, ...]
    moq: int
    lead_time: str
    landing_page_url: str
    status: str
    concept_versions: tuple[ProductConceptVersion, ...]

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProductGenerationContext:
    product: ProductSnapshot
    ontology: OntologySnapshot

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _concept_link_specs(concept_links: Iterable[dict[str, object]]) -> tuple[dict[str, object], ...]:
    specs = tuple(
        {
            "role": item["role"],
            "concept_id": (
                item["concept_id"]
                if "concept_id" in item
                else item["concept"].pk
            ),
        }
        for item in concept_links
    )
    keys = [(item["role"], item["concept_id"]) for item in specs]
    if len(keys) != len(set(keys)):
        raise ValidationError(
            {"concept_links": ["Duplicate product role/concept pairs are not allowed."]}
        )
    return specs


def _lock_product(product: Product) -> Product:
    return Product.objects.select_for_update().get(pk=product.pk)


def _lock_and_validate_concepts(
    *, product: Product, specs: tuple[dict[str, object], ...]
) -> dict[UUID, KnowledgeConcept]:
    concept_ids = sorted({item["concept_id"] for item in specs}, key=str)
    concepts = list(
        KnowledgeConcept.objects.select_for_update()
        .filter(pk__in=concept_ids)
        .order_by("id")
    )
    by_id = {concept.id: concept for concept in concepts}
    for item in specs:
        concept_id = item["concept_id"]
        concept = by_id.get(concept_id)
        if concept is None:
            raise ValidationError(
                {"concept_links": ["Approved concept does not exist."]}
            )
        if concept.organization_id not in {None, product.organization_id}:
            raise ValidationError(
                {"concept_links": ["Approved concept does not exist."]}
            )
        if concept.status != KnowledgeConcept.Status.APPROVED:
            raise ValidationError(
                {"concept_links": ["Only currently APPROVED concepts may be linked."]}
            )
        if concept.concept_type not in ROLE_CONCEPT_TYPES[item["role"]]:
            raise ValidationError(
                {
                    "concept_links": [
                        f"Concept type is not compatible with the {item['role']} product role."
                    ]
                }
            )
    return by_id


def _active_links_locked(product: Product) -> list[ProductConceptLink]:
    return list(
        ProductConceptLink.objects.select_for_update()
        .active()
        .filter(product=product)
        .select_related("concept")
        .order_by("id")
    )


def _active_keys(links: Iterable[ProductConceptLink]) -> set[tuple[str, UUID]]:
    return {(link.role, link.concept_id) for link in links}


@transaction.atomic
def replace_product_links(*, product: Product, concept_links) -> Product:
    locked_product = _lock_product(product)
    specs = _concept_link_specs(concept_links)
    current_links = _active_links_locked(locked_product)
    concepts = _lock_and_validate_concepts(product=locked_product, specs=specs)
    desired_keys = {(item["role"], item["concept_id"]) for item in specs}
    reusable: dict[tuple[str, UUID], ProductConceptLink] = {}
    for link in current_links:
        concept = concepts.get(link.concept_id)
        key = (link.role, link.concept_id)
        if (
            key in desired_keys
            and link.organization_id == locked_product.organization_id
            and concept is not None
            and concept.organization_id in {None, locked_product.organization_id}
            and concept.status == KnowledgeConcept.Status.APPROVED
            and concept.concept_type in ROLE_CONCEPT_TYPES.get(link.role, ())
        ):
            reusable[key] = link

    retired_at = timezone.now()
    for link in current_links:
        if reusable.get((link.role, link.concept_id)) != link:
            link.retired_at = retired_at
            with _product_link_retirement_writes():
                link.save(update_fields=["retired_at", "updated_at"])

    ProductConceptLink.objects.bulk_create(
        [
            ProductConceptLink(
                organization=locked_product.organization,
                product=locked_product,
                role=item["role"],
                concept_id=item["concept_id"],
            )
            for item in specs
            if (item["role"], item["concept_id"]) not in reusable
        ]
    )
    return locked_product


@transaction.atomic
def create_product(*, organization, values: dict[str, object], concept_links) -> Product:
    product = Product.objects.create(organization=organization, **values)
    return replace_product_links(product=product, concept_links=concept_links)


@transaction.atomic
def update_product(*, product: Product, values: dict[str, object]) -> Product:
    locked_product = _lock_product(product)
    missing = object()
    concept_links = values.pop("concept_links", missing)
    if concept_links is not missing:
        specs = _concept_link_specs(concept_links)
        current_keys = _active_keys(_active_links_locked(locked_product))
        desired_keys = {(item["role"], item["concept_id"]) for item in specs}
        target_status = values.get("status", locked_product.status)
        if (
            locked_product.status == Product.Status.ARCHIVED
            or target_status == Product.Status.ARCHIVED
        ) and desired_keys != current_keys:
            raise ValidationError(
                {"concept_links": ["Archived products must retain their active concept links."]}
            )
        replace_product_links(product=locked_product, concept_links=specs)

    for field, value in values.items():
        setattr(locked_product, field, value)
    locked_product.version += 1
    with _explicit_product_version_writes():
        locked_product.save()
    return locked_product


def _snapshot_from_locked_product(product: Product) -> ProductSnapshot:
    links = _active_links_locked(product)
    concept_ids = sorted({link.concept_id for link in links}, key=str)
    concepts = {
        concept.id: concept
        for concept in KnowledgeConcept.objects.select_for_update()
        .filter(pk__in=concept_ids)
        .order_by("id")
    }
    valid_links = []
    for link in links:
        concept = concepts.get(link.concept_id)
        if (
            link.organization_id == product.organization_id
            and concept is not None
            and concept.organization_id in {None, product.organization_id}
            and concept.status == KnowledgeConcept.Status.APPROVED
            and concept.concept_type in ROLE_CONCEPT_TYPES.get(link.role, ())
        ):
            valid_links.append((link, concept))
    valid_links.sort(key=lambda item: (item[0].role, item[1].code, str(item[0].id)))
    return ProductSnapshot(
        product_id=product.id,
        product_version=product.version,
        name_zh=product.name_zh,
        name_en=product.name_en,
        module_min=product.module_min,
        module_max=product.module_max,
        tooth_count_min=product.tooth_count_min,
        tooth_count_max=product.tooth_count_max,
        pressure_angle=product.pressure_angle,
        accuracy_grade=product.accuracy_grade,
        heat_treatment=product.heat_treatment,
        surface_treatment=product.surface_treatment,
        manufacturing_capabilities=tuple(product.manufacturing_capabilities),
        inspection_capabilities=tuple(product.inspection_capabilities),
        moq=product.moq,
        lead_time=product.lead_time,
        landing_page_url=product.landing_page_url,
        status=product.status,
        concept_versions=tuple(
            ProductConceptVersion(
                link_id=link.id,
                link_version=link.version,
                role=link.role,
                concept_id=concept.id,
                concept_code=concept.code,
                concept_type=concept.concept_type,
                concept_version=concept.version,
            )
            for link, concept in valid_links
        ),
    )


@transaction.atomic
def build_product_snapshot(product: Product) -> ProductSnapshot:
    locked_product = _lock_product(product)
    return _snapshot_from_locked_product(locked_product)


@transaction.atomic
def build_product_generation_context(product: Product) -> ProductGenerationContext:
    locked_product = _lock_product(product)
    snapshot = _snapshot_from_locked_product(locked_product)
    ontology = OntologyContextService(locked_product.organization).build_snapshot(
        concept_ids=[item.concept_id for item in snapshot.concept_versions],
        max_depth=2,
    )
    return ProductGenerationContext(product=snapshot, ontology=ontology)
