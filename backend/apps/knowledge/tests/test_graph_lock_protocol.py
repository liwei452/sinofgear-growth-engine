from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.audit.models import ReviewAction
from apps.knowledge.models import (
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeRelation,
)
from apps.knowledge.services import KnowledgeReviewService

from .conftest import make_concept


def _make_snapshot_record(kind, organization, suffix="CURRENT"):
    if kind == "concept":
        return make_concept(
            code=f"LOCK_{suffix}", organization=organization, status="SUGGESTED"
        )
    if kind == "evidence":
        return KnowledgeEvidence.objects.create(
            organization=organization,
            evidence_type="HUMAN_ENTRY",
            excerpt=f"lock {suffix}",
            status="SUGGESTED",
        )
    subject = make_concept(
        code=f"LOCK_SUBJECT_{suffix}", organization=organization, status="SUGGESTED"
    )
    target = make_concept(
        code=f"LOCK_TARGET_{suffix}",
        concept_type="APPLICATION",
        organization=organization,
        status="SUGGESTED",
    )
    return KnowledgeRelation.objects.create(
        organization=organization,
        subject_concept=subject,
        predicate="APPLIES_TO",
        object_concept=target,
        status="SUGGESTED",
    )


def _mutate(instance, write_style):
    model = type(instance)
    if isinstance(instance, KnowledgeConcept):
        field, value = "description", "changed under graph lock"
    elif isinstance(instance, KnowledgeEvidence):
        field, value = "reviewed_at", timezone.now()
    else:
        field, value = "confidence", Decimal("0.5000")
    if write_style == "save":
        setattr(instance, field, value)
        instance.save(update_fields=[field])
    elif write_style == "queryset":
        model.objects.filter(pk=instance.pk).update(**{field: value})
    elif write_style == "base_queryset":
        model._base_manager.filter(pk=instance.pk).update(**{field: value})
    elif write_style == "bulk_update":
        setattr(instance, field, value)
        model.objects.bulk_update([instance], [field])
    else:
        raise AssertionError(write_style)
    instance.refresh_from_db()
    assert getattr(instance, field) == value


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["concept", "relation", "evidence"])
@pytest.mark.parametrize(
    "write_style", ["save", "queryset", "base_queryset", "bulk_update"]
)
def test_snapshot_record_mutations_acquire_canonical_graph_lock(
    organizations, kind, write_style
):
    instance = _make_snapshot_record(kind, organizations[0], suffix=write_style)

    with patch(
        "apps.knowledge.graph.acquire_knowledge_graph_lock",
        wraps=__import__(
            "apps.knowledge.graph", fromlist=["acquire_knowledge_graph_lock"]
        ).acquire_knowledge_graph_lock,
    ) as acquire:
        _mutate(instance, write_style)

    assert acquire.called


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["concept", "relation", "evidence"])
@pytest.mark.parametrize("use_base", [False, True])
def test_snapshot_record_deletes_acquire_canonical_graph_lock(
    organizations, kind, use_base
):
    instance = _make_snapshot_record(kind, organizations[0], suffix=f"DELETE_{use_base}")
    model = type(instance)
    from apps.knowledge import graph

    with patch.object(
        graph,
        "acquire_knowledge_graph_lock",
        wraps=graph.acquire_knowledge_graph_lock,
    ) as acquire:
        manager = model._base_manager if use_base else model.objects
        manager.filter(pk=instance.pk).delete()

    assert acquire.called
    assert not model.objects.filter(pk=instance.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["concept", "relation", "evidence"])
def test_snapshot_record_bulk_create_acquires_canonical_graph_lock(
    organizations, kind
):
    instance = _make_snapshot_record(kind, organizations[0], suffix="BULK_SOURCE")
    instance.pk = None
    instance._state.adding = True
    if isinstance(instance, KnowledgeConcept):
        instance.code = f"{instance.code}_COPY"
    elif isinstance(instance, KnowledgeEvidence):
        instance.excerpt = f"{instance.excerpt} copy"
    else:
        target = make_concept(
            code="LOCK_BULK_OTHER_TARGET",
            concept_type="INDUSTRY",
            organization=organizations[0],
            status="SUGGESTED",
        )
        instance.object_concept = target
    from apps.knowledge import graph

    with patch.object(
        graph,
        "acquire_knowledge_graph_lock",
        wraps=graph.acquire_knowledge_graph_lock,
    ) as acquire:
        type(instance).objects.bulk_create([instance])

    assert acquire.called


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["concept", "relation", "evidence"])
def test_review_transition_acquires_graph_lock_before_record_lock(
    organizations, kind
):
    own, _ = organizations
    instance = _make_snapshot_record(kind, own, suffix="REVIEW")
    actor = get_user_model().objects.create_user(username=f"lock-review-{kind}")
    events = []
    from apps.knowledge import graph
    manager = type(instance).objects
    original_graph_lock = graph.acquire_knowledge_graph_lock
    original_row_lock = manager.select_for_update

    def graph_lock():
        events.append("graph")
        return original_graph_lock()

    def row_lock(*args, **kwargs):
        events.append("row")
        return original_row_lock(*args, **kwargs)

    with (
        patch.object(graph, "acquire_knowledge_graph_lock", side_effect=graph_lock),
        patch.object(manager, "select_for_update", side_effect=row_lock),
    ):
        KnowledgeReviewService(own).transition(
            instance=instance,
            action=ReviewAction.APPROVE,
            actor=actor,
        )

    assert events.index("graph") < events.index("row")


def _association_owner(kind, organization, suffix):
    if kind == "concept":
        return _make_snapshot_record("concept", organization, suffix)
    return _make_snapshot_record("relation", organization, suffix)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["concept", "relation"])
@pytest.mark.parametrize("action", ["add", "remove", "clear"])
def test_evidence_relation_manager_acquires_canonical_graph_lock(
    organizations, kind, action
):
    from apps.knowledge import graph

    owner = _association_owner(kind, organizations[0], f"M2M_{action}")
    evidence = _make_snapshot_record("evidence", organizations[0], f"M2M_{action}")
    if action in {"remove", "clear"}:
        owner.evidence.add(evidence)

    with patch.object(
        graph,
        "acquire_knowledge_graph_lock",
        wraps=graph.acquire_knowledge_graph_lock,
    ) as acquire:
        if action == "add":
            owner.evidence.add(evidence)
        elif action == "remove":
            owner.evidence.remove(evidence)
        else:
            owner.evidence.clear()

    assert acquire.called


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["concept", "relation"])
@pytest.mark.parametrize(
    "write_style",
    [
        "create",
        "base_create",
        "bulk_create",
        "base_bulk_create",
        "update",
        "base_update",
        "bulk_update",
        "base_bulk_update",
        "instance_save",
        "instance_delete",
        "delete",
        "base_delete",
    ],
)
def test_evidence_through_direct_writes_acquire_canonical_graph_lock(
    organizations, kind, write_style
):
    from apps.knowledge import graph

    owner = _association_owner(kind, organizations[0], f"THROUGH_{write_style}")
    evidence = _make_snapshot_record(
        "evidence", organizations[0], f"THROUGH_{write_style}"
    )
    through = owner.evidence.through
    source_field = "knowledgeconcept" if kind == "concept" else "knowledgerelation"
    values = {source_field: owner, "knowledgeevidence": evidence}
    manager = through._base_manager if write_style.startswith("base_") else through.objects
    operation = write_style.removeprefix("base_")
    association = None
    if operation in {"update", "bulk_update", "instance_save", "instance_delete", "delete"}:
        association = through.objects.create(**values)

    with patch.object(
        graph,
        "acquire_knowledge_graph_lock",
        wraps=graph.acquire_knowledge_graph_lock,
    ) as acquire:
        if operation == "create":
            manager.create(**values)
        elif operation == "bulk_create":
            manager.bulk_create([through(**values)])
        elif operation == "update":
            manager.filter(pk=association.pk).update(knowledgeevidence=evidence)
        elif operation == "bulk_update":
            manager.bulk_update([association], ["knowledgeevidence"])
        elif operation == "instance_save":
            association.save(update_fields=["knowledgeevidence"])
        elif operation == "instance_delete":
            association.delete()
        else:
            manager.filter(**values).delete()

    assert acquire.called
