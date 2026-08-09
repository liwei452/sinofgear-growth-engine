import re
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models, transaction
from django.db.models.deletion import ProtectedError
from django.db.models.expressions import BaseExpression

from apps.assets.models import AssetProductLink, MaterialAsset
from apps.catalog.models import Product
from apps.common.models import OrganizationScopedModel
from apps.knowledge.models import KnowledgeConcept
from apps.platforms.models import Platform


_allow_lifecycle_write: ContextVar[bool] = ContextVar(
    "campaigns_allow_lifecycle_write", default=False
)
_allow_revision_write: ContextVar[bool] = ContextVar(
    "campaigns_allow_revision_write", default=False
)
_allow_draft_link_replacement: ContextVar[bool] = ContextVar(
    "campaigns_allow_draft_link_replacement", default=False
)


@contextmanager
def lifecycle_writes() -> Iterator[None]:
    token = _allow_lifecycle_write.set(True)
    try:
        yield
    finally:
        _allow_lifecycle_write.reset(token)


@contextmanager
def revision_writes() -> Iterator[None]:
    token = _allow_revision_write.set(True)
    try:
        yield
    finally:
        _allow_revision_write.reset(token)


@contextmanager
def draft_link_replacement_writes() -> Iterator[None]:
    token = _allow_draft_link_replacement.set(True)
    try:
        yield
    finally:
        _allow_draft_link_replacement.reset(token)


def normalize_list_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def validate_text_list(value: object) -> None:
    if not isinstance(value, list):
        raise ValidationError("Value must be a JSON list of non-blank strings.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError("Every list value must be a non-blank string.")
    normalized = [normalize_list_text(item) for item in value]
    if len(normalized) != len(set(normalized)):
        raise ValidationError("List values must be unique after normalization.")


class VersionedQuerySet(models.QuerySet):
    @transaction.atomic
    def update(self, **kwargs):
        if "version" in kwargs:
            raise ValidationError("Version cannot be assigned directly.")
        if {"organization", "organization_id"} & set(kwargs):
            raise ValidationError("Organization is immutable after creation.")
        rows = list(self.select_for_update().order_by("pk"))
        for row in rows:
            for field, value in kwargs.items():
                if isinstance(value, BaseExpression):
                    raise ValidationError("Expression updates are not supported.")
                setattr(row, field, value)
            row.save(update_fields=[*kwargs, "updated_at"])
        return len(rows)

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Bulk upserts are not supported.")
        rows = sorted(objs, key=lambda row: str(row.pk))
        for row in rows:
            row.full_clean()
        return super().bulk_create(rows, **kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        names = {field.name if hasattr(field, "name") else str(field) for field in fields}
        if "version" in names or {"organization", "organization_id"} & names:
            raise ValidationError("Version and organization cannot be bulk updated.")
        rows = sorted(objs, key=lambda row: str(row.pk))
        for row in rows:
            row.save(update_fields=[*names, "updated_at"])
        return len(rows)


class VersionedManager(models.Manager.from_queryset(VersionedQuerySet)):
    pass


class Campaign(OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        ARCHIVED = "ARCHIVED", "Archived"

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1)

    objects = VersionedManager()

    class Meta:
        ordering = ["-created_at", "-id"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.CheckConstraint(condition=models.Q(version__gt=0), name="campaigns_campaign_version_positive")
        ]

    def clean(self) -> None:
        self.name = self.name.strip()
        self.description = self.description.strip()
        if not self.name:
            raise ValidationError({"name": "Campaign name must not be blank."})
        if self._state.adding and self.version != 1:
            raise ValidationError({"version": "Campaigns must start at version 1."})

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            original = type(self).objects.select_for_update().get(pk=self.pk)
            if original.organization_id != self.organization_id:
                raise ValidationError("Campaign organization is immutable.")
            if self.version != original.version:
                raise ValidationError("Campaign version cannot be assigned directly.")
            elif any(
                getattr(self, field) != getattr(original, field)
                for field in ("name", "description", "status")
            ):
                self.version = original.version + 1
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {"version"}
        self.full_clean()
        super().save(*args, **kwargs)


GENERATION_FIELDS = (
    "campaign_id",
    "target_country",
    "customer_type",
    "content_objective",
    "cta",
    "landing_page_url",
    "language",
    "prohibited_claims",
    "selling_points",
    "advantages",
    "keywords",
)


class ContentBrief(OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        READY = "READY", "Ready"

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="briefs")
    previous_version = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="revisions"
    )
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    target_country = models.CharField(max_length=128, blank=True)
    customer_type = models.CharField(max_length=255, blank=True)
    content_objective = models.TextField(blank=True)
    cta = models.CharField(max_length=512, blank=True)
    landing_page_url = models.URLField(max_length=2048, blank=True)
    language = models.CharField(max_length=16, blank=True)
    prohibited_claims = models.JSONField(default=list, blank=True, validators=[validate_text_list])
    selling_points = models.JSONField(default=list, blank=True, validators=[validate_text_list])
    advantages = models.JSONField(default=list, blank=True, validators=[validate_text_list])
    keywords = models.JSONField(default=list, blank=True, validators=[validate_text_list])
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_content_briefs"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_content_briefs",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    objects = VersionedManager()

    class Meta:
        ordering = ["-created_at", "-id"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.CheckConstraint(condition=models.Q(version__gt=0), name="campaigns_brief_version_positive"),
            models.UniqueConstraint(fields=["previous_version"], condition=models.Q(previous_version__isnull=False), name="campaigns_one_direct_revision"),
        ]

    def clean(self) -> None:
        if self.organization_id and self.campaign_id:
            campaign = Campaign.objects.filter(pk=self.campaign_id).first()
            if campaign is None or campaign.organization_id != self.organization_id:
                raise ValidationError({"campaign": "Campaign is not visible to this organization."})
        if self._state.adding:
            if self.previous_version_id is None:
                if self.version != 1:
                    raise ValidationError({"version": "Content briefs must start at version 1."})
            else:
                if not _allow_revision_write.get():
                    raise ValidationError(
                        {"previous_version": "Revisions must be created through the revision service."}
                    )
                previous = ContentBrief.objects.filter(pk=self.previous_version_id).first()
                if (
                    previous is None
                    or previous.id == self.id
                    or previous.organization_id != self.organization_id
                    or previous.campaign_id != self.campaign_id
                    or previous.status != self.Status.READY
                    or self.version != previous.version + 1
                ):
                    raise ValidationError(
                        {"previous_version": "Revision source, campaign, organization, status and sequence are invalid."}
                    )
        for field in GENERATION_FIELDS[1:6]:
            value = getattr(self, field)
            setattr(self, field, value.strip())
        self.language = self.language.strip().lower()
        if self.landing_page_url:
            URLValidator(schemes=["http", "https"])(self.landing_page_url)
        for field in ("prohibited_claims", "selling_points", "advantages", "keywords"):
            validate_text_list(getattr(self, field))
        prohibited = {normalize_list_text(item) for item in self.prohibited_claims}
        selling = {normalize_list_text(item) for item in self.selling_points}
        if prohibited & selling:
            raise ValidationError(
                {
                    "prohibited_claims": "Prohibited claims must not duplicate selling points.",
                    "selling_points": "Selling points must not duplicate prohibited claims.",
                }
            )

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            original = type(self).objects.select_for_update().get(pk=self.pk)
            if original.organization_id != self.organization_id:
                raise ValidationError("Content brief organization is immutable.")
            if original.previous_version_id != self.previous_version_id:
                raise ValidationError("Content brief revision identity is immutable.")
            changed = {
                field
                for field in (*GENERATION_FIELDS, "status", "previous_version_id")
                if getattr(self, field) != getattr(original, field)
            }
            if original.status == self.Status.READY and changed:
                raise ValidationError("READY content briefs are immutable; create a revision.")
            if self.status != original.status and not _allow_lifecycle_write.get():
                raise ValidationError("Content brief lifecycle changes require the service.")
            if self.version != original.version:
                if not _allow_revision_write.get() or self.version != original.version + 1:
                    raise ValidationError("Content brief version may change only through a versioned write.")
            elif changed:
                self.version = original.version + 1
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {"version"}
        self.full_clean()
        super().save(*args, **kwargs)


LINK_IDENTITY_FIELDS = frozenset(
    {"id", "pk", "organization", "organization_id", "campaign", "campaign_id", "brief", "brief_id", "product", "product_id", "asset", "asset_id", "platform", "platform_id", "concept", "concept_id", "role"}
)


class ImmutableLinkQuerySet(models.QuerySet):
    @staticmethod
    def _lock_brief_parents(rows):
        brief_ids = sorted(
            {row.brief_id for row in rows if hasattr(row, "brief_id")}, key=str
        )
        briefs = {
            brief.id: brief
            for brief in ContentBrief.objects.select_for_update()
            .filter(pk__in=brief_ids)
            .order_by("id")
        }
        for row in rows:
            if hasattr(row, "brief_id"):
                brief = briefs.get(row.brief_id)
                if brief is None:
                    raise ValidationError("Brief relationship parent does not exist.")
                row.brief = brief

    @transaction.atomic
    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Link bulk upserts are not supported.")
        rows = sorted(objs, key=lambda row: str(row.pk))
        self._lock_brief_parents(rows)
        for row in rows:
            row.full_clean()
        created = super().bulk_create(rows, **kwargs)
        for row in created:
            row._loaded_pk = row.pk
        return created

    def update(self, **kwargs):
        if LINK_IDENTITY_FIELDS & set(kwargs):
            raise ValidationError("Historical relationship identity is immutable.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        names = {field.name if hasattr(field, "name") else str(field) for field in fields}
        if LINK_IDENTITY_FIELDS & names:
            raise ValidationError("Historical relationship identity is immutable.")
        return super().bulk_update(objs, fields, **kwargs)

    def delete(self):
        protected = list(self)
        if protected:
            if _allow_draft_link_replacement.get() and all(
                not hasattr(row, "brief_id")
                or row.brief.status == ContentBrief.Status.DRAFT
                for row in protected
            ):
                return super().delete()
            raise ProtectedError("Historical campaign relationships cannot be deleted.", protected)
        return 0, {}


class ImmutableLinkManager(models.Manager.from_queryset(ImmutableLinkQuerySet)):
    pass


class ImmutableLink(OrganizationScopedModel):
    objects = ImmutableLinkManager()

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_pk = instance.pk
        return instance

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    @property
    def identity_fields(self) -> tuple[str, ...]:
        raise NotImplementedError

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        if self._state.adding and hasattr(self, "brief_id"):
            try:
                self.brief = ContentBrief.objects.select_for_update().get(pk=self.brief_id)
            except ContentBrief.DoesNotExist as error:
                raise ValidationError("Brief relationship parent does not exist.") from error
        if not self._state.adding:
            loaded_pk = getattr(self, "_loaded_pk", self.pk)
            if self.pk != loaded_pk:
                raise ValidationError("Historical relationship identity is immutable.")
            original = type(self).objects.select_for_update().get(pk=loaded_pk)
            if any(getattr(self, field) != getattr(original, field) for field in self.identity_fields):
                raise ValidationError("Historical relationship identity is immutable.")
        self.full_clean()
        super().save(*args, **kwargs)
        self._loaded_pk = self.pk

    def delete(self, *args, **kwargs):
        raise ProtectedError("Historical campaign relationships cannot be deleted.", [self])


def _ensure_draft(brief: ContentBrief) -> None:
    if brief.status != ContentBrief.Status.DRAFT:
        raise ValidationError("READY content brief relationships are immutable.")


class CampaignProduct(ImmutableLink):
    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="product_links")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="campaign_links")

    class Meta(ImmutableLink.Meta):
        constraints = [models.UniqueConstraint(fields=["campaign", "product"], name="campaigns_unique_campaign_product")]

    @property
    def identity_fields(self):
        return ("id", "organization_id", "campaign_id", "product_id")

    def clean(self):
        campaign = Campaign.objects.filter(pk=self.campaign_id).first()
        product = Product.objects.filter(pk=self.product_id).first()
        if campaign is None or product is None or campaign.organization_id != self.organization_id or product.organization_id != self.organization_id:
            raise ValidationError("Campaign product references must share one organization.")
        if self._state.adding and product.status != Product.Status.ACTIVE:
            raise ValidationError("New campaign product selections require an active product.")


class ContentBriefProduct(ImmutableLink):
    brief = models.ForeignKey(ContentBrief, on_delete=models.PROTECT, related_name="product_links")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="content_brief_links")

    class Meta(ImmutableLink.Meta):
        constraints = [models.UniqueConstraint(fields=["brief", "product"], name="campaigns_unique_brief_product")]

    @property
    def identity_fields(self):
        return ("id", "organization_id", "brief_id", "product_id")

    def clean(self):
        brief = ContentBrief.objects.filter(pk=self.brief_id).first()
        product = Product.objects.filter(pk=self.product_id).first()
        if brief is None or product is None or brief.organization_id != self.organization_id or product.organization_id != self.organization_id:
            raise ValidationError("Brief product references must share one organization.")
        _ensure_draft(brief)
        if self._state.adding and product.status != Product.Status.ACTIVE:
            raise ValidationError("New brief product selections require an active product.")


class ContentBriefAsset(ImmutableLink):
    brief = models.ForeignKey(ContentBrief, on_delete=models.PROTECT, related_name="asset_links")
    asset = models.ForeignKey(MaterialAsset, on_delete=models.PROTECT, related_name="content_brief_links")

    class Meta(ImmutableLink.Meta):
        constraints = [models.UniqueConstraint(fields=["brief", "asset"], name="campaigns_unique_brief_asset")]

    @property
    def identity_fields(self):
        return ("id", "organization_id", "brief_id", "asset_id")

    def clean(self):
        brief = ContentBrief.objects.filter(pk=self.brief_id).first()
        asset = MaterialAsset.objects.filter(pk=self.asset_id).first()
        if brief is None or asset is None or brief.organization_id != self.organization_id or asset.organization_id != self.organization_id:
            raise ValidationError("Brief asset references must share one organization.")
        _ensure_draft(brief)
        if asset.status != MaterialAsset.Status.ACTIVE:
            raise ValidationError("Selected brief assets must be active.")
        linked_products = set(
            AssetProductLink.objects.filter(asset=asset, organization=self.organization).values_list("product_id", flat=True)
        )
        selected_products = set(brief.product_links.values_list("product_id", flat=True))
        if linked_products and not linked_products & selected_products:
            raise ValidationError("A product-linked asset must match a selected brief product.")


class ContentBriefPlatform(ImmutableLink):
    brief = models.ForeignKey(ContentBrief, on_delete=models.PROTECT, related_name="platform_links")
    platform = models.ForeignKey(Platform, on_delete=models.PROTECT, related_name="content_brief_links")

    class Meta(ImmutableLink.Meta):
        constraints = [models.UniqueConstraint(fields=["brief", "platform"], name="campaigns_unique_brief_platform")]

    @property
    def identity_fields(self):
        return ("id", "organization_id", "brief_id", "platform_id")

    def clean(self):
        brief = ContentBrief.objects.filter(pk=self.brief_id).first()
        platform = Platform.objects.filter(pk=self.platform_id).first()
        if brief is None or platform is None or brief.organization_id != self.organization_id:
            raise ValidationError("Brief platform references are invalid.")
        _ensure_draft(brief)


BRIEF_ROLE_CONCEPT_TYPES = {
    "TARGET_INDUSTRY": KnowledgeConcept.ConceptType.INDUSTRY,
    "TARGET_CUSTOMER_TYPE": KnowledgeConcept.ConceptType.CUSTOMER_TYPE,
    "PURCHASE_INTENT": KnowledgeConcept.ConceptType.PURCHASE_INTENT,
    "STANDARD": KnowledgeConcept.ConceptType.STANDARD,
    "APPLICATION": KnowledgeConcept.ConceptType.APPLICATION,
}


class ContentBriefConceptLink(ImmutableLink):
    class Role(models.TextChoices):
        TARGET_INDUSTRY = "TARGET_INDUSTRY", "Target industry"
        TARGET_CUSTOMER_TYPE = "TARGET_CUSTOMER_TYPE", "Target customer type"
        PURCHASE_INTENT = "PURCHASE_INTENT", "Purchase intent"
        STANDARD = "STANDARD", "Standard"
        APPLICATION = "APPLICATION", "Application"

    brief = models.ForeignKey(ContentBrief, on_delete=models.PROTECT, related_name="concept_links")
    concept = models.ForeignKey(KnowledgeConcept, on_delete=models.PROTECT, related_name="content_brief_links")
    role = models.CharField(max_length=32, choices=Role.choices)

    class Meta(ImmutableLink.Meta):
        constraints = [models.UniqueConstraint(fields=["brief", "role", "concept"], name="campaigns_unique_brief_role_concept")]

    @property
    def identity_fields(self):
        return ("id", "organization_id", "brief_id", "concept_id", "role")

    def clean(self):
        brief = ContentBrief.objects.filter(pk=self.brief_id).first()
        concept = KnowledgeConcept.objects.filter(pk=self.concept_id).first()
        if brief is None or concept is None or brief.organization_id != self.organization_id:
            raise ValidationError("Brief concept references are invalid.")
        _ensure_draft(brief)
        if concept.organization_id not in {None, self.organization_id}:
            raise ValidationError("Concept is not visible to the brief organization.")
        if concept.status != KnowledgeConcept.Status.APPROVED:
            raise ValidationError("Only APPROVED concepts may be selected.")
        if concept.concept_type != BRIEF_ROLE_CONCEPT_TYPES.get(self.role):
            raise ValidationError("Concept type does not match the brief concept role.")
