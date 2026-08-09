from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.assets.models import AssetProductLink, MaterialAsset
from apps.catalog.models import Product, ProductConceptLink
from apps.catalog.services import ProductSnapshot, _snapshot_from_locked_product
from apps.knowledge.models import KnowledgeConcept
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
    lifecycle_writes,
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
    list(brief.product_links.select_for_update().order_by("id"))
    list(brief.asset_links.select_for_update().order_by("id"))
    list(brief.platform_links.select_for_update().order_by("id"))
    list(brief.concept_links.select_for_update().order_by("id"))
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
    generated_at: datetime

    def to_dict(self) -> dict[str, object]:
        return _json_value(asdict(self))


def _json_value(value):
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (UUID, datetime, Decimal)):
        return str(value)
    return value


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
    ontology = OntologyContextService(brief.organization).build_snapshot(
        concept_ids=sorted(ontology_ids, key=str), max_depth=2
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
        generated_at=timezone.now(),
    )
