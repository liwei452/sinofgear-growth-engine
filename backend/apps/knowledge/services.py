from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable, Sequence
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.models import ReviewAction
from apps.audit.services import record_review_transition
from apps.identity.models import Organization

from .models import KnowledgeAlias, KnowledgeConcept, KnowledgeEvidence, KnowledgeRelation, KnowledgeStatus
from .guards import _audited_review_writes
from .normalization import normalize_alias
from .relation_rules import validate_predicate_types


class OntologyDepthError(ValueError):
    pass


class KnowledgeStateError(ValueError):
    pass


@dataclass(frozen=True)
class ConceptMatch:
    concept_id: UUID
    code: str
    concept_type: str
    scope: str
    label_zh: str
    label_en: str


@dataclass(frozen=True)
class AliasResolution:
    ambiguous: bool
    candidates: tuple[ConceptMatch, ...]
    selected: ConceptMatch | None


@dataclass(frozen=True)
class ConceptVersion:
    concept_id: UUID
    code: str
    concept_type: str
    label_zh: str
    label_en: str
    version: int
    status: str


@dataclass(frozen=True)
class RelationVersion:
    relation_id: UUID
    subject_concept_id: UUID
    predicate: str
    object_concept_id: UUID
    version: int
    status: str


@dataclass(frozen=True)
class EvidenceReference:
    evidence_id: UUID
    evidence_type: str
    source_object_type: str
    source_object_id: UUID | None
    source_url: str | None
    excerpt: str
    captured_at: datetime | None
    version: int
    status: str


@dataclass(frozen=True)
class OntologySnapshot:
    organization_id: UUID
    concept_versions: tuple[ConceptVersion, ...]
    relation_versions: tuple[RelationVersion, ...]
    evidence_references: tuple[EvidenceReference, ...]
    generated_at: datetime

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _visible_filter(organization: Organization) -> Q:
    return Q(organization__isnull=True) | Q(organization=organization)


class KnowledgeReviewService:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    @transaction.atomic
    def transition(
        self,
        *,
        instance,
        action: str,
        actor: AbstractBaseUser,
        comment: str = "",
    ):
        if action == ReviewAction.REJECT and not comment.strip():
            raise ValueError("Reject comment must not be empty.")
        from .graph import acquire_knowledge_graph_lock

        acquire_knowledge_graph_lock()
        model = type(instance)
        locked = model.objects.select_for_update().get(pk=instance.pk)
        self._ensure_visible(locked)
        before = self._metadata(locked)
        target_status = {
            ReviewAction.SUBMIT: KnowledgeStatus.SUGGESTED,
            ReviewAction.APPROVE: KnowledgeStatus.APPROVED,
            ReviewAction.REJECT: KnowledgeStatus.REJECTED,
            ReviewAction.DEPRECATE: KnowledgeStatus.DEPRECATED,
        }[action]
        allowed_status = {
            ReviewAction.SUBMIT: KnowledgeStatus.SUGGESTED,
            ReviewAction.APPROVE: KnowledgeStatus.SUGGESTED,
            ReviewAction.REJECT: KnowledgeStatus.SUGGESTED,
            ReviewAction.DEPRECATE: KnowledgeStatus.APPROVED,
        }[action]
        if locked.status != allowed_status:
            raise KnowledgeStateError(f"Cannot {action.lower()} knowledge in status {locked.status}.")
        locked.status = target_status
        locked.version += 1
        if action in {ReviewAction.APPROVE, ReviewAction.REJECT, ReviewAction.DEPRECATE}:
            locked.reviewed_by = actor
            locked.reviewed_at = timezone.now()
        with _audited_review_writes():
            locked.save(update_fields=["status", "version", "reviewed_by", "reviewed_at", "updated_at"])
        after = self._metadata(locked)
        record_review_transition(
            organization=self.organization,
            object_type=f"{locked._meta.app_label}.{locked.__class__.__name__}",
            object_id=locked.pk,
            action=action,
            status=target_status,
            object_version=locked.version,
            actor=actor,
            comment=comment.strip(),
            before_metadata=before,
            after_metadata=after,
        )
        return locked

    def _ensure_visible(self, instance) -> None:
        organization_id = getattr(instance, "organization_id", None)
        if organization_id not in {None, self.organization.id}:
            raise ValidationError("Knowledge object is not visible to this organization.")

    @staticmethod
    def _metadata(instance) -> dict[str, object]:
        return {
            "status": instance.status,
            "version": instance.version,
            "organization_id": str(instance.organization_id) if instance.organization_id else None,
        }


class KnowledgeRelationService:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    @transaction.atomic
    def create(
        self,
        subject: KnowledgeConcept,
        predicate: str,
        object: KnowledgeConcept,
        *,
        status: str = KnowledgeStatus.SUGGESTED,
        confidence=1,
        suggested_by_ai_run_id: UUID | None = None,
        created_by: AbstractBaseUser | None = None,
        scope: str | None = None,
    ) -> KnowledgeRelation:
        self._ensure_concept_visible(subject)
        self._ensure_concept_visible(object)
        validate_predicate_types(subject=subject, predicate=predicate, object=object)
        if scope == KnowledgeConcept.Scope.SYSTEM:
            if subject.organization_id is not None or object.organization_id is not None:
                raise ValidationError("SYSTEM relations require SYSTEM concepts.")
            relation_organization = None
        elif scope == KnowledgeConcept.Scope.ORGANIZATION:
            relation_organization = self.organization
        else:
            relation_organization = None if subject.organization_id is None and object.organization_id is None else self.organization
        relation = KnowledgeRelation(
            organization=relation_organization,
            subject_concept=subject,
            predicate=predicate,
            object_concept=object,
            status=status,
            confidence=confidence,
            suggested_by_ai_run_id=suggested_by_ai_run_id,
            created_by=created_by,
        )
        relation.clean()
        relation.save()
        return relation

    def _ensure_concept_visible(self, concept: KnowledgeConcept) -> None:
        if concept.organization_id not in {None, self.organization.id}:
            raise ValidationError("Concept is not visible to this organization.")

    @staticmethod
    def graph_lock_concept_ids(
        *, subject: KnowledgeConcept, object: KnowledgeConcept
    ) -> tuple[UUID, ...]:
        return tuple(sorted({subject.id, object.id}, key=str))

class OntologyContextService:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    def visible_concepts(self) -> QuerySet[KnowledgeConcept]:
        return KnowledgeConcept.objects.filter(_visible_filter(self.organization)).order_by("code", "id")

    def visible_relations(self) -> QuerySet[KnowledgeRelation]:
        return KnowledgeRelation.objects.filter(_visible_filter(self.organization)).order_by(
            "subject_concept__code", "predicate", "object_concept__code", "id"
        )

    def visible_aliases(self) -> QuerySet[KnowledgeAlias]:
        return KnowledgeAlias.objects.filter(_visible_filter(self.organization)).order_by(
            "normalized_alias", "concept__code", "id"
        )

    def visible_evidence(self) -> QuerySet[KnowledgeEvidence]:
        return KnowledgeEvidence.objects.filter(_visible_filter(self.organization)).order_by("created_at", "id")

    def resolve_alias(self, *, text: str, language: str) -> AliasResolution:
        normalized = normalize_alias(text, language=language)
        aliases = self.visible_aliases().filter(
            language=language.strip().lower(),
            normalized_alias=normalized,
            status=KnowledgeStatus.APPROVED,
            concept__status=KnowledgeStatus.APPROVED,
        ).select_related("concept")
        matches_by_id: dict[UUID, ConceptMatch] = {}
        for alias in aliases:
            concept = alias.concept
            matches_by_id[concept.id] = ConceptMatch(
                concept_id=concept.id,
                code=concept.code,
                concept_type=concept.concept_type,
                scope=concept.scope,
                label_zh=concept.label_zh,
                label_en=concept.label_en,
            )
        candidates = tuple(sorted(matches_by_id.values(), key=lambda item: (item.code, str(item.concept_id))))
        return AliasResolution(
            ambiguous=len(candidates) > 1,
            candidates=candidates,
            selected=candidates[0] if len(candidates) == 1 else None,
        )

    def expand_concepts(
        self,
        *,
        concept_ids: Sequence[UUID],
        predicates: Iterable[str] | None = None,
        max_depth: int = 2,
    ) -> OntologySnapshot:
        self._validate_depth(max_depth)
        predicate_values = tuple(
            sorted(set(KnowledgeRelation.Predicate.values if predicates is None else predicates))
        )
        invalid = set(predicate_values) - set(KnowledgeRelation.Predicate.values)
        if invalid:
            raise ValidationError({"predicates": f"Unsupported predicates: {', '.join(sorted(invalid))}"})
        concepts = {
            item.id: item
            for item in self.visible_concepts().filter(id__in=concept_ids, status=KnowledgeStatus.APPROVED)
        }
        frontier = set(concepts)
        included_relations: dict[UUID, KnowledgeRelation] = {}
        for _depth in range(max_depth):
            if not frontier:
                break
            relations = list(
                self.visible_relations()
                .filter(
                    subject_concept_id__in=frontier,
                    predicate__in=predicate_values,
                    status=KnowledgeStatus.APPROVED,
                    object_concept__status=KnowledgeStatus.APPROVED,
                )
                .select_related("subject_concept", "object_concept")
            )
            next_frontier: set[UUID] = set()
            for relation in relations:
                object_concept = relation.object_concept
                if object_concept.organization_id not in {None, self.organization.id}:
                    continue
                included_relations[relation.id] = relation
                if object_concept.id not in concepts:
                    concepts[object_concept.id] = object_concept
                    next_frontier.add(object_concept.id)
            frontier = next_frontier
        concept_rows = sorted(concepts.values(), key=lambda item: (item.code, str(item.id)))
        relation_rows = sorted(
            included_relations.values(),
            key=lambda item: (
                item.subject_concept.code,
                item.predicate,
                item.object_concept.code,
                str(item.id),
            ),
        )
        evidence = self._snapshot_evidence(concept_rows=concept_rows, relation_rows=relation_rows)
        return OntologySnapshot(
            organization_id=self.organization.id,
            concept_versions=tuple(
                ConceptVersion(
                    concept_id=item.id,
                    code=item.code,
                    concept_type=item.concept_type,
                    label_zh=item.label_zh,
                    label_en=item.label_en,
                    version=item.version,
                    status=item.status,
                )
                for item in concept_rows
            ),
            relation_versions=tuple(
                RelationVersion(
                    relation_id=item.id,
                    subject_concept_id=item.subject_concept_id,
                    predicate=item.predicate,
                    object_concept_id=item.object_concept_id,
                    version=item.version,
                    status=item.status,
                )
                for item in relation_rows
            ),
            evidence_references=tuple(
                EvidenceReference(
                    evidence_id=item.id,
                    evidence_type=item.evidence_type,
                    source_object_type=item.source_object_type,
                    source_object_id=item.source_object_id,
                    source_url=item.source_url,
                    excerpt=item.excerpt,
                    captured_at=item.captured_at,
                    version=item.version,
                    status=item.status,
                )
                for item in evidence
            ),
            generated_at=timezone.now(),
        )

    def build_snapshot(self, *, concept_ids: Sequence[UUID], max_depth: int = 2) -> OntologySnapshot:
        return self.expand_concepts(concept_ids=concept_ids, max_depth=max_depth)

    def _snapshot_evidence(
        self,
        *,
        concept_rows: Sequence[KnowledgeConcept],
        relation_rows: Sequence[KnowledgeRelation],
    ) -> list[KnowledgeEvidence]:
        evidence_ids: set[UUID] = set()
        for concept in concept_rows:
            evidence_ids.update(concept.evidence.values_list("id", flat=True))
        for relation in relation_rows:
            evidence_ids.update(relation.evidence.values_list("id", flat=True))
        return list(
            self.visible_evidence()
            .filter(id__in=evidence_ids, status=KnowledgeStatus.APPROVED)
            .order_by("id")
        )

    @staticmethod
    def _validate_depth(max_depth: int) -> None:
        if not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 0 or max_depth > 2:
            raise OntologyDepthError("Ontology expansion depth must be between 0 and 2")

    def submit_review(self, concept_id: UUID, *, actor: AbstractBaseUser, comment: str = "") -> KnowledgeConcept:
        return self._transition(concept_id, actor=actor, action=ReviewAction.SUBMIT, comment=comment)

    def approve(self, concept_id: UUID, *, actor: AbstractBaseUser, comment: str = "") -> KnowledgeConcept:
        return self._transition(concept_id, actor=actor, action=ReviewAction.APPROVE, comment=comment)

    def reject(self, concept_id: UUID, *, actor: AbstractBaseUser, comment: str) -> KnowledgeConcept:
        return self._transition(concept_id, actor=actor, action=ReviewAction.REJECT, comment=comment)

    def deprecate(self, concept_id: UUID, *, actor: AbstractBaseUser, comment: str = "") -> KnowledgeConcept:
        return self._transition(concept_id, actor=actor, action=ReviewAction.DEPRECATE, comment=comment)

    def _transition(
        self, concept_id: UUID, *, actor: AbstractBaseUser, action: str, comment: str
    ) -> KnowledgeConcept:
        concept = self.visible_concepts().get(id=concept_id)
        return KnowledgeReviewService(self.organization).transition(
            instance=concept, action=action, actor=actor, comment=comment
        )


def build_snapshot(
    *, organization: Organization, concept_ids: Sequence[UUID], max_depth: int = 2
) -> OntologySnapshot:
    return OntologyContextService(organization).build_snapshot(concept_ids=concept_ids, max_depth=max_depth)
