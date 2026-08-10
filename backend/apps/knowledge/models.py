import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction

from .guards import GraphAssociationModel, GuardedKnowledgeModel
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
        CAPABILITY = "CAPABILITY", "Capability"
        REQUIREMENT = "REQUIREMENT", "Requirement"

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
            "created_by_id",
        }
    )

    def _knowledge_reference_objects(self) -> list[object]:
        return [*self.concepts.all(), *self.relations.all()]


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
        SATISFIES = "SATISFIES", "Satisfies"
        HAS_REQUIREMENT = "HAS_REQUIREMENT", "Has requirement"

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
