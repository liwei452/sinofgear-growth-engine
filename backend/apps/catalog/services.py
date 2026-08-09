from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.db import transaction

from apps.knowledge.models import KnowledgeConcept
from apps.knowledge.services import OntologyContextService, OntologySnapshot

from .models import Product, ProductConceptLink


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


def _approved_visible_links(product: Product):
    return (
        product.concept_links.filter(
            concept__status=KnowledgeConcept.Status.APPROVED,
        )
        .filter(Q(concept__organization__isnull=True) | Q(concept__organization=product.organization))
        .select_related("concept")
        .order_by("role", "concept__code", "id")
    )


def build_product_snapshot(product: Product) -> ProductSnapshot:
    links = tuple(
        ProductConceptVersion(
            link_id=link.id,
            link_version=link.version,
            role=link.role,
            concept_id=link.concept_id,
            concept_code=link.concept.code,
            concept_type=link.concept.concept_type,
            concept_version=link.concept.version,
        )
        for link in _approved_visible_links(product)
    )
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
        concept_versions=links,
    )


def build_product_generation_context(product: Product) -> ProductGenerationContext:
    snapshot = build_product_snapshot(product)
    ontology = OntologyContextService(product.organization).build_snapshot(
        concept_ids=[item.concept_id for item in snapshot.concept_versions],
        max_depth=2,
    )
    return ProductGenerationContext(product=snapshot, ontology=ontology)


@transaction.atomic
def create_product(*, organization, values: dict[str, object], concept_links) -> Product:
    product = Product.objects.create(organization=organization, **values)
    replace_product_links(product=product, concept_links=concept_links)
    return product


def replace_product_links(*, product: Product, concept_links) -> None:
    ProductConceptLink.objects.filter(product=product).delete()
    ProductConceptLink.objects.bulk_create(
        [
            ProductConceptLink(
                organization=product.organization,
                product=product,
                role=item["role"],
                concept=item["concept"],
            )
            for item in concept_links
        ]
    )


def update_product(*, product: Product, values: dict[str, object]) -> Product:
    missing = object()
    concept_links = values.pop("concept_links", missing)
    for field, value in values.items():
        setattr(product, field, value)
    product.version += 1
    product.save()
    if concept_links is not missing:
        replace_product_links(product=product, concept_links=concept_links)
    return product
