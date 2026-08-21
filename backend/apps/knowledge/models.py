import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models.expressions import BaseExpression

from .guards import (
    CompanyRevisionModel,
    GraphAssociationModel,
    GuardedKnowledgeModel,
    _validated_company_fact_evidence_bulk_update,
    company_fact_evidence_bulk_update_active,
    company_write_override_active,
)
from .normalization import normalize_alias


class KnowledgeStatus(models.TextChoices):
    SUGGESTED = "SUGGESTED", "Suggested"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    DEPRECATED = "DEPRECATED", "Deprecated"


class KnowledgeGraphLock(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(max_length=32, unique=True, default="is_a_graph")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1), name="knowledge_single_is_a_graph_lock"
            )
        ]


class KnowledgeConcept(GuardedKnowledgeModel):
    affects_ontology_snapshot = True
    class Scope(models.TextChoices):
        SYSTEM = "SYSTEM", "System"
        ORGANIZATION = "ORGANIZATION", "Organization"

    class ConceptType(models.TextChoices):
        PRODUCT_TYPE = "PRODUCT_TYPE", "Product type"
        PARAMETER = "PARAMETER", "Parameter"
        MATERIAL = "MATERIAL", "Material"
        PROCESS = "PROCESS", "Process"
        STANDARD = "STANDARD", "Standard"
        APPLICATION = "APPLICATION", "Application"
        INDUSTRY = "INDUSTRY", "Industry"
        CUSTOMER_TYPE = "CUSTOMER_TYPE", "Customer type"
        PURCHASE_INTENT = "PURCHASE_INTENT", "Purchase intent"

    Status = KnowledgeStatus

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=16, choices=Scope.choices)
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.PROTECT, null=True, blank=True, related_name="knowledge_concepts"
    )
    concept_type = models.CharField(max_length=32, choices=ConceptType.choices)
    code = models.CharField(max_length=96)
    label_zh = models.CharField(max_length=255)
    label_en = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=KnowledgeStatus.choices, default=KnowledgeStatus.SUGGESTED)
    version = models.PositiveIntegerField(default=1)
    suggested_by_ai_run_id = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="created_knowledge_concepts"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_knowledge_concepts"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    evidence = models.ManyToManyField(
        "KnowledgeEvidence",
        blank=True,
        related_name="concepts",
        through="KnowledgeConceptEvidence",
        through_fields=("knowledgeconcept", "knowledgeevidence"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["code", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(scope="SYSTEM", organization__isnull=True)
                    | models.Q(scope="ORGANIZATION", organization__isnull=False)
                ),
                name="knowledge_concept_scope_organization",
            ),
            models.UniqueConstraint(
                fields=["concept_type", "code"],
                condition=models.Q(scope="SYSTEM"),
                name="knowledge_unique_system_concept_code",
            ),
            models.UniqueConstraint(
                fields=["organization", "concept_type", "code"],
                condition=models.Q(scope="ORGANIZATION"),
                name="knowledge_unique_org_concept_code",
            ),
        ]

    identity_fields = frozenset({"scope", "organization_id"})
    system_seed_update_fields = GuardedKnowledgeModel.system_seed_update_fields | frozenset(
        {"label_zh", "label_en", "description"}
    )

    def clean(self) -> None:
        super().clean()
        if self.scope == self.Scope.SYSTEM and self.organization_id is not None:
            raise ValidationError({"organization": "SYSTEM concepts cannot have an organization."})
        if self.scope == self.Scope.ORGANIZATION and self.organization_id is None:
            raise ValidationError({"organization": "ORGANIZATION concepts require an organization."})

    def _knowledge_reference_objects(self) -> list[object]:
        return [
            *self.aliases.all(),
            *self.outgoing_relations.all(),
            *self.incoming_relations.all(),
            *self.evidence.all(),
        ]


class KnowledgeEvidence(GuardedKnowledgeModel):
    affects_ontology_snapshot = True
    class EvidenceType(models.TextChoices):
        PRODUCT_DOCUMENT = "PRODUCT_DOCUMENT", "Product document"
        PUBLIC_SOURCE = "PUBLIC_SOURCE", "Public source"
        HUMAN_ENTRY = "HUMAN_ENTRY", "Human entry"
        STANDARD_REFERENCE = "STANDARD_REFERENCE", "Standard reference"

    class UsageRights(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Unknown"
        INTERNAL_ONLY = "INTERNAL_ONLY", "Internal only"
        PUBLIC = "PUBLIC", "Public use allowed"

    class Sensitivity(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        CONFIDENTIAL = "CONFIDENTIAL", "Confidential"
        SECRET = "SECRET", "Secret"

    Status = KnowledgeStatus

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.PROTECT, null=True, blank=True, related_name="knowledge_evidence"
    )
    evidence_type = models.CharField(max_length=32, choices=EvidenceType.choices)
    source_object_type = models.CharField(max_length=128, blank=True)
    source_object_id = models.UUIDField(null=True, blank=True)
    source_url = models.URLField(max_length=2048, null=True, blank=True)
    excerpt = models.TextField(blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    usage_rights = models.CharField(
        max_length=24,
        choices=UsageRights.choices,
        default=UsageRights.UNKNOWN,
    )
    sensitivity = models.CharField(
        max_length=16,
        choices=Sensitivity.choices,
        default=Sensitivity.NORMAL,
    )
    is_demo = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=KnowledgeStatus.choices, default=KnowledgeStatus.SUGGESTED)
    version = models.PositiveIntegerField(default=1)
    suggested_by_ai_run_id = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="created_knowledge_evidence"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_knowledge_evidence"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["created_at", "id"]

    immutable_fields = frozenset(
        {
            "organization_id",
            "evidence_type",
            "source_object_type",
            "source_object_id",
            "source_url",
            "excerpt",
            "captured_at",
            "content_hash",
            "usage_rights",
            "sensitivity",
            "is_demo",
            "expires_at",
            "created_by_id",
        }
    )

    def _knowledge_reference_objects(self) -> list[object]:
        return [*self.concepts.all(), *self.relations.all(), *self.company_fact_bindings.all()]


class CompanyKnowledgeProfile(CompanyRevisionModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        IN_REVIEW = "IN_REVIEW", "In review"
        APPROVED = "APPROVED", "Approved"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="company_knowledge_profiles",
    )
    version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successor_profiles",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    brand_name = models.CharField(max_length=255)
    legal_name_zh = models.CharField(max_length=255, blank=True)
    legal_name_en = models.CharField(max_length=255, blank=True)
    brand_aliases = models.JSONField(default=list, blank=True)
    internal_summary = models.TextField(blank=True)
    default_language = models.CharField(max_length=16, default="en")
    supported_languages = models.JSONField(default=list, blank=True)
    primary_site_origin = models.URLField(max_length=2048, blank=True)
    disclosure_rules = models.JSONField(default=dict, blank=True)
    prohibited_claims = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_company_knowledge_profiles",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_company_knowledge_profiles",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    frozen_statuses = frozenset({Status.IN_REVIEW, Status.APPROVED, Status.SUPERSEDED})
    frozen_label = "approved profile"
    business_fields = frozenset(
        {
            "brand_name",
            "legal_name_zh",
            "legal_name_en",
            "brand_aliases",
            "internal_summary",
            "default_language",
            "supported_languages",
            "primary_site_origin",
            "disclosure_rules",
            "prohibited_claims",
        }
    )

    class Meta:
        ordering = ["organization_id", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "version"],
                name="knowledge_unique_company_profile_version",
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(status="APPROVED"),
                name="knowledge_one_approved_company_profile",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.supersedes_id:
            if self.supersedes.organization_id != self.organization_id:
                raise ValidationError({"supersedes": "Superseded profile must belong to the same organization."})
            if self.version <= self.supersedes.version:
                raise ValidationError({"version": "A profile revision version must increase."})
        if not isinstance(self.brand_aliases, list) or not all(
            isinstance(item, str) for item in self.brand_aliases
        ):
            raise ValidationError({"brand_aliases": "Brand aliases must be a list of strings."})
        if not isinstance(self.supported_languages, list) or not all(
            isinstance(item, str) for item in self.supported_languages
        ):
            raise ValidationError({"supported_languages": "Supported languages must be a list of strings."})
        if not isinstance(self.disclosure_rules, dict):
            raise ValidationError({"disclosure_rules": "Disclosure rules must be an object."})
        if not isinstance(self.prohibited_claims, list) or not all(
            isinstance(item, str) for item in self.prohibited_claims
        ):
            raise ValidationError({"prohibited_claims": "Prohibited claims must be a list of strings."})


class CompanyFact(CompanyRevisionModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        IN_REVIEW = "IN_REVIEW", "In review"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC", "Public"
        INTERNAL = "INTERNAL", "Internal"
        RESTRICTED = "RESTRICTED", "Restricted"

    class Sensitivity(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        CONFIDENTIAL = "CONFIDENTIAL", "Confidential"
        SECRET = "SECRET", "Secret"

    class ClaimPolicy(models.TextChoices):
        ALLOW_WITH_EVIDENCE = "ALLOW_WITH_EVIDENCE", "Allow with evidence"
        INTERNAL_CONTEXT_ONLY = "INTERNAL_CONTEXT_ONLY", "Internal context only"
        NEVER_SEND_TO_MODEL = "NEVER_SEND_TO_MODEL", "Never send to model"

    class RiskLevel(models.TextChoices):
        STANDARD = "STANDARD", "Standard"
        HIGH = "HIGH", "High"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="company_facts",
    )
    profile = models.ForeignKey(
        CompanyKnowledgeProfile,
        on_delete=models.PROTECT,
        related_name="facts",
    )
    namespace = models.CharField(max_length=96)
    key = models.CharField(max_length=160)
    value_json = models.JSONField()
    fact_type = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.INTERNAL)
    sensitivity = models.CharField(max_length=16, choices=Sensitivity.choices, default=Sensitivity.NORMAL)
    claim_policy = models.CharField(
        max_length=32,
        choices=ClaimPolicy.choices,
        default=ClaimPolicy.INTERNAL_CONTEXT_ONLY,
    )
    risk_level = models.CharField(max_length=16, choices=RiskLevel.choices, default=RiskLevel.STANDARD)
    version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successor_facts",
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    is_demo = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_company_facts",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_company_facts",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    evidence = models.ManyToManyField(
        KnowledgeEvidence,
        through="CompanyFactEvidence",
        related_name="company_facts",
        blank=True,
    )

    frozen_statuses = frozenset(
        {Status.IN_REVIEW, Status.VERIFIED, Status.REJECTED, Status.SUPERSEDED}
    )
    frozen_label = "verified fact"
    identity_fields = CompanyRevisionModel.identity_fields | frozenset({"profile_id", "namespace", "key"})
    business_fields = frozenset(
        {
            "value_json",
            "fact_type",
            "visibility",
            "sensitivity",
            "claim_policy",
            "risk_level",
            "valid_from",
            "valid_until",
            "is_demo",
        }
    )

    class Meta:
        ordering = ["profile_id", "namespace", "key", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "namespace", "key", "version"],
                name="knowledge_unique_company_fact_version",
            ),
            models.UniqueConstraint(
                fields=["profile", "namespace", "key"],
                condition=models.Q(status="VERIFIED"),
                name="knowledge_one_verified_company_fact",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_until__isnull=True)
                | models.Q(valid_from__isnull=True)
                | models.Q(valid_until__gte=models.F("valid_from")),
                name="knowledge_company_fact_valid_dates",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.profile_id and self.profile.organization_id != self.organization_id:
            raise ValidationError({"organization": "Fact and profile must belong to the same organization."})
        if self.supersedes_id:
            previous = self.supersedes
            if previous.organization_id != self.organization_id or previous.profile_id != self.profile_id:
                raise ValidationError({"supersedes": "Superseded fact must belong to the same profile and organization."})
            if (previous.namespace, previous.key) != (self.namespace, self.key):
                raise ValidationError({"supersedes": "A fact revision must preserve namespace and key."})
            if self.version <= previous.version:
                raise ValidationError({"version": "A fact revision version must increase."})
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "valid_until cannot be earlier than valid_from."})
        self.namespace = self.namespace.strip()
        self.key = self.key.strip()
        if not self.namespace or not self.key:
            raise ValidationError("Company facts require a namespace and key.")


def _company_fact_id(value) -> uuid.UUID:
    return value.pk if isinstance(value, CompanyFact) else value


def _lock_company_facts(fact_ids) -> dict[uuid.UUID, CompanyFact]:
    ordered_ids = sorted({fact_id for fact_id in fact_ids if fact_id is not None}, key=str)
    locked_facts = list(
        CompanyFact.objects.select_for_update()
        .filter(pk__in=ordered_ids)
        .only("id", "status", "organization_id", "profile_id")
        .order_by("id")
    )
    if len(locked_facts) != len(ordered_ids):
        raise ValidationError("Every evidence binding requires an existing company fact.")
    return {fact.pk: fact for fact in locked_facts}


class CompanyFactEvidenceQuerySet(models.QuerySet):
    @transaction.atomic
    def create(self, **kwargs):
        return super().create(**kwargs)

    @transaction.atomic
    def bulk_create(self, objs, **kwargs):
        objects = list(objs)
        locked_facts = _lock_company_facts(instance.company_fact_id for instance in objects)
        for instance in objects:
            instance._validate_binding_write(
                locked_facts=locked_facts,
                original_fact_id=None,
            )
        return super().bulk_create(objects, **kwargs)

    @transaction.atomic
    def update(self, **kwargs):
        if company_fact_evidence_bulk_update_active():
            return super().update(**kwargs)
        for value in kwargs.values():
            if isinstance(value, BaseExpression):
                raise ValidationError("Expression updates are not supported for fact evidence bindings.")
        objects = list(self)
        original_fact_ids = {instance.pk: instance.company_fact_id for instance in objects}
        fact_ids = set(original_fact_ids.values())
        if "company_fact" in kwargs:
            fact_ids.add(_company_fact_id(kwargs["company_fact"]))
        if "company_fact_id" in kwargs:
            fact_ids.add(_company_fact_id(kwargs["company_fact_id"]))
        locked_facts = _lock_company_facts(fact_ids)
        for instance in objects:
            for field, value in kwargs.items():
                setattr(instance, field, value)
            instance._validate_binding_write(
                locked_facts=locked_facts,
                original_fact_id=original_fact_ids[instance.pk],
            )
        return super().update(**kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        objects = list(objs)
        original_fact_ids = dict(
            self.model.objects.filter(pk__in=[instance.pk for instance in objects]).values_list(
                "pk", "company_fact_id"
            )
        )
        fact_ids = set(original_fact_ids.values())
        fact_ids.update(instance.company_fact_id for instance in objects)
        locked_facts = _lock_company_facts(fact_ids)
        for instance in objects:
            instance._validate_binding_write(
                locked_facts=locked_facts,
                original_fact_id=original_fact_ids.get(instance.pk),
            )
        with _validated_company_fact_evidence_bulk_update():
            return super().bulk_update(objects, fields, **kwargs)

    @transaction.atomic
    def delete(self):
        fact_ids = set(self.values_list("company_fact_id", flat=True))
        locked_facts = _lock_company_facts(fact_ids)
        if not company_write_override_active() and any(
            fact.status == CompanyFact.Status.VERIFIED for fact in locked_facts.values()
        ):
            raise ValidationError("Evidence bindings for verified facts are immutable.")
        return super().delete()


class CompanyFactEvidence(models.Model):
    class SupportType(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        SUPPORTING = "SUPPORTING", "Supporting"
        CONTRADICTING = "CONTRADICTING", "Contradicting"

    objects = models.Manager.from_queryset(CompanyFactEvidenceQuerySet)()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_fact = models.ForeignKey(
        CompanyFact,
        on_delete=models.CASCADE,
        related_name="evidence_bindings",
    )
    evidence = models.ForeignKey(
        KnowledgeEvidence,
        on_delete=models.PROTECT,
        related_name="company_fact_bindings",
    )
    support_type = models.CharField(max_length=16, choices=SupportType.choices)
    citation_label = models.CharField(max_length=255, blank=True)
    bound_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bound_company_fact_evidence",
    )
    bound_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["company_fact_id", "support_type", "bound_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company_fact", "evidence", "support_type"],
                name="knowledge_unique_company_fact_evidence",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if not self.company_fact_id or not self.evidence_id:
            return
        fact = self.company_fact
        if fact.profile.organization_id != fact.organization_id:
            raise ValidationError("Fact and profile must belong to the same organization.")
        if self.evidence.organization_id != fact.organization_id:
            raise ValidationError("Fact, profile, and evidence must belong to the same organization.")

    def _validate_binding_scope(self, *, locked_fact: CompanyFact) -> None:
        profile_organization_id = CompanyKnowledgeProfile.objects.values_list(
            "organization_id", flat=True
        ).get(pk=locked_fact.profile_id)
        evidence_organization_id = KnowledgeEvidence.objects.values_list(
            "organization_id", flat=True
        ).get(pk=self.evidence_id)
        if profile_organization_id != locked_fact.organization_id:
            raise ValidationError("Fact and profile must belong to the same organization.")
        if evidence_organization_id != locked_fact.organization_id:
            raise ValidationError("Fact, profile, and evidence must belong to the same organization.")

    def _validate_binding_write(
        self,
        *,
        locked_facts: dict[uuid.UUID, CompanyFact],
        original_fact_id: uuid.UUID | None,
    ) -> None:
        locked_fact = locked_facts[self.company_fact_id]
        self._validate_binding_scope(locked_fact=locked_fact)
        if company_write_override_active():
            return
        involved_fact_ids = {self.company_fact_id, original_fact_id}
        if any(
            locked_facts[fact_id].status == CompanyFact.Status.VERIFIED
            for fact_id in involved_fact_ids
            if fact_id is not None
        ):
            raise ValidationError("Evidence bindings for verified facts are immutable.")

    @transaction.atomic
    def save(self, *args, **kwargs):
        original_fact_id = None
        if not self._state.adding:
            original_fact_id = type(self).objects.values_list("company_fact_id", flat=True).get(pk=self.pk)
        locked_facts = _lock_company_facts({self.company_fact_id, original_fact_id})
        self._validate_binding_write(
            locked_facts=locked_facts,
            original_fact_id=original_fact_id,
        )
        return super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        locked_fact = _lock_company_facts({self.company_fact_id})[self.company_fact_id]
        if not company_write_override_active() and locked_fact.status == CompanyFact.Status.VERIFIED:
            raise ValidationError("Evidence bindings for verified facts are immutable.")
        return super().delete(*args, **kwargs)


class KnowledgeAlias(GuardedKnowledgeModel):
    class AliasType(models.TextChoices):
        SYNONYM = "SYNONYM", "Synonym"
        ABBREVIATION = "ABBREVIATION", "Abbreviation"
        MARKET_TERM = "MARKET_TERM", "Market term"

    Status = KnowledgeStatus

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.PROTECT, null=True, blank=True, related_name="knowledge_aliases"
    )
    concept = models.ForeignKey(KnowledgeConcept, on_delete=models.PROTECT, related_name="aliases")
    language = models.CharField(max_length=16)
    alias = models.CharField(max_length=255)
    normalized_alias = models.CharField(max_length=255, editable=False)
    alias_type = models.CharField(max_length=16, choices=AliasType.choices, default=AliasType.SYNONYM)
    status = models.CharField(max_length=16, choices=KnowledgeStatus.choices, default=KnowledgeStatus.SUGGESTED)
    version = models.PositiveIntegerField(default=1)
    suggested_by_ai_run_id = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="created_knowledge_aliases"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_knowledge_aliases"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["normalized_alias", "concept__code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["language", "normalized_alias"],
                condition=models.Q(organization__isnull=True, status="APPROVED"),
                name="knowledge_unique_system_approved_alias",
            ),
            models.UniqueConstraint(
                fields=["organization", "language", "normalized_alias"],
                condition=models.Q(organization__isnull=False, status="APPROVED"),
                name="knowledge_unique_org_approved_alias",
            ),
        ]

    identity_fields = frozenset({"organization_id", "concept_id"})
    system_seed_update_fields = GuardedKnowledgeModel.system_seed_update_fields | frozenset(
        {"alias", "alias_type", "normalized_alias"}
    )

    @classmethod
    def _validate_queryset_update_fields(cls, fields: set[str]) -> None:
        super()._validate_queryset_update_fields(fields)
        if "normalized_alias" in fields:
            raise ValidationError("normalized_alias is derived and cannot be updated directly.")
        if {field.removesuffix("_id") for field in fields} & {"alias", "language"}:
            raise ValidationError("Unsafe alias or language queryset update; use model save or bulk_update.")

    @classmethod
    def _validate_system_seed_queryset_fields(cls, fields: set[str]) -> None:
        super()._validate_system_seed_queryset_fields(fields)
        if "normalized_alias" in fields:
            raise ValidationError("normalized_alias is derived and cannot be updated directly.")
        if {field.removesuffix("_id") for field in fields} & {"alias", "language"}:
            raise ValidationError("Unsafe alias or language queryset update; use model save or bulk_update.")

    @classmethod
    def _augment_bulk_update_fields(cls, fields: set[str]) -> list[str]:
        if fields & {"alias", "language"}:
            fields = fields | {"normalized_alias"}
        return super()._augment_bulk_update_fields(fields)

    def _augment_save_update_fields(self, fields: set[str]) -> set[str]:
        if fields & {"alias", "language"}:
            fields = fields | {"normalized_alias"}
        return super()._augment_save_update_fields(fields)

    def clean(self) -> None:
        super().clean()
        if not self.concept_id:
            return
        if self.organization_id is None and self.concept.organization_id is not None:
            raise ValidationError({"organization": "SYSTEM aliases require a SYSTEM concept."})
        if self.organization_id is not None and self.concept.organization_id not in {None, self.organization_id}:
            raise ValidationError({"organization": "Alias concept must be visible to the organization."})

    def _prepare_knowledge_write(self) -> None:
        self.language = self.language.strip().lower()
        self.normalized_alias = normalize_alias(self.alias, language=self.language)


class KnowledgeRelation(GuardedKnowledgeModel):
    affects_ontology_snapshot = True
    class Predicate(models.TextChoices):
        IS_A = "IS_A", "Is a"
        APPLIES_TO = "APPLIES_TO", "Applies to"
        USES_MATERIAL = "USES_MATERIAL", "Uses material"
        REQUIRES_PROCESS = "REQUIRES_PROCESS", "Requires process"
        COMPLIES_WITH = "COMPLIES_WITH", "Complies with"
        RELEVANT_TO_CUSTOMER_TYPE = "RELEVANT_TO_CUSTOMER_TYPE", "Relevant to customer type"
        INDICATES_PURCHASE_INTENT = "INDICATES_PURCHASE_INTENT", "Indicates purchase intent"
        REQUIRES_PARAMETER = "REQUIRES_PARAMETER", "Requires parameter"

    Status = KnowledgeStatus

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.PROTECT, null=True, blank=True, related_name="knowledge_relations"
    )
    subject_concept = models.ForeignKey(
        KnowledgeConcept, on_delete=models.PROTECT, related_name="outgoing_relations"
    )
    predicate = models.CharField(max_length=40, choices=Predicate.choices)
    object_concept = models.ForeignKey(
        KnowledgeConcept, on_delete=models.PROTECT, related_name="incoming_relations"
    )
    status = models.CharField(max_length=16, choices=KnowledgeStatus.choices, default=KnowledgeStatus.SUGGESTED)
    confidence = models.DecimalField(
        max_digits=5, decimal_places=4, default=1, validators=[MinValueValidator(0), MaxValueValidator(1)]
    )
    version = models.PositiveIntegerField(default=1)
    suggested_by_ai_run_id = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="created_knowledge_relations"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_knowledge_relations"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    evidence = models.ManyToManyField(
        KnowledgeEvidence,
        blank=True,
        related_name="relations",
        through="KnowledgeRelationEvidence",
        through_fields=("knowledgerelation", "knowledgeevidence"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["subject_concept__code", "predicate", "object_concept__code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["subject_concept", "predicate", "object_concept"],
                condition=models.Q(organization__isnull=True),
                name="knowledge_unique_system_relation",
            ),
            models.UniqueConstraint(
                fields=["organization", "subject_concept", "predicate", "object_concept"],
                condition=models.Q(organization__isnull=False),
                name="knowledge_unique_org_relation",
            ),
            models.CheckConstraint(
                condition=~models.Q(subject_concept=models.F("object_concept")),
                name="knowledge_relation_not_self",
            ),
        ]

    identity_fields = frozenset(
        {"organization_id", "subject_concept_id", "object_concept_id", "predicate"}
    )
    system_seed_update_fields = GuardedKnowledgeModel.system_seed_update_fields | frozenset(
        {"confidence"}
    )

    def _validate_bulk_create(self) -> None:
        if self.predicate == self.Predicate.IS_A:
            raise ValidationError("IS_A bulk creation is unsafe; create relations individually.")

    def _validate_domain_invariants(self) -> None:
        super()._validate_domain_invariants()
        from .relation_rules import validate_predicate_types

        validate_predicate_types(
            subject=self.subject_concept,
            predicate=self.predicate,
            object=self.object_concept,
        )
        if self.predicate == self.Predicate.IS_A:
            from .graph import reject_is_a_cycle

            reject_is_a_cycle(
                subject=self.subject_concept,
                object=self.object_concept,
                relation_organization_id=self.organization_id,
                exclude_relation_id=None if self._state.adding else self.id,
            )

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if not self.subject_concept_id or not self.object_concept_id:
            return
        concepts = (self.subject_concept, self.object_concept)
        if self.organization_id is None and any(item.organization_id is not None for item in concepts):
            raise ValidationError({"organization": "SYSTEM relations require SYSTEM concepts."})
        if self.organization_id is not None:
            for concept in concepts:
                if concept.organization_id not in {None, self.organization_id}:
                    raise ValidationError({"organization": "Relation concepts must be visible to the organization."})

    def _knowledge_reference_objects(self) -> list[object]:
        return list(self.evidence.all())


class KnowledgeConceptEvidence(GraphAssociationModel):
    knowledgeconcept = models.ForeignKey(KnowledgeConcept, on_delete=models.CASCADE)
    knowledgeevidence = models.ForeignKey(KnowledgeEvidence, on_delete=models.CASCADE)

    class Meta:
        db_table = "knowledge_knowledgeconcept_evidence"
        base_manager_name = "objects"
        default_manager_name = "objects"
        unique_together = (("knowledgeconcept", "knowledgeevidence"),)


class KnowledgeRelationEvidence(GraphAssociationModel):
    knowledgerelation = models.ForeignKey(KnowledgeRelation, on_delete=models.CASCADE)
    knowledgeevidence = models.ForeignKey(KnowledgeEvidence, on_delete=models.CASCADE)

    class Meta:
        db_table = "knowledge_knowledgerelation_evidence"
        base_manager_name = "objects"
        default_manager_name = "objects"
        unique_together = (("knowledgerelation", "knowledgeevidence"),)
