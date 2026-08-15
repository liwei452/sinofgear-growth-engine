from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.assets.models import AssetProductLink, MaterialAsset, ProductEvidenceFact
from apps.catalog.models import Product, ProductConceptLink
from apps.catalog.services import ProductSnapshot, _snapshot_from_locked_product
from apps.knowledge.graph import acquire_knowledge_graph_lock
from apps.knowledge.models import (
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeRelation,
)
from apps.knowledge.services import OntologyContextService, OntologySnapshot
from apps.platforms.models import Platform, PlatformCapability

from .models import (
    BRIEF_ROLE_CONCEPT_TYPES,
    Campaign,
    CampaignProduct,
    ContentBrief,
    ContentBriefAsset,
    ContentBriefConceptLink,
    ContentBriefPlatform,
    ContentBriefProduct,
    draft_link_replacement_writes,
    lifecycle_writes,
    revision_writes,
)


def _unique_ids(values, field: str) -> tuple[UUID, ...]:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise ValidationError({field: ["Duplicate selections are not allowed."]})
    return items


@transaction.atomic
def create_campaign(*, organization, values, product_ids=()) -> Campaign:
    product_ids = _unique_ids(product_ids, "product_ids")
    campaign = Campaign.objects.create(organization=organization, **values)
    CampaignProduct.objects.bulk_create(
        [
            CampaignProduct(organization=organization, campaign=campaign, product_id=item)
            for item in product_ids
        ]
    )
    return campaign


@transaction.atomic
def create_content_brief(
    *,
    organization,
    campaign,
    creator,
    values,
    product_ids,
    asset_ids,
    platform_ids,
    concept_links,
) -> ContentBrief:
    campaign = Campaign.objects.select_for_update().get(
        pk=campaign.pk, organization=organization
    )
    product_ids = _unique_ids(product_ids, "product_ids")
    asset_ids = _unique_ids(asset_ids, "asset_ids")
    platform_ids = _unique_ids(platform_ids, "platform_ids")
    specs = tuple(concept_links)
    keys = tuple((item["role"], item["concept_id"]) for item in specs)
    if len(keys) != len(set(keys)):
        raise ValidationError({"concept_links": ["Duplicate role/concept pairs are not allowed."]})
    brief = ContentBrief.objects.create(
        organization=organization,
        campaign=campaign,
        created_by=creator,
        **values,
    )
    ContentBriefProduct.objects.bulk_create(
        [
            ContentBriefProduct(organization=organization, brief=brief, product_id=item)
            for item in product_ids
        ]
    )
    ContentBriefPlatform.objects.bulk_create(
        [
            ContentBriefPlatform(organization=organization, brief=brief, platform_id=item)
            for item in platform_ids
        ]
    )
    ContentBriefConceptLink.objects.bulk_create(
        [
            ContentBriefConceptLink(
                organization=organization,
                brief=brief,
                role=item["role"],
                concept_id=item["concept_id"],
            )
            for item in specs
        ]
    )
    ContentBriefAsset.objects.bulk_create(
        [
            ContentBriefAsset(organization=organization, brief=brief, asset_id=item)
            for item in asset_ids
        ]
    )
    return brief


BRIEF_MUTABLE_FIELDS = frozenset(
    {
        "target_country", "customer_type", "content_objective", "cta",
        "landing_page_url", "language", "prohibited_claims", "selling_points",
        "advantages", "keywords",
    }
)


@transaction.atomic
def update_content_brief(
    brief_id: UUID,
    *,
    values,
    product_ids=None,
    asset_ids=None,
    platform_ids=None,
    concept_links=None,
) -> ContentBrief:
    brief = ContentBrief.objects.select_for_update().get(pk=brief_id)
    if brief.status != ContentBrief.Status.DRAFT:
        raise ValidationError({"status": ["Only DRAFT briefs can be edited."]})
    unknown = set(values) - BRIEF_MUTABLE_FIELDS
    if unknown:
        raise ValidationError({name: ["Unknown field."] for name in sorted(unknown)})

    current_products = tuple(
        brief.product_links.select_for_update().order_by("product_id").values_list(
            "product_id", flat=True
        )
    )
    current_assets = tuple(
        brief.asset_links.select_for_update().order_by("asset_id").values_list(
            "asset_id", flat=True
        )
    )
    current_platforms = tuple(
        brief.platform_links.select_for_update().order_by("platform_id").values_list(
            "platform_id", flat=True
        )
    )
    current_concepts = tuple(
        brief.concept_links.select_for_update()
        .order_by("role", "concept_id")
        .values_list("role", "concept_id")
    )
    desired_products = (
        current_products if product_ids is None else tuple(sorted(_unique_ids(product_ids, "product_ids"), key=str))
    )
    desired_assets = (
        current_assets if asset_ids is None else tuple(sorted(_unique_ids(asset_ids, "asset_ids"), key=str))
    )
    desired_platforms = (
        current_platforms if platform_ids is None else tuple(sorted(_unique_ids(platform_ids, "platform_ids"), key=str))
    )
    if concept_links is None:
        desired_concepts = current_concepts
    else:
        specs = tuple(concept_links)
        desired_concepts = tuple(
            sorted(
                ((item["role"], item["concept_id"]) for item in specs),
                key=lambda item: (item[0], str(item[1])),
            )
        )
        if len(desired_concepts) != len(set(desired_concepts)):
            raise ValidationError({"concept_links": ["Duplicate role/concept pairs are not allowed."]})

    scalar_changed = any(getattr(brief, key) != value for key, value in values.items())
    relation_changed = (
        desired_products != current_products
        or desired_assets != current_assets
        or desired_platforms != current_platforms
        or desired_concepts != current_concepts
    )
    if not scalar_changed and not relation_changed:
        return brief

    if scalar_changed:
        for key, value in values.items():
            setattr(brief, key, value)
        brief.save()

    if relation_changed:
        with draft_link_replacement_writes():
            brief.asset_links.all().delete()
            brief.concept_links.all().delete()
            brief.platform_links.all().delete()
            brief.product_links.all().delete()
        ContentBriefProduct.objects.bulk_create([
            ContentBriefProduct(organization=brief.organization, brief=brief, product_id=item)
            for item in desired_products
        ])
        ContentBriefPlatform.objects.bulk_create([
            ContentBriefPlatform(organization=brief.organization, brief=brief, platform_id=item)
            for item in desired_platforms
        ])
        ContentBriefConceptLink.objects.bulk_create([
            ContentBriefConceptLink(
                organization=brief.organization, brief=brief, role=role, concept_id=concept_id
            )
            for role, concept_id in desired_concepts
        ])
        ContentBriefAsset.objects.bulk_create([
            ContentBriefAsset(organization=brief.organization, brief=brief, asset_id=item)
            for item in desired_assets
        ])
        if not scalar_changed:
            brief.version += 1
            with revision_writes():
                brief.save(update_fields=["version", "updated_at"])
    return brief


def _ready_errors(brief: ContentBrief) -> dict[str, list[str]]:
    errors = {}
    for field in (
        "target_country",
        "customer_type",
        "content_objective",
        "cta",
        "landing_page_url",
        "language",
    ):
        if not getattr(brief, field).strip():
            errors[field] = ["This field is required before READY."]
    for field in ("selling_points", "advantages", "keywords"):
        if not getattr(brief, field):
            errors[field] = ["At least one value is required before READY."]
    if not brief.product_links.exists():
        errors["products"] = ["At least one product is required before READY."]
    if not brief.platform_links.exists():
        errors["target_platforms"] = ["At least one target platform is required before READY."]
    return errors


@transaction.atomic
def mark_content_brief_ready(brief_id: UUID, *, reviewer) -> ContentBrief:
    brief = ContentBrief.objects.select_for_update().get(pk=brief_id)
    if brief.status != ContentBrief.Status.DRAFT:
        raise ValidationError({"status": ["Only DRAFT briefs can be marked READY."]})
    Campaign.objects.select_for_update().get(pk=brief.campaign_id)
    product_links = list(brief.product_links.select_for_update().order_by("id"))
    asset_links = list(brief.asset_links.select_for_update().order_by("id"))
    platform_links = list(brief.platform_links.select_for_update().order_by("id"))
    concept_links = list(brief.concept_links.select_for_update().order_by("id"))
    products = {
        row.id: row
        for row in Product.objects.select_for_update()
        .filter(id__in=[link.product_id for link in product_links])
        .order_by("id")
    }
    assets = {
        row.id: row
        for row in MaterialAsset.objects.select_for_update()
        .filter(id__in=[link.asset_id for link in asset_links])
        .order_by("id")
    }
    platforms = {
        row.id: row
        for row in Platform.objects.select_for_update()
        .filter(id__in=[link.platform_id for link in platform_links])
        .order_by("id")
    }
    concepts = {
        row.id: row
        for row in KnowledgeConcept.objects.select_for_update()
        .filter(id__in=[link.concept_id for link in concept_links])
        .order_by("id")
    }
    list(
        AssetProductLink.objects.select_for_update()
        .filter(asset_id__in=assets)
        .order_by("asset_id", "product_id", "id")
    )
    for link in product_links:
        if link.product_id in products:
            link.product = products[link.product_id]
        link.full_clean()
    for link in asset_links:
        if link.asset_id in assets:
            link.asset = assets[link.asset_id]
        link.full_clean()
    for link in platform_links:
        if link.platform_id in platforms:
            link.platform = platforms[link.platform_id]
        link.full_clean()
    for link in concept_links:
        if link.concept_id in concepts:
            link.concept = concepts[link.concept_id]
        link.full_clean()
    errors = _ready_errors(brief)
    if errors:
        raise ValidationError(errors)
    brief.full_clean()
    brief.status = ContentBrief.Status.READY
    brief.reviewed_by = reviewer
    brief.reviewed_at = timezone.now()
    with lifecycle_writes():
        brief.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
    return brief


@transaction.atomic
def revise_content_brief(brief_id: UUID, *, creator) -> ContentBrief:
    source = ContentBrief.objects.select_for_update().get(pk=brief_id)
    if source.status != ContentBrief.Status.READY:
        raise ValidationError({"status": ["Only READY briefs can be revised."]})
    if source.revisions.exists():
        raise ValidationError({"revision": ["This brief already has a direct revision."]})
    values = {field: getattr(source, field) for field in (
        "target_country", "customer_type", "content_objective", "cta",
        "landing_page_url", "language", "prohibited_claims", "selling_points",
        "advantages", "keywords",
    )}
    revision = ContentBrief(
        organization=source.organization,
        campaign=source.campaign,
        previous_version=source,
        version=source.version + 1,
        created_by=creator,
        **values,
    )
    with revision_writes():
        revision.full_clean()
        revision.save(force_insert=True)
    ContentBriefProduct.objects.bulk_create([
        ContentBriefProduct(organization=source.organization, brief=revision, product_id=value)
        for value in source.product_links.values_list("product_id", flat=True)
    ])
    ContentBriefPlatform.objects.bulk_create([
        ContentBriefPlatform(organization=source.organization, brief=revision, platform_id=value)
        for value in source.platform_links.values_list("platform_id", flat=True)
    ])
    ContentBriefAsset.objects.bulk_create([
        ContentBriefAsset(organization=source.organization, brief=revision, asset_id=value)
        for value in source.asset_links.values_list("asset_id", flat=True)
    ])
    ContentBriefConceptLink.objects.bulk_create([
        ContentBriefConceptLink(
            organization=source.organization,
            brief=revision,
            concept_id=concept_id,
            role=role,
        )
        for concept_id, role in source.concept_links.values_list("concept_id", "role")
    ])
    return revision


@dataclass(frozen=True)
class AssetSnapshot:
    asset_id: UUID
    checksum: str
    mime_type: str
    asset_type: str
    language: str
    tags: tuple[str, ...]
    product_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class PlatformSnapshot:
    platform_id: UUID
    code: str
    name: str
    capability_codes: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedProductFactSnapshot:
    fact_id: UUID
    product_id: UUID
    field_name: str
    value: str
    category: str
    source_asset_id: UUID
    source_filename: str
    source_page: int | None
    source_excerpt: str
    is_demo: bool


@dataclass(frozen=True)
class ContentGenerationInput:
    organization_id: UUID
    brief_id: UUID
    brief_version: int
    campaign_id: UUID
    campaign_version: int
    products: tuple[ProductSnapshot, ...]
    assets: tuple[AssetSnapshot, ...]
    target_country: str
    customer_type: str
    content_objective: str
    cta: str
    landing_page_url: str
    language: str
    keywords: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    selling_points: tuple[str, ...]
    advantages: tuple[str, ...]
    target_platforms: tuple[PlatformSnapshot, ...]
    ontology_snapshot: OntologySnapshot
    verified_product_facts: tuple[VerifiedProductFactSnapshot, ...]
    generated_at: datetime

    def to_dict(self) -> dict[str, object]:
        from .generation_schema import CONTENT_GENERATION_INPUT_SCHEMA_VERSION

        return {
            "schema_version": CONTENT_GENERATION_INPUT_SCHEMA_VERSION,
            **_json_value(asdict(self)),
        }


def _json_value(value):
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (UUID, datetime, Decimal)):
        return str(value)
    return value


def _lock_through_rows(through_model, source_model, source_ids):
    source_field = next(
        field
        for field in through_model._meta.fields
        if getattr(field, "related_model", None) is source_model
    )
    return list(
        through_model.objects.select_for_update()
        .filter(**{f"{source_field.attname}__in": source_ids})
        .order_by("pk")
    )


def _build_locked_ontology_snapshot(*, organization, concept_ids):
    acquire_knowledge_graph_lock()
    service = OntologyContextService(organization)
    discovered = service.build_snapshot(concept_ids=concept_ids, max_depth=2)
    locked_concept_ids = {item.concept_id for item in discovered.concept_versions}
    locked_relation_ids = {item.relation_id for item in discovered.relation_versions}
    locked_evidence_ids = {item.evidence_id for item in discovered.evidence_references}
    list(
        KnowledgeConcept.objects.select_for_update()
        .filter(pk__in=locked_concept_ids)
        .order_by("id")
    )
    list(
        KnowledgeRelation.objects.select_for_update()
        .filter(pk__in=locked_relation_ids)
        .order_by("id")
    )
    list(
        KnowledgeEvidence.objects.select_for_update()
        .filter(pk__in=locked_evidence_ids)
        .order_by("id")
    )
    _lock_through_rows(
        KnowledgeConcept.evidence.through, KnowledgeConcept, locked_concept_ids
    )
    _lock_through_rows(
        KnowledgeRelation.evidence.through, KnowledgeRelation, locked_relation_ids
    )
    snapshot = service.build_snapshot(concept_ids=concept_ids, max_depth=2)
    if (
        {item.concept_id for item in snapshot.concept_versions} != locked_concept_ids
        or {item.relation_id for item in snapshot.relation_versions} != locked_relation_ids
        or {item.evidence_id for item in snapshot.evidence_references} != locked_evidence_ids
    ):
        raise ValidationError("Ontology changed while the generation snapshot was locked.")
    return snapshot


@transaction.atomic
def build_content_generation_input(brief_id: UUID) -> ContentGenerationInput:
    brief = (
        ContentBrief.objects.select_for_update(of=("self",))
        .select_related("organization", "campaign")
        .get(pk=brief_id)
    )
    if brief.status != ContentBrief.Status.READY:
        raise ValidationError({"status": ["Only READY briefs can be used for generation."]})
    errors = _ready_errors(brief)
    if errors:
        raise ValidationError(errors)

    campaign = Campaign.objects.select_for_update(of=("self",)).get(pk=brief.campaign_id)
    if campaign.organization_id != brief.organization_id:
        raise ValidationError("Campaign is not visible to the brief organization.")
    # Knowledge mutations acquire this singleton before concept/relation rows.
    # Match that order before product snapshotting locks concept rows.
    acquire_knowledge_graph_lock()

    product_links = list(
        brief.product_links.select_for_update(of=("self",)).order_by("product_id", "id")
    )
    product_ids = [link.product_id for link in product_links]
    if any(link.organization_id != brief.organization_id for link in product_links):
        raise ValidationError("Brief product references are invalid.")
    products = list(
        Product.objects.select_for_update(of=("self",))
        .filter(pk__in=product_ids)
        .order_by("id")
    )
    if len(products) != len(product_ids) or any(
        product.organization_id != brief.organization_id for product in products
    ):
        raise ValidationError("Brief product references are invalid.")
    product_snapshots = tuple(_snapshot_from_locked_product(product) for product in products)
    live_product_concept_link_ids = set(
        ProductConceptLink.objects.active()
        .select_for_update(of=("self",))
        .filter(product_id__in=product_ids)
        .values_list("id", flat=True)
    )
    snapshot_product_concept_link_ids = {
        item.link_id
        for snapshot in product_snapshots
        for item in snapshot.concept_versions
    }
    if live_product_concept_link_ids != snapshot_product_concept_link_ids:
        raise ValidationError("Product concepts must remain visible and approved.")

    asset_links = list(
        brief.asset_links.select_for_update(of=("self",)).order_by("asset_id", "id")
    )
    asset_ids = [link.asset_id for link in asset_links]
    if any(link.organization_id != brief.organization_id for link in asset_links):
        raise ValidationError("Brief asset references are invalid or inactive.")
    assets = list(
        MaterialAsset.objects.select_for_update(of=("self",))
        .filter(pk__in=asset_ids)
        .order_by("id")
    )
    if len(assets) != len(asset_ids) or any(
        asset.organization_id != brief.organization_id
        or asset.status != MaterialAsset.Status.ACTIVE
        for asset in assets
    ):
        raise ValidationError("Brief asset references are invalid or inactive.")
    asset_product_rows = list(
        AssetProductLink.objects.select_for_update(of=("self",))
        .filter(asset_id__in=asset_ids)
        .select_related("product")
        .order_by("asset_id", "product_id", "id")
    )
    products_by_asset: dict[UUID, list[UUID]] = {asset.id: [] for asset in assets}
    selected_product_ids = set(product_ids)
    for link in asset_product_rows:
        if (
            link.organization_id != brief.organization_id
            or link.product.organization_id != brief.organization_id
        ):
            raise ValidationError("Brief asset product references are invalid.")
        products_by_asset[link.asset_id].append(link.product_id)
    for asset_id, linked_product_ids in products_by_asset.items():
        if linked_product_ids and not selected_product_ids.intersection(linked_product_ids):
            raise ValidationError("A product-linked asset must match a selected brief product.")
    asset_snapshots = tuple(
        AssetSnapshot(
            asset_id=asset.id,
            checksum=asset.checksum,
            mime_type=asset.mime_type,
            asset_type=asset.asset_type,
            language=asset.language,
            tags=tuple(asset.tags),
            product_ids=tuple(sorted(products_by_asset[asset.id], key=str)),
        )
        for asset in assets
    )
    verified_fact_rows = list(
        ProductEvidenceFact.objects.select_for_update(of=("self",))
        .filter(
            organization=brief.organization,
            product_id__in=product_ids,
            review_status=ProductEvidenceFact.ReviewStatus.VERIFIED,
        )
        .order_by("product_id", "field_name", "source_page", "id")
    )
    verified_product_facts = tuple(
        VerifiedProductFactSnapshot(
            fact_id=fact.id,
            product_id=fact.product_id,
            field_name=fact.field_name,
            value=fact.value,
            category=fact.category,
            source_asset_id=fact.asset_id,
            source_filename=fact.asset.original_filename,
            source_page=fact.source_page,
            source_excerpt=fact.source_excerpt,
            is_demo=fact.is_demo,
        )
        for fact in verified_fact_rows
        if fact.asset.organization_id == brief.organization_id
        and fact.job.organization_id == brief.organization_id
    )

    platform_links = list(
        brief.platform_links.select_for_update(of=("self",)).order_by("platform_id", "id")
    )
    platform_ids = [link.platform_id for link in platform_links]
    if any(link.organization_id != brief.organization_id for link in platform_links):
        raise ValidationError("Brief platform references are invalid.")
    platforms = list(
        Platform.objects.select_for_update(of=("self",))
        .filter(pk__in=platform_ids)
        .order_by("code", "id")
    )
    if len(platforms) != len(platform_ids):
        raise ValidationError("Brief platform references are invalid.")
    capability_rows = list(
        PlatformCapability.objects.select_for_update(of=("self",))
        .filter(platform_id__in=platform_ids)
        .order_by("platform_id", "code", "id")
    )
    capabilities: dict[UUID, list[str]] = {platform.id: [] for platform in platforms}
    for capability in capability_rows:
        capabilities[capability.platform_id].append(capability.code)
    platform_snapshots = tuple(
        PlatformSnapshot(
            platform_id=platform.id,
            code=platform.code,
            name=platform.name,
            capability_codes=tuple(capabilities[platform.id]),
        )
        for platform in platforms
    )

    concept_links = list(
        brief.concept_links.select_for_update(of=("self",)).order_by("concept_id", "role", "id")
    )
    brief_concept_ids = [link.concept_id for link in concept_links]
    if any(link.organization_id != brief.organization_id for link in concept_links):
        raise ValidationError("Brief concepts must remain visible and approved.")
    concepts = {
        concept.id: concept
        for concept in KnowledgeConcept.objects.select_for_update(of=("self",))
        .filter(pk__in=brief_concept_ids)
        .order_by("id")
    }
    for link in concept_links:
        concept = concepts.get(link.concept_id)
        if (
            concept is None
            or concept.organization_id not in {None, brief.organization_id}
            or concept.status != KnowledgeConcept.Status.APPROVED
            or concept.concept_type != BRIEF_ROLE_CONCEPT_TYPES.get(link.role)
        ):
            raise ValidationError("Brief concepts must remain visible and approved.")
    ontology_ids = set(brief_concept_ids)
    for product_snapshot in product_snapshots:
        ontology_ids.update(item.concept_id for item in product_snapshot.concept_versions)
    ontology = _build_locked_ontology_snapshot(
        organization=brief.organization,
        concept_ids=sorted(ontology_ids, key=str),
    )
    included_ids = {item.concept_id for item in ontology.concept_versions}
    if not ontology_ids.issubset(included_ids):
        raise ValidationError("Generation concepts must remain visible and approved.")

    return ContentGenerationInput(
        organization_id=brief.organization_id,
        brief_id=brief.id,
        brief_version=brief.version,
        campaign_id=campaign.id,
        campaign_version=campaign.version,
        products=product_snapshots,
        assets=asset_snapshots,
        target_country=brief.target_country,
        customer_type=brief.customer_type,
        content_objective=brief.content_objective,
        cta=brief.cta,
        landing_page_url=brief.landing_page_url,
        language=brief.language,
        keywords=tuple(brief.keywords),
        prohibited_claims=tuple(brief.prohibited_claims),
        selling_points=tuple(brief.selling_points),
        advantages=tuple(brief.advantages),
        target_platforms=platform_snapshots,
        ontology_snapshot=ontology,
        verified_product_facts=verified_product_facts,
        generated_at=timezone.now(),
    )
