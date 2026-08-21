import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models, transaction
from django.db.models.expressions import BaseExpression

from .guards import CompanyRevisionModel


MAX_CONTEXT_LIST_ITEMS = 100
MAX_CONTEXT_LIST_ITEM_LENGTH = 255
LOWER_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def validate_context_string_list(value: object) -> None:
    if not isinstance(value, list):
        raise ValidationError("Value must be a JSON list.")
    if len(value) > MAX_CONTEXT_LIST_ITEMS:
        raise ValidationError(f"List may contain at most {MAX_CONTEXT_LIST_ITEMS} items.")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError("Every list item must be a non-blank string.")
        if len(item) > MAX_CONTEXT_LIST_ITEM_LENGTH:
            raise ValidationError(
                f"Every list item must be at most {MAX_CONTEXT_LIST_ITEM_LENGTH} characters."
            )


def _normalize_https_url(
    value: object,
    *,
    label: str,
    preserve_fragment: bool,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a valid HTTPS URL.")
    raw_value = value.strip()
    try:
        parts = urlsplit(raw_value)
        port = parts.port
    except ValueError as exc:
        raise ValidationError(f"{label} must be a valid HTTPS URL.") from exc
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValidationError(f"{label} must be a valid HTTPS URL.")
    if parts.username or parts.password:
        raise ValidationError(f"{label} must not contain user information.")
    try:
        hostname = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValidationError(f"{label} host is invalid.") from exc
    if not hostname:
        raise ValidationError(f"{label} host is invalid.")
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host if port in {None, 443} else f"{host}:{port}"
    normalized = urlunsplit(
        (
            "https",
            netloc,
            parts.path or "/",
            parts.query,
            parts.fragment if preserve_fragment else "",
        )
    )
    if len(normalized) > 2048:
        raise ValidationError(f"{label} must be a valid HTTPS URL.")
    try:
        URLValidator(schemes=["https"])(normalized)
    except ValidationError as exc:
        raise ValidationError(f"{label} must be a valid HTTPS URL.") from exc
    return normalized


def normalize_https_url(value: object) -> str:
    return _normalize_https_url(
        value,
        label="Canonical URL",
        preserve_fragment=False,
    )


def normalize_optional_cta_url(value: object) -> str:
    if value is None or value == "":
        return ""
    return _normalize_https_url(
        value,
        label="Primary CTA URL",
        preserve_fragment=True,
    )


class ICPProfile(CompanyRevisionModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        IN_REVIEW = "IN_REVIEW", "In review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="icp_profiles",
    )
    code = models.CharField(max_length=96)
    version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successor_icp_profiles",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    target_industries = models.JSONField(default=list, validators=[validate_context_string_list])
    company_types = models.JSONField(default=list, validators=[validate_context_string_list])
    buyer_roles = models.JSONField(default=list, validators=[validate_context_string_list])
    target_markets = models.JSONField(default=list, validators=[validate_context_string_list])
    languages = models.JSONField(default=list, validators=[validate_context_string_list])
    pain_points = models.JSONField(default=list, validators=[validate_context_string_list])
    buying_triggers = models.JSONField(default=list, validators=[validate_context_string_list])
    exclusion_rules = models.JSONField(default=list, validators=[validate_context_string_list])
    preferred_channels = models.JSONField(default=list, validators=[validate_context_string_list])
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_icp_profiles",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_icp_profiles",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    frozen_statuses = frozenset(
        {Status.IN_REVIEW, Status.APPROVED, Status.REJECTED, Status.SUPERSEDED}
    )
    frozen_label = "ICP profile"
    identity_fields = CompanyRevisionModel.identity_fields | frozenset({"code"})
    business_fields = frozenset(
        {
            "name",
            "description",
            "target_industries",
            "company_types",
            "buyer_roles",
            "target_markets",
            "languages",
            "pain_points",
            "buying_triggers",
            "exclusion_rules",
            "preferred_channels",
        }
    )
    list_fields = (
        "target_industries",
        "company_types",
        "buyer_roles",
        "target_markets",
        "languages",
        "pain_points",
        "buying_triggers",
        "exclusion_rules",
        "preferred_channels",
    )

    class Meta:
        ordering = ["organization_id", "code", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code", "version"],
                name="knowledge_unique_icp_profile_version",
            ),
            models.UniqueConstraint(
                fields=["organization", "code"],
                condition=models.Q(status="APPROVED"),
                name="knowledge_one_approved_icp_profile",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="knowledge_icp_profile_version_positive",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.code = self.code.strip().upper()
        self.name = self.name.strip()
        if not self.code:
            raise ValidationError({"code": "ICP code must not be blank."})
        if not self.name:
            raise ValidationError({"name": "ICP name must not be blank."})
        if self.version < 1:
            raise ValidationError({"version": "ICP version must be positive."})
        for field in self.list_fields:
            validate_context_string_list(getattr(self, field))
        if self.supersedes_id:
            previous = self.supersedes
            if previous.organization_id != self.organization_id or previous.code != self.code:
                raise ValidationError(
                    {"supersedes": "Superseded ICP must belong to the same organization and code."}
                )
            if self.version <= previous.version:
                raise ValidationError({"version": "An ICP revision version must increase."})


class WebsitePage(CompanyRevisionModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        IN_REVIEW = "IN_REVIEW", "In review"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    class PageType(models.TextChoices):
        HOME = "HOME", "Home"
        PRODUCT = "PRODUCT", "Product"
        INDUSTRY = "INDUSTRY", "Industry"
        APPLICATION = "APPLICATION", "Application"
        CAPABILITY = "CAPABILITY", "Capability"
        CASE_STUDY = "CASE_STUDY", "Case study"
        ABOUT = "ABOUT", "About"
        CONTACT = "CONTACT", "Contact"
        RFQ = "RFQ", "RFQ"
        OTHER = "OTHER", "Other"

    class SourceType(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        SIGNED_FEED = "SIGNED_FEED", "Signed feed"
        CRAWL = "CRAWL", "Crawl"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="website_pages",
    )
    canonical_url = models.URLField(max_length=2048)
    version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successor_website_pages",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    page_type = models.CharField(max_length=24, choices=PageType.choices)
    language = models.CharField(max_length=16)
    title = models.CharField(max_length=500)
    content_summary = models.TextField(blank=True)
    primary_cta_label = models.CharField(max_length=255, blank=True)
    primary_cta_url = models.URLField(max_length=2048, blank=True)
    seo_keywords = models.JSONField(default=list, validators=[validate_context_string_list])
    content_hash = models.CharField(max_length=64, blank=True, default="")
    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_website_pages",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_website_pages",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    frozen_statuses = frozenset(
        {Status.IN_REVIEW, Status.VERIFIED, Status.REJECTED, Status.SUPERSEDED}
    )
    frozen_label = "Website page"
    identity_fields = CompanyRevisionModel.identity_fields | frozenset({"canonical_url"})
    review_metadata_fields = CompanyRevisionModel.review_metadata_fields | frozenset(
        {"last_verified_at"}
    )
    business_fields = frozenset(
        {
            "page_type",
            "language",
            "title",
            "content_summary",
            "primary_cta_label",
            "primary_cta_url",
            "seo_keywords",
            "content_hash",
            "source_type",
            "is_demo",
        }
    )

    class Meta:
        ordering = ["organization_id", "canonical_url", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "canonical_url", "version"],
                name="knowledge_unique_website_page_version",
            ),
            models.UniqueConstraint(
                fields=["organization", "canonical_url"],
                condition=models.Q(status="VERIFIED"),
                name="knowledge_one_verified_website_page",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="knowledge_website_page_version_positive",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.canonical_url = normalize_https_url(self.canonical_url)
        if self.page_type not in self.PageType.values:
            raise ValidationError({"page_type": "Unsupported page type."})
        if self.source_type not in self.SourceType.values:
            raise ValidationError({"source_type": "Unsupported source type."})
        self.primary_cta_url = normalize_optional_cta_url(self.primary_cta_url)
        self.language = self.language.strip().lower()
        self.title = self.title.strip()
        if not self.language:
            raise ValidationError({"language": "Page language must not be blank."})
        if not self.title:
            raise ValidationError({"title": "Page title must not be blank."})
        if self.version < 1:
            raise ValidationError({"version": "Website page version must be positive."})
        validate_context_string_list(self.seo_keywords)
        if self.content_hash and not LOWER_SHA256_PATTERN.fullmatch(self.content_hash):
            raise ValidationError({"content_hash": "Content hash must be a lowercase SHA-256 value."})
        if self.supersedes_id:
            previous = self.supersedes
            if (
                previous.organization_id != self.organization_id
                or previous.canonical_url != self.canonical_url
            ):
                raise ValidationError(
                    {"supersedes": "Superseded page must belong to the same organization and URL."}
                )
            if self.version <= previous.version:
                raise ValidationError({"version": "A website page revision version must increase."})


_link_bulk_update: ContextVar[bool] = ContextVar("knowledge_context_link_bulk_update", default=False)


@contextmanager
def _validated_link_bulk_update() -> Iterator[None]:
    token = _link_bulk_update.set(True)
    try:
        yield
    finally:
        _link_bulk_update.reset(token)


class DraftRevisionLinkQuerySet(models.QuerySet):
    @transaction.atomic
    def create(self, **kwargs):
        return super().create(**kwargs)

    @transaction.atomic
    def bulk_create(self, objs, **kwargs):
        rows = list(objs)
        self.model._validate_link_rows(rows, original_parent_ids={})
        return super().bulk_create(rows, **kwargs)

    @transaction.atomic
    def update(self, **kwargs):
        if _link_bulk_update.get():
            return super().update(**kwargs)
        for value in kwargs.values():
            if isinstance(value, BaseExpression):
                raise ValidationError("Expression updates are not supported for context links.")
        rows = list(self)
        original_parent_ids = {
            row.pk: getattr(row, self.model.parent_id_field) for row in rows
        }
        for row in rows:
            for field, value in kwargs.items():
                setattr(row, field, value)
        self.model._validate_link_rows(rows, original_parent_ids=original_parent_ids)
        return super().update(**kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        rows = list(objs)
        original_parent_ids = dict(
            self.model.objects.filter(pk__in=[row.pk for row in rows]).values_list(
                "pk", self.model.parent_id_field
            )
        )
        self.model._validate_link_rows(rows, original_parent_ids=original_parent_ids)
        with _validated_link_bulk_update():
            return super().bulk_update(rows, fields, **kwargs)

    @transaction.atomic
    def delete(self):
        rows = list(self)
        original_parent_ids = {
            row.pk: getattr(row, self.model.parent_id_field) for row in rows
        }
        self.model._require_draft_parents(rows, original_parent_ids=original_parent_ids)
        return super().delete()


class DraftRevisionLinkManager(models.Manager.from_queryset(DraftRevisionLinkQuerySet)):
    pass


class DraftRevisionLinkModel(models.Model):
    objects = DraftRevisionLinkManager()
    parent_field: str
    parent_id_field: str
    parent_model_name: str

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    @classmethod
    def _lock_objects(cls, model_name: str, ids, fields: tuple[str, ...]):
        model = apps.get_model(*model_name.split("."))
        ordered_ids = sorted({object_id for object_id in ids if object_id is not None}, key=str)
        objects = list(
            model.objects.select_for_update()
            .filter(pk__in=ordered_ids)
            .only("id", *fields)
            .order_by("id")
        )
        if len(objects) != len(ordered_ids):
            raise ValidationError("A linked object does not exist.")
        return {item.pk: item for item in objects}

    @classmethod
    def _require_draft_parents(cls, rows, *, original_parent_ids):
        parent_ids = {getattr(row, cls.parent_id_field) for row in rows}
        parent_ids.update(original_parent_ids.values())
        parents = cls._lock_objects(
            cls.parent_model_name,
            parent_ids,
            ("organization_id", "status"),
        )
        if any(parent.status != "DRAFT" for parent in parents.values()):
            raise ValidationError("Revision links may be changed only while the parent is DRAFT.")
        return parents

    @classmethod
    def _validate_link_rows(cls, rows, *, original_parent_ids):
        parents = cls._require_draft_parents(rows, original_parent_ids=original_parent_ids)
        cls._validate_targets(rows, parents=parents)

    @classmethod
    def _validate_targets(cls, rows, *, parents) -> None:
        raise NotImplementedError

    @transaction.atomic
    def save(self, *args, **kwargs):
        original_parent_ids = {}
        if not self._state.adding:
            original_parent_ids[self.pk] = type(self).objects.values_list(
                self.parent_id_field, flat=True
            ).get(pk=self.pk)
        type(self)._validate_link_rows([self], original_parent_ids=original_parent_ids)
        return super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        current_parent_id = (
            type(self)
            .objects.values_list(self.parent_id_field, flat=True)
            .get(pk=self.pk)
        )
        type(self)._require_draft_parents(
            [self],
            original_parent_ids={self.pk: current_parent_id},
        )
        return super().delete(*args, **kwargs)


class ProductLinkedRevisionModel(DraftRevisionLinkModel):
    class Meta:
        abstract = True

    @classmethod
    def _validate_targets(cls, rows, *, parents) -> None:
        product_ids = {row.product_id for row in rows}
        products = cls._lock_objects(
            "catalog.Product",
            product_ids,
            ("organization_id", "status"),
        )
        for row in rows:
            parent = parents[getattr(row, cls.parent_id_field)]
            product = products[row.product_id]
            if product.organization_id != parent.organization_id:
                raise ValidationError("Parent and Product must belong to the same organization.")
            if product.status == "ARCHIVED":
                raise ValidationError("Archived products cannot be linked.")
            row.product = product
            row._validate_product_link_fields()


class ICPProductLink(ProductLinkedRevisionModel):
    class Role(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        SECONDARY = "SECONDARY", "Secondary"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    icp_profile = models.ForeignKey(
        ICPProfile,
        on_delete=models.CASCADE,
        related_name="product_links",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="icp_links",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    priority = models.PositiveIntegerField(default=1)
    use_cases = models.JSONField(default=list, validators=[validate_context_string_list])
    created_at = models.DateTimeField(auto_now_add=True)

    parent_field = "icp_profile"
    parent_id_field = "icp_profile_id"
    parent_model_name = "knowledge.ICPProfile"

    class Meta:
        ordering = ["icp_profile_id", "priority", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["icp_profile", "product"],
                name="knowledge_unique_icp_product_link",
            ),
            models.CheckConstraint(
                condition=models.Q(priority__gt=0),
                name="knowledge_icp_product_priority_positive",
            ),
        ]

    def _validate_product_link_fields(self) -> None:
        if self.role not in self.Role.values:
            raise ValidationError({"role": "Unsupported ICP product role."})
        if not self.priority or self.priority < 1:
            raise ValidationError({"priority": "Priority must be positive."})
        validate_context_string_list(self.use_cases)


class WebsitePageProductLink(ProductLinkedRevisionModel):
    class RelationType(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        RELATED = "RELATED", "Related"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    website_page = models.ForeignKey(
        WebsitePage,
        on_delete=models.CASCADE,
        related_name="product_links",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="website_page_links",
    )
    relation_type = models.CharField(max_length=16, choices=RelationType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    parent_field = "website_page"
    parent_id_field = "website_page_id"
    parent_model_name = "knowledge.WebsitePage"

    class Meta:
        ordering = ["website_page_id", "relation_type", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["website_page", "product"],
                name="knowledge_unique_page_product_link",
            )
        ]

    def _validate_product_link_fields(self) -> None:
        if self.relation_type not in self.RelationType.values:
            raise ValidationError({"relation_type": "Unsupported page product relation type."})


class WebsitePageConceptLink(DraftRevisionLinkModel):
    class Role(models.TextChoices):
        INDUSTRY = "INDUSTRY", "Industry"
        APPLICATION = "APPLICATION", "Application"
        PURCHASE_INTENT = "PURCHASE_INTENT", "Purchase intent"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    website_page = models.ForeignKey(
        WebsitePage,
        on_delete=models.CASCADE,
        related_name="concept_links",
    )
    concept = models.ForeignKey(
        "knowledge.KnowledgeConcept",
        on_delete=models.PROTECT,
        related_name="website_page_links",
    )
    role = models.CharField(max_length=24, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    parent_field = "website_page"
    parent_id_field = "website_page_id"
    parent_model_name = "knowledge.WebsitePage"

    class Meta:
        ordering = ["website_page_id", "role", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["website_page", "role", "concept"],
                name="knowledge_unique_page_concept_link",
            )
        ]

    @classmethod
    def _validate_targets(cls, rows, *, parents) -> None:
        concept_ids = {row.concept_id for row in rows}
        concepts = cls._lock_objects(
            "knowledge.KnowledgeConcept",
            concept_ids,
            ("organization_id", "status", "concept_type"),
        )
        concept_model = apps.get_model("knowledge", "KnowledgeConcept")
        compatible_types = {
            cls.Role.INDUSTRY: concept_model.ConceptType.INDUSTRY,
            cls.Role.APPLICATION: concept_model.ConceptType.APPLICATION,
            cls.Role.PURCHASE_INTENT: concept_model.ConceptType.PURCHASE_INTENT,
        }
        for row in rows:
            parent = parents[row.website_page_id]
            concept = concepts[row.concept_id]
            if concept.status != "APPROVED":
                raise ValidationError("Website page concepts must be APPROVED.")
            if concept.organization_id not in {None, parent.organization_id}:
                raise ValidationError("Page and organization concept must belong to the same organization.")
            if compatible_types.get(row.role) != concept.concept_type:
                raise ValidationError("Concept role is not compatible with the concept type.")
            row.concept = concept
