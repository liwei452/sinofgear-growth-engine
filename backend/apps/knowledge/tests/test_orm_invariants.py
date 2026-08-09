import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.audit.models import ApprovalRecord, AuditLog
from apps.knowledge.guards import _system_seed_writes
from apps.knowledge.models import KnowledgeAlias, KnowledgeConcept, KnowledgeEvidence, KnowledgeRelation
from apps.knowledge.services import OntologyContextService

from .conftest import make_concept


@pytest.mark.django_db
def test_direct_alias_create_cannot_expose_a_foreign_concept(organizations) -> None:
    own, other = organizations
    foreign = make_concept(code="FOREIGN", organization=other)

    with pytest.raises(ValidationError, match="visible"):
        KnowledgeAlias.objects.create(
            organization=own,
            concept=foreign,
            language="en",
            alias="foreign leak",
            status="SUGGESTED",
        )

    assert OntologyContextService(own).resolve_alias(text="foreign leak", language="en").candidates == ()


@pytest.mark.django_db
def test_alias_queryset_update_cannot_repoint_to_a_foreign_concept(organizations) -> None:
    own, other = organizations
    local = make_concept(code="LOCAL", organization=own)
    foreign = make_concept(code="FOREIGN", organization=other)
    alias = KnowledgeAlias.objects.create(
        organization=own, concept=local, language="en", alias="local", status="SUGGESTED"
    )

    with pytest.raises(ValidationError, match="visible|identity"):
        KnowledgeAlias.objects.filter(id=alias.id).update(concept=foreign)

    alias.refresh_from_db()
    assert alias.concept == local


@pytest.mark.django_db
def test_alias_bulk_create_validates_cross_organization_scope(organizations) -> None:
    own, other = organizations
    foreign = make_concept(code="FOREIGN", organization=other)
    attack = KnowledgeAlias(
        organization=own, concept=foreign, language="en", alias="bulk leak", status="SUGGESTED"
    )

    with pytest.raises(ValidationError, match="visible"):
        KnowledgeAlias.objects.bulk_create([attack])

    assert not KnowledgeAlias.objects.exists()


@pytest.mark.django_db
def test_relation_save_and_bulk_update_enforce_concept_visibility(organizations) -> None:
    own, other = organizations
    local = make_concept(code="LOCAL")
    own_app = make_concept(code="OWN_APP", concept_type="APPLICATION", organization=own)
    foreign_app = make_concept(code="FOREIGN_APP", concept_type="APPLICATION", organization=other)
    relation = KnowledgeRelation.objects.create(
        organization=own,
        subject_concept=local,
        predicate="APPLIES_TO",
        object_concept=own_app,
        status="SUGGESTED",
    )
    relation.object_concept = foreign_app

    with pytest.raises(ValidationError, match="visible|identity"):
        KnowledgeRelation.objects.bulk_update([relation], ["object_concept"])

    relation.refresh_from_db()
    assert relation.object_concept == own_app


@pytest.mark.django_db
@pytest.mark.parametrize("owner_type", ["concept", "relation"])
def test_m2m_add_rejects_cross_organization_evidence(organizations, owner_type) -> None:
    own, other = organizations
    concept = make_concept(code="OWNER", organization=own)
    evidence = KnowledgeEvidence.objects.create(
        organization=other, evidence_type="HUMAN_ENTRY", excerpt="foreign", status="SUGGESTED"
    )
    if owner_type == "concept":
        owner = concept
    else:
        target = make_concept(code="TARGET", concept_type="APPLICATION", organization=own)
        owner = KnowledgeRelation.objects.create(
            organization=own,
            subject_concept=concept,
            predicate="APPLIES_TO",
            object_concept=target,
            status="SUGGESTED",
        )

    with pytest.raises(ValidationError, match="evidence"), transaction.atomic():
        owner.evidence.add(evidence)

    assert owner.evidence.count() == 0


@pytest.mark.django_db
def test_system_owner_cannot_link_organization_evidence_via_set(organizations) -> None:
    system = make_concept(code="SYSTEM_OWNER")
    organization_evidence = KnowledgeEvidence.objects.create(
        organization=organizations[0], evidence_type="HUMAN_ENTRY", excerpt="local", status="SUGGESTED"
    )

    with pytest.raises(ValidationError, match="SYSTEM"), transaction.atomic():
        system.evidence.set([organization_evidence])

    assert system.evidence.count() == 0


@pytest.mark.django_db
def test_evidence_queryset_and_bulk_updates_cannot_change_source_snapshot(organizations) -> None:
    evidence = KnowledgeEvidence.objects.create(
        organization=organizations[0], evidence_type="PUBLIC_SOURCE", excerpt="original", status="SUGGESTED"
    )

    with pytest.raises(ValidationError, match="immutable"):
        KnowledgeEvidence.objects.filter(id=evidence.id).update(excerpt="queryset overwrite")
    evidence.excerpt = "bulk overwrite"
    with pytest.raises(ValidationError, match="immutable"):
        KnowledgeEvidence.objects.bulk_update([evidence], ["excerpt"])

    evidence.refresh_from_db()
    assert evidence.excerpt == "original"


@pytest.mark.django_db
@pytest.mark.parametrize("delete_style", ["instance", "queryset"])
def test_referenced_evidence_cannot_be_deleted_and_join_is_preserved(organizations, delete_style) -> None:
    concept = make_concept(code="REFERENCED", organization=organizations[0])
    evidence = KnowledgeEvidence.objects.create(
        organization=organizations[0], evidence_type="HUMAN_ENTRY", excerpt="retained", status="SUGGESTED"
    )
    concept.evidence.add(evidence)

    with pytest.raises(ProtectedError, match="referenced"):
        if delete_style == "instance":
            evidence.delete()
        else:
            KnowledgeEvidence.objects.filter(id=evidence.id).delete()

    assert KnowledgeEvidence.objects.filter(id=evidence.id).exists()
    assert concept.evidence.filter(id=evidence.id).exists()


@pytest.mark.django_db
def test_owner_with_evidence_link_uses_reusable_retention_rule(organizations) -> None:
    concept = make_concept(code="OWNER_REFERENCED", organization=organizations[0])
    evidence = KnowledgeEvidence.objects.create(
        organization=organizations[0], evidence_type="HUMAN_ENTRY", excerpt="retained", status="SUGGESTED"
    )
    concept.evidence.add(evidence)

    with pytest.raises(ProtectedError, match="referenced"):
        KnowledgeConcept.objects.filter(id=concept.id).delete()

    assert KnowledgeConcept.objects.filter(id=concept.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("model_name", ["concept", "alias", "relation", "evidence"])
def test_ai_originated_ordinary_create_cannot_start_approved(organizations, model_name) -> None:
    own, _ = organizations
    run_id = uuid.uuid4()
    concept = make_concept(code="AI_BASE", organization=own)
    target = make_concept(code="AI_TARGET", concept_type="APPLICATION", organization=own)
    factories = {
        "concept": lambda: KnowledgeConcept.objects.create(
            scope="ORGANIZATION", organization=own, concept_type="PRODUCT_TYPE", code="AI_APPROVED",
            label_zh="AI", label_en="AI", status="APPROVED", suggested_by_ai_run_id=run_id,
        ),
        "alias": lambda: KnowledgeAlias.objects.create(
            organization=own, concept=concept, language="en", alias="ai approved",
            status="APPROVED", suggested_by_ai_run_id=run_id,
        ),
        "relation": lambda: KnowledgeRelation.objects.create(
            organization=own, subject_concept=concept, predicate="APPLIES_TO", object_concept=target,
            status="APPROVED", suggested_by_ai_run_id=run_id,
        ),
        "evidence": lambda: KnowledgeEvidence.objects.create(
            organization=own, evidence_type="HUMAN_ENTRY", excerpt="AI", status="APPROVED",
            suggested_by_ai_run_id=run_id,
        ),
    }

    with pytest.raises(ValidationError, match="SUGGESTED"):
        factories[model_name]()


@pytest.mark.django_db
@pytest.mark.parametrize("model_name", ["concept", "alias", "relation", "evidence"])
def test_ai_originated_bulk_create_cannot_start_approved(organizations, model_name) -> None:
    own, _ = organizations
    run_id = uuid.uuid4()
    concept = make_concept(code="AI_BULK_BASE", organization=own)
    target = make_concept(code="AI_BULK_TARGET", concept_type="APPLICATION", organization=own)
    objects = {
        "concept": KnowledgeConcept(
            scope="ORGANIZATION", organization=own, concept_type="PRODUCT_TYPE",
            code="AI_BULK_APPROVED", label_zh="AI", label_en="AI",
            status="APPROVED", suggested_by_ai_run_id=run_id,
        ),
        "alias": KnowledgeAlias(
            organization=own, concept=concept, language="en", alias="ai bulk approved",
            status="APPROVED", suggested_by_ai_run_id=run_id,
        ),
        "relation": KnowledgeRelation(
            organization=own, subject_concept=concept, predicate="APPLIES_TO", object_concept=target,
            status="APPROVED", suggested_by_ai_run_id=run_id,
        ),
        "evidence": KnowledgeEvidence(
            organization=own, evidence_type="HUMAN_ENTRY", excerpt="AI bulk",
            status="APPROVED", suggested_by_ai_run_id=run_id,
        ),
    }
    instance = objects[model_name]

    with pytest.raises(ValidationError, match="SUGGESTED"):
        type(instance).objects.bulk_create([instance])


@pytest.mark.django_db
def test_direct_status_and_version_updates_cannot_bypass_audit(organizations) -> None:
    concept = KnowledgeConcept.objects.create(
        scope="ORGANIZATION", organization=organizations[0], concept_type="PRODUCT_TYPE",
        code="DIRECT_BYPASS", label_zh="直接", label_en="Direct", status="SUGGESTED",
    )

    with pytest.raises(ValidationError, match="review service"):
        KnowledgeConcept.objects.filter(id=concept.id).update(status="APPROVED", version=2)
    concept.status = "APPROVED"
    concept.version = 2
    with pytest.raises(ValidationError, match="review service"):
        concept.save()
    with pytest.raises(ValidationError, match="review service"):
        KnowledgeConcept.objects.bulk_update([concept], ["status", "version"])

    concept.refresh_from_db()
    assert concept.status == "SUGGESTED"
    assert concept.version == 1
    assert not ApprovalRecord.objects.filter(object_id=concept.id).exists()
    assert not AuditLog.objects.filter(object_id=concept.id).exists()


@pytest.mark.django_db
def test_system_seed_escape_hatch_cannot_mutate_organization_knowledge(organizations) -> None:
    concept = KnowledgeConcept.objects.create(
        scope="ORGANIZATION",
        organization=organizations[0],
        concept_type="PRODUCT_TYPE",
        code="ORG_SEED_GUARD",
        label_zh="组织",
        label_en="Organization",
        status="SUGGESTED",
    )

    with pytest.raises(ValidationError, match="SYSTEM seed"), _system_seed_writes():
        KnowledgeConcept.objects.filter(id=concept.id).update(status="APPROVED")

    concept.refresh_from_db()
    assert concept.status == "SUGGESTED"
