import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .normalization import normalize_alias


class KnowledgeStatus(models.TextChoices):
    SUGGESTED = "SUGGESTED", "Suggested"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    DEPRECATED = "DEPRECATED", "Deprecated"


class KnowledgeConcept(models.Model):
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
    evidence = models.ManyToManyField("KnowledgeEvidence", blank=True, related_name="concepts")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
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

    def clean(self) -> None:
        super().clean()
        if self.scope == self.Scope.SYSTEM and self.organization_id is not None:
            raise ValidationError({"organization": "SYSTEM concepts cannot have an organization."})
        if self.scope == self.Scope.ORGANIZATION and self.organization_id is None:
            raise ValidationError({"organization": "ORGANIZATION concepts require an organization."})


class KnowledgeEvidence(models.Model):
    class EvidenceType(models.TextChoices):
        PRODUCT_DOCUMENT = "PRODUCT_DOCUMENT", "Product document"
        PUBLIC_SOURCE = "PUBLIC_SOURCE", "Public source"
        HUMAN_ENTRY = "HUMAN_ENTRY", "Human entry"
        STANDARD_REFERENCE = "STANDARD_REFERENCE", "Standard reference"

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
        ordering = ["created_at", "id"]

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            original = type(self).objects.get(pk=self.pk)
            immutable_fields = (
                "organization_id",
                "evidence_type",
                "source_object_type",
                "source_object_id",
                "source_url",
                "excerpt",
                "captured_at",
                "created_by_id",
            )
            if any(getattr(self, field) != getattr(original, field) for field in immutable_fields):
                raise ValidationError("Knowledge evidence source snapshots are immutable.")
        super().save(*args, **kwargs)


class KnowledgeAlias(models.Model):
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

    def clean(self) -> None:
        super().clean()
        if not self.concept_id:
            return
        if self.organization_id is None and self.concept.organization_id is not None:
            raise ValidationError({"organization": "SYSTEM aliases require a SYSTEM concept."})
        if self.organization_id is not None and self.concept.organization_id not in {None, self.organization_id}:
            raise ValidationError({"organization": "Alias concept must be visible to the organization."})

    def save(self, *args: object, **kwargs: object) -> None:
        self.language = self.language.strip().lower()
        self.normalized_alias = normalize_alias(self.alias, language=self.language)
        super().save(*args, **kwargs)


class KnowledgeRelation(models.Model):
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
    evidence = models.ManyToManyField(KnowledgeEvidence, blank=True, related_name="relations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
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
        if self._state.adding and self.suggested_by_ai_run_id and self.status != KnowledgeStatus.SUGGESTED:
            raise ValidationError({"status": "AI-originated relations must start as SUGGESTED."})
