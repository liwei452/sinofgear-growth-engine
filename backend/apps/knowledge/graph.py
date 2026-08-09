from uuid import UUID

from django.db.models import Q

from .models import KnowledgeConcept, KnowledgeGraphLock, KnowledgeRelation, KnowledgeStatus
from .relation_rules import RelationCycleError


KNOWLEDGE_GRAPH_LOCK_ID = 1


def acquire_knowledge_graph_lock() -> KnowledgeGraphLock:
    """Acquire the canonical lock before reading or mutating snapshot graph state."""
    return KnowledgeGraphLock.objects.select_for_update().get(
        pk=KNOWLEDGE_GRAPH_LOCK_ID
    )
def reject_is_a_cycle(
    *,
    subject: KnowledgeConcept,
    object: KnowledgeConcept,
    relation_organization_id: UUID | None,
    exclude_relation_id: UUID | None = None,
) -> None:
    if subject.id == object.id:
        raise RelationCycleError(
            [subject.code, subject.code], organization_id=relation_organization_id
        )
    if relation_organization_id is None:
        overlay_ids = list(
            KnowledgeRelation.objects.filter(predicate=KnowledgeRelation.Predicate.IS_A)
            .exclude(organization_id__isnull=True)
            .values_list("organization_id", flat=True)
            .distinct()
            .order_by("organization_id")
        )
        overlays = [None, *overlay_ids]
    else:
        overlays = [relation_organization_id]
    for overlay_id in overlays:
        _reject_cycle_in_overlay(
            subject=subject,
            object=object,
            organization_id=overlay_id,
            exclude_relation_id=exclude_relation_id,
        )


def _reject_cycle_in_overlay(
    *,
    subject: KnowledgeConcept,
    object: KnowledgeConcept,
    organization_id: UUID | None,
    exclude_relation_id: UUID | None,
) -> None:
    visibility = Q(organization_id__isnull=True)
    if organization_id is not None:
        visibility |= Q(organization_id=organization_id)
    relations = KnowledgeRelation.objects.filter(
        visibility,
        predicate=KnowledgeRelation.Predicate.IS_A,
    ).exclude(status__in=[KnowledgeStatus.REJECTED, KnowledgeStatus.DEPRECATED])
    if exclude_relation_id is not None:
        relations = relations.exclude(id=exclude_relation_id)
    adjacency: dict[UUID, list[tuple[UUID, str]]] = {}
    for source_id, target_id, target_code in relations.values_list(
        "subject_concept_id", "object_concept_id", "object_concept__code"
    ):
        adjacency.setdefault(source_id, []).append((target_id, target_code))
    for edges in adjacency.values():
        edges.sort(key=lambda item: (item[1], str(item[0])))
    queue: list[tuple[UUID, list[str]]] = [(object.id, [object.code])]
    visited: set[UUID] = set()
    while queue:
        current, path = queue.pop(0)
        if current == subject.id:
            raise RelationCycleError(
                [subject.code, *path], organization_id=organization_id
            )
        if current in visited:
            continue
        visited.add(current)
        for target_id, target_code in adjacency.get(current, []):
            queue.append((target_id, [*path, target_code]))
