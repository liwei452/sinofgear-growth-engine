import ipaddress
import re
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, router, transaction
from django.db.models.deletion import ProtectedError
from django.db.models.expressions import BaseExpression
from django.utils import timezone

from apps.common.models import OrganizationScopedModel

from .scoring import EvidenceGates, ScoreDimensions, score_lead


_lead_history_write: ContextVar[bool] = ContextVar("lead_history_write", default=False)
_lead_frozen_references: ContextVar[dict | None] = ContextVar(
    "lead_frozen_references", default=None
)
_lead_analysis_lease_write: ContextVar[bool] = ContextVar(
    "lead_analysis_lease_write", default=False
)

SPECIAL_USE_DOMAIN_SUFFIXES = frozenset(
    {
        "localhost",
        "local",
        "internal",
        "home.arpa",
        "onion",
        "test",
        "invalid",
        "lan",
        "home",
        "corp",
    }
)


class LeadVersionConflict(ValidationError):
    pass


@contextmanager
def lead_history_writes():
    token = _lead_history_write.set(True)
    try:
        yield
    finally:
        _lead_history_write.reset(token)


@contextmanager
def lead_frozen_reference_writes(*, organization_id, ontology_snapshot, capability_bindings):
    """Allow immutable insight links already approved in a verified frozen snapshot."""
    references = {
        "organization_id": str(organization_id),
        "concept_types": {
            str(row["concept_id"]): row["concept_type"]
            for row in ontology_snapshot.get("concept_versions", [])
            if isinstance(row, dict) and row.get("status") == "APPROVED"
        },
        "capability_evidence": {
            str(row["capability_concept_id"]): {
                str(item) for item in row.get("knowledge_evidence_ids", [])
            }
            for row in capability_bindings
            if isinstance(row, dict) and row.get("capability_concept_id")
        },
    }
    token = _lead_frozen_references.set(references)
    try:
        yield
    finally:
        _lead_frozen_references.reset(token)


@contextmanager
def lead_analysis_lease_writes():
    token = _lead_analysis_lease_write.set(True)
    try:
        yield
    finally:
        _lead_analysis_lease_write.reset(token)


def normalize_company_domain(value: str) -> str:
    if not isinstance(value, str) or not (value := value.strip()):
        return ""
    if any(ord(character) <= 32 for character in value):
        raise ValidationError("Company domain must not contain whitespace or control characters.")
    candidate = value if "://" in value else f"//{value}"
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as error:
        raise ValidationError("Company domain is invalid.") from error
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        raise ValidationError("Company domain URL must use HTTP or HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("Company domain must not contain credentials.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or port is not None:
        raise ValidationError("Company domain must not contain a path, port, query, or fragment.")
    hostname = parsed.hostname
    if not hostname or "%" in hostname:
        raise ValidationError("Company domain is invalid.")
    hostname = hostname.rstrip(".").lower()
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        try:
            hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise ValidationError("Company domain is invalid.") from error
        labels = hostname.split(".")
        if any(
            hostname == suffix or hostname.endswith(f".{suffix}")
            for suffix in SPECIAL_USE_DOMAIN_SUFFIXES
        ):
            raise ValidationError("Company domain must be public.")
        if labels and all(
            re.fullmatch(r"(?:0x[0-9a-f]+|0[0-7]+|[0-9]+)", label) is not None
            for label in labels
        ):
            raise ValidationError("Company domain must not use an encoded IP address.")
        if len(labels) < 2 or len(hostname) > 253 or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or re.fullmatch(r"[a-z0-9-]+", label) is None
            for label in labels
        ):
            raise ValidationError("Company domain is invalid.")
        return hostname
    raise ValidationError("Company domain must be a public DNS name, not an IP address.")


def _related_organization_error(instance, field_name: str, errors: dict[str, str]) -> None:
    related_id = getattr(instance, f"{field_name}_id", None)
    if not instance.organization_id or not related_id:
        return
    related = getattr(instance, field_name)
    persisted_organization_id = (
        type(related)._base_manager.filter(pk=related_id)
        .values_list("organization_id", flat=True)
        .first()
    )
    if persisted_organization_id != instance.organization_id:
        errors[field_name] = f"{field_name.replace('_', ' ').title()} must belong to the same organization."


class CandidateQuerySet(models.QuerySet):
    @transaction.atomic
    def update(self, **kwargs):
        rows = list(self.select_for_update().order_by("pk"))
        for row in rows:
            for field, value in kwargs.items():
                if isinstance(value, BaseExpression):
                    raise ValidationError(
                        f"Expression updates are not supported for lead field '{field}'."
                    )
                setattr(row, field, value)
            row.save(update_fields=[*kwargs, "updated_at"])
        return len(rows)

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Lead candidate bulk upserts are not supported.")
        rows = list(objs)
        for row in rows:
            row.full_clean(validate_unique=False, validate_constraints=False)
        return super().bulk_create(rows, **kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        names = [field.name if hasattr(field, "name") else str(field) for field in fields]
        rows = sorted(objs, key=lambda row: str(row.pk))
        for row in rows:
            row.save(update_fields=[*names, "updated_at"])
        return len(rows)


class CandidateManager(models.Manager.from_queryset(CandidateQuerySet)):
    pass


class ImmutableHistoryQuerySet(models.QuerySet):
    @staticmethod
    def _require_service_write():
        if not _lead_history_write.get():
            raise ValidationError("Lead history may be created only through LeadService.")

    def update(self, **kwargs):
        raise ValidationError("Lead history is immutable.")

    def bulk_create(self, objs, **kwargs):
        self._require_service_write()
        rows = list(objs)
        for row in rows:
            row.full_clean(validate_unique=False, validate_constraints=False)
        return super().bulk_create(rows, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Lead history is immutable.")

    def delete(self):
        protected = list(self)
        if protected:
            raise ProtectedError("Lead history cannot be deleted.", protected)
        return 0, {}


class ImmutableHistoryManager(models.Manager.from_queryset(ImmutableHistoryQuerySet)):
    pass


class ImmutableLeadHistory(OrganizationScopedModel):
    objects = ImmutableHistoryManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(self, *args, **kwargs):
        if not _lead_history_write.get():
            raise ValidationError("Lead history may be created only through LeadService.")
        if not self._state.adding:
            raise ValidationError("Lead history is immutable.")
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ProtectedError("Lead history cannot be deleted.", [self])


class LeadCandidate(OrganizationScopedModel):
    class Status(models.TextChoices):
        DISCOVERED = "DISCOVERED", "Discovered"
        ANALYZING = "ANALYZING", "Analyzing"
        ANALYZED = "ANALYZED", "Analyzed"
        REVIEWED = "REVIEWED", "Reviewed"
        READY_FOR_HANDOFF = "READY_FOR_HANDOFF", "Ready for handoff"
        HANDED_OFF = "HANDED_OFF", "Handed off"
        DISMISSED = "DISMISSED", "Dismissed"

    B1_TRANSITIONS = {
        Status.DISCOVERED: frozenset({Status.ANALYZING}),
        Status.ANALYZING: frozenset({Status.ANALYZED}),
        Status.ANALYZED: frozenset(
            {Status.ANALYZING, Status.REVIEWED, Status.DISMISSED}
        ),
        Status.REVIEWED: frozenset({Status.DISMISSED}),
        Status.DISMISSED: frozenset({Status.DISCOVERED}),
    }

    objects = CandidateManager()
    source_signal = models.ForeignKey(
        "sources.SourceSignal",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lead_candidates",
    )
    company_name = models.CharField(max_length=255, blank=True)
    company_domain = models.CharField(max_length=253, blank=True)
    country_hint = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DISCOVERED)
    latest_insight = models.ForeignKey(
        "LeadInsight",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="latest_for_candidates",
    )
    analysis_lease_token = models.UUIDField(null=True, blank=True, editable=False)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_lead_candidates",
    )
    evidence = models.ManyToManyField(
        "sources.SourceEvidence",
        through="LeadCandidateEvidence",
        through_fields=("candidate", "evidence"),
        related_name="lead_candidates",
    )

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(version__gte=1), name="leads_candidate_version_positive"),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="ANALYZING",
                        analysis_lease_token__isnull=False,
                    )
                    | (
                        ~models.Q(status="ANALYZING")
                        & models.Q(analysis_lease_token__isnull=True)
                    )
                ),
                name="leads_candidate_lease_status_valid",
            ),
        ]

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}
        if self.company_domain:
            try:
                self.company_domain = normalize_company_domain(self.company_domain)
            except ValidationError as error:
                errors["company_domain"] = " ".join(error.messages)
        _related_organization_error(self, "source_signal", errors)
        if self._state.adding:
            if (
                self.analysis_lease_token is not None
                and not _lead_analysis_lease_write.get()
            ):
                errors["analysis_lease_token"] = (
                    "Analysis lease is managed only by LeadService."
                )
            if self.status != self.Status.DISCOVERED:
                errors["status"] = "Lead candidates must be created as DISCOVERED."
        if (self.status == self.Status.ANALYZING) != (
            self.analysis_lease_token is not None
        ):
            errors.setdefault("analysis_lease_token", (
                "ANALYZING status and an analysis lease must exist together."
            ))
        if self.latest_insight_id:
            _related_organization_error(self, "latest_insight", errors)
            latest_values = LeadInsight._base_manager.filter(pk=self.latest_insight_id).values(
                "candidate_id", "version"
            ).first()
            if latest_values is None or latest_values["candidate_id"] != self.pk:
                errors["latest_insight"] = "Latest insight must belong to this candidate."
        if not self._state.adding and self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                "organization_id",
                "status",
                "version",
                "latest_insight_id",
                "analysis_lease_token",
            ).first()
            if persisted is not None:
                if self.organization_id != persisted["organization_id"]:
                    errors["organization"] = "Organization is immutable after creation."
                recovery_transition = (
                    _lead_analysis_lease_write.get()
                    and persisted["status"] == self.Status.ANALYZING
                    and self.status == self.Status.DISCOVERED
                )
                if (
                    self.status != persisted["status"]
                    and self.status
                    not in self.B1_TRANSITIONS.get(persisted["status"], frozenset())
                    and not recovery_transition
                ):
                    errors["status"] = (
                        f"B1 cannot transition from {persisted['status']} to {self.status}."
                    )
                if (
                    self.analysis_lease_token != persisted["analysis_lease_token"]
                    and not _lead_analysis_lease_write.get()
                ):
                    errors["analysis_lease_token"] = (
                        "Analysis lease is managed only by LeadService."
                    )
                if self.version != persisted["version"]:
                    errors["version"] = "Candidate version is managed automatically."
                greatest_insight_id = LeadInsight._base_manager.filter(
                    candidate_id=self.pk
                ).order_by("-version", "-id").values_list("id", flat=True).first()
                if greatest_insight_id is not None and self.latest_insight_id != greatest_insight_id:
                    errors["latest_insight"] = (
                        "Latest insight must remain the greatest candidate-local version."
                    )
        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def save(self, *args, **kwargs):
        adding = self._state.adding
        self.full_clean(validate_unique=False, validate_constraints=False)
        if adding:
            return super().save(*args, **kwargs)
        if kwargs.get("force_insert"):
            raise ValueError("Cannot force insert an existing lead candidate.")

        expected_version = self.version
        next_version = expected_version + 1
        updated_at = timezone.now()
        requested_fields = kwargs.get("update_fields")
        if requested_fields is None:
            selected = {
                field.name
                for field in self._meta.concrete_fields
                if not field.primary_key and field.name != "created_at"
            }
        else:
            selected = {
                field_name.removesuffix("_id") for field_name in requested_fields
            } | {"version", "updated_at"}

        self.version = next_version
        self.updated_at = updated_at
        values = {
            field.attname: getattr(self, field.attname)
            for field in self._meta.concrete_fields
            if not field.primary_key
            and field.name != "created_at"
            and field.name in selected
        }
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        queryset = type(self)._base_manager.using(database).filter(
            pk=self.pk, version=expected_version
        )
        if models.QuerySet.update(queryset, **values) != 1:
            self.version = expected_version
            raise LeadVersionConflict("Lead candidate version changed before persistence.")
        self._state.db = database
        self._state.adding = False
        return None


class LeadInsight(ImmutableLeadHistory):
    class ScoreBand(models.TextChoices):
        HIGH = "HIGH", "High"
        WATCH = "WATCH", "Watch"
        OBSERVE = "OBSERVE", "Observe"
        LOW = "LOW", "Low"

    candidate = models.ForeignKey(LeadCandidate, on_delete=models.PROTECT, related_name="insights")
    ai_run = models.ForeignKey("ai.AIRun", on_delete=models.PROTECT, related_name="lead_insights")
    version = models.PositiveIntegerField()
    intent_score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(30)])
    company_fit_score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(25)])
    specificity_score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(20)])
    capability_fit_score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(15)])
    recency_score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(10)])
    score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(100)])
    score_band = models.CharField(max_length=16, choices=ScoreBand.choices)
    high_value_eligible = models.BooleanField(default=False)
    traceable_source = models.BooleanField(default=False)
    explicit_need_or_company_match = models.BooleanField(default=False)
    capability_evidence = models.BooleanField(default=False)
    audited_run = models.BooleanField(default=False)
    ontology_snapshot_complete = models.BooleanField(default=False)
    explanation = models.JSONField(default=dict)
    extracted_requirement_values = models.JSONField(default=list)
    evidence_confidence = models.DecimalField(
        max_digits=5, decimal_places=4, validators=[MinValueValidator(0), MaxValueValidator(1)]
    )
    company_match_confidence = models.DecimalField(
        max_digits=5, decimal_places=4, validators=[MinValueValidator(0), MaxValueValidator(1)]
    )
    ai_confidence = models.DecimalField(
        max_digits=5, decimal_places=4, validators=[MinValueValidator(0), MaxValueValidator(1)]
    )
    ontology_snapshot = models.JSONField()
    evidence = models.ManyToManyField(
        "sources.SourceEvidence",
        through="LeadCandidateEvidence",
        through_fields=("insight", "evidence"),
        related_name="lead_insights",
    )

    class Meta(ImmutableLeadHistory.Meta):
        ordering = ["candidate_id", "version", "id"]
        constraints = [
            models.UniqueConstraint(fields=["candidate", "version"], name="leads_unique_insight_version"),
            models.UniqueConstraint(fields=["ai_run"], name="leads_unique_insight_ai_run"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="leads_insight_version_positive"),
            models.CheckConstraint(
                condition=models.Q(
                    intent_score__gte=0,
                    intent_score__lte=30,
                    company_fit_score__gte=0,
                    company_fit_score__lte=25,
                    specificity_score__gte=0,
                    specificity_score__lte=20,
                    capability_fit_score__gte=0,
                    capability_fit_score__lte=15,
                    recency_score__gte=0,
                    recency_score__lte=10,
                    score__gte=0,
                    score__lte=100,
                ),
                name="leads_insight_scores_bounded",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    score=(
                        models.F("intent_score")
                        + models.F("company_fit_score")
                        + models.F("specificity_score")
                        + models.F("capability_fit_score")
                        + models.F("recency_score")
                    )
                ),
                name="leads_insight_score_sum",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(score__gte=80, score_band="HIGH")
                    | models.Q(score__gte=60, score__lt=80, score_band="WATCH")
                    | models.Q(score__gte=40, score__lt=60, score_band="OBSERVE")
                    | models.Q(score__lt=40, score_band="LOW")
                ),
                name="leads_insight_band_matches_score",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        high_value_eligible=True,
                        score_band="HIGH",
                        traceable_source=True,
                        explicit_need_or_company_match=True,
                        capability_evidence=True,
                        audited_run=True,
                        ontology_snapshot_complete=True,
                    )
                    | models.Q(
                        high_value_eligible=False,
                    )
                    & ~models.Q(
                        score_band="HIGH",
                        traceable_source=True,
                        explicit_need_or_company_match=True,
                        capability_evidence=True,
                        audited_run=True,
                        ontology_snapshot_complete=True,
                    )
                ),
                name="leads_insight_high_value_gated",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    evidence_confidence__gte=0,
                    evidence_confidence__lte=1,
                    company_match_confidence__gte=0,
                    company_match_confidence__lte=1,
                    ai_confidence__gte=0,
                    ai_confidence__lte=1,
                ),
                name="leads_insight_confidence_bounded",
            ),
        ]

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}
        _related_organization_error(self, "candidate", errors)
        _related_organization_error(self, "ai_run", errors)
        dimensions = ScoreDimensions(
            self.intent_score,
            self.company_fit_score,
            self.specificity_score,
            self.capability_fit_score,
            self.recency_score,
        )
        gates = EvidenceGates(
            self.traceable_source,
            self.explicit_need_or_company_match,
            self.capability_evidence,
            self.audited_run,
            self.ontology_snapshot_complete,
        )
        try:
            scored = score_lead(dimensions, gates)
        except ValueError as error:
            errors["score"] = str(error)
        else:
            if self.score != scored.total:
                errors["score"] = "Score must equal the five deterministic dimensions."
            if self.score_band != scored.band:
                errors["score_band"] = "Score band must match the deterministic total."
            if self.high_value_eligible != scored.high_value_eligible:
                errors["high_value_eligible"] = "High-value eligibility must match evidence gates."
        snapshot_org = self.ontology_snapshot.get("organization_id") if isinstance(
            self.ontology_snapshot, dict
        ) else None
        if snapshot_org is not None and str(snapshot_org) != str(self.organization_id):
            errors["ontology_snapshot"] = "Ontology snapshot belongs to another organization."
        elif self.ontology_snapshot_complete and snapshot_org is None:
            errors["ontology_snapshot"] = "Complete ontology snapshot must belong to the candidate organization."
        if errors:
            raise ValidationError(errors)


class LeadCandidateEvidence(ImmutableLeadHistory):
    candidate = models.ForeignKey(
        LeadCandidate, on_delete=models.PROTECT, related_name="evidence_links"
    )
    insight = models.ForeignKey(
        LeadInsight, on_delete=models.PROTECT, related_name="evidence_links"
    )
    evidence = models.ForeignKey(
        "sources.SourceEvidence", on_delete=models.PROTECT, related_name="candidate_links"
    )
    source_signal = models.ForeignKey(
        "sources.SourceSignal", on_delete=models.PROTECT, related_name="candidate_evidence_links"
    )

    class Meta(ImmutableLeadHistory.Meta):
        ordering = ["candidate_id", "insight_id", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["insight", "evidence"], name="leads_unique_insight_evidence"
            )
        ]

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}
        for field_name in ("candidate", "insight", "evidence", "source_signal"):
            _related_organization_error(self, field_name, errors)
        insight_candidate_id = LeadInsight._base_manager.filter(pk=self.insight_id).values_list(
            "candidate_id", flat=True
        ).first() if self.insight_id else None
        if self.insight_id and self.candidate_id and insight_candidate_id != self.candidate_id:
            errors["insight"] = "Insight must belong to this candidate."
        evidence_signal_id = None
        if self.evidence_id:
            from apps.sources.models import SourceEvidence

            evidence_signal_id = SourceEvidence._base_manager.filter(pk=self.evidence_id).values_list(
                "source_signal_id", flat=True
            ).first()
        if self.evidence_id and self.source_signal_id and evidence_signal_id != self.source_signal_id:
            errors["source_signal"] = "Source signal must be the evidence source signal."
        if errors:
            raise ValidationError(errors)


class LeadInsightRequirement(ImmutableLeadHistory):
    insight = models.ForeignKey(LeadInsight, on_delete=models.PROTECT, related_name="requirements")
    requirement_concept = models.ForeignKey(
        "knowledge.KnowledgeConcept",
        on_delete=models.PROTECT,
        related_name="lead_requirement_links",
    )
    capability_concept = models.ForeignKey(
        "knowledge.KnowledgeConcept",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lead_capability_links",
    )
    capability_knowledge_evidence = models.ForeignKey(
        "knowledge.KnowledgeEvidence",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lead_capability_evidence_links",
    )
    source_evidence = models.ForeignKey(
        "sources.SourceEvidence", on_delete=models.PROTECT, related_name="lead_requirement_links"
    )
    extracted_value = models.CharField(max_length=500)
    unit = models.CharField(max_length=64, blank=True)

    class Meta(ImmutableLeadHistory.Meta):
        ordering = ["insight_id", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["insight", "requirement_concept", "source_evidence", "extracted_value", "unit"],
                name="leads_unique_insight_requirement",
            )
        ]

    def clean(self):
        super().clean()
        from apps.knowledge.models import KnowledgeConcept, KnowledgeEvidence, KnowledgeStatus

        errors: dict[str, str] = {}
        _related_organization_error(self, "insight", errors)
        _related_organization_error(self, "source_evidence", errors)
        if self.insight_id and self.source_evidence_id:
            if not self.insight.evidence_links.filter(evidence_id=self.source_evidence_id).exists():
                errors["source_evidence"] = "Requirement evidence must be linked to this insight."
        frozen_references = _lead_frozen_references.get()
        for field_name, expected_type in (
            ("requirement_concept", KnowledgeConcept.ConceptType.REQUIREMENT),
            ("capability_concept", KnowledgeConcept.ConceptType.CAPABILITY),
        ):
            concept_id = getattr(self, f"{field_name}_id", None)
            if not concept_id:
                continue
            concept = KnowledgeConcept._base_manager.filter(pk=concept_id).first()
            if concept is None:
                errors[field_name] = f"{field_name.replace('_', ' ').title()} does not exist."
                continue
            frozen_type = (
                frozen_references["concept_types"].get(str(concept_id))
                if frozen_references is not None
                else None
            )
            if frozen_references is not None and (
                frozen_references["organization_id"] != str(self.organization_id)
                or frozen_type != expected_type
            ):
                errors[field_name] = (
                    f"{field_name.replace('_', ' ').title()} is not approved in the frozen ontology."
                )
            elif frozen_references is None and (
                concept.status != KnowledgeStatus.APPROVED
                or concept.concept_type != expected_type
            ):
                errors[field_name] = f"{field_name.replace('_', ' ').title()} must be an approved {expected_type}."
            elif concept.organization_id not in {None, self.organization_id}:
                errors[field_name] = f"{field_name.replace('_', ' ').title()} is not visible to this organization."
        if self.capability_knowledge_evidence_id:
            knowledge_evidence = KnowledgeEvidence._base_manager.filter(
                pk=self.capability_knowledge_evidence_id
            ).first()
            if knowledge_evidence is None:
                errors["capability_knowledge_evidence"] = "Capability knowledge evidence does not exist."
            elif frozen_references is not None and str(
                self.capability_knowledge_evidence_id
            ) not in frozen_references["capability_evidence"].get(
                str(self.capability_concept_id), set()
            ):
                errors["capability_knowledge_evidence"] = (
                    "Capability knowledge evidence is not approved for the frozen capability."
                )
            elif frozen_references is None and knowledge_evidence.status != KnowledgeStatus.APPROVED:
                errors["capability_knowledge_evidence"] = "Capability knowledge evidence must be approved."
            elif knowledge_evidence.organization_id not in {None, self.organization_id}:
                errors["capability_knowledge_evidence"] = (
                    "Capability knowledge evidence is not visible to this organization."
                )
            elif not self.capability_concept_id:
                errors["capability_knowledge_evidence"] = (
                    "Capability knowledge evidence requires a capability concept."
                )
            elif frozen_references is None and not KnowledgeConcept.objects.filter(
                pk=self.capability_concept_id,
                evidence=self.capability_knowledge_evidence_id,
            ).exists():
                errors["capability_knowledge_evidence"] = (
                    "Capability knowledge evidence must support the linked capability."
                )
        if not self.extracted_value.strip():
            errors["extracted_value"] = "Extracted requirement value must not be blank."
        if errors:
            raise ValidationError(errors)
