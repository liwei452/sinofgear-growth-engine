import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.knowledge.models import KnowledgeConcept, KnowledgeEvidence
from apps.knowledge.services import OntologyContextService

from .conftest import make_concept


@pytest.mark.django_db
def test_organization_reads_system_and_own_concepts_but_not_other_org(organizations) -> None:
    own, other = organizations
    system = make_concept(code="HELICAL_GEAR")
    own_concept = make_concept(code="OWN_GEAR", organization=own)
    other_concept = make_concept(code="OTHER_GEAR", organization=other)

    visible = list(OntologyContextService(own).visible_concepts())

    assert system in visible
    assert own_concept in visible
    assert other_concept not in visible


@pytest.mark.django_db
def test_duplicate_system_and_organization_codes_are_rejected(organizations) -> None:
    own, other = organizations
    make_concept(code="GEAR")
    make_concept(code="CUSTOM", organization=own)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_concept(code="GEAR")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_concept(code="CUSTOM", organization=own)

    assert make_concept(code="CUSTOM", organization=other).pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("scope", "has_organization"),
    [(KnowledgeConcept.Scope.SYSTEM, True), (KnowledgeConcept.Scope.ORGANIZATION, False)],
)
def test_malformed_scope_combinations_are_rejected(organizations, scope, has_organization) -> None:
    concept = KnowledgeConcept(
        scope=scope,
        organization=organizations[0] if has_organization else None,
        concept_type=KnowledgeConcept.ConceptType.PRODUCT_TYPE,
        code=f"BAD_{scope}",
        label_zh="bad",
        label_en="bad",
    )

    with pytest.raises(ValidationError, match="organization"):
        concept.full_clean()


@pytest.mark.django_db
def test_other_organization_evidence_is_not_visible(organizations) -> None:
    own, other = organizations
    own_evidence = KnowledgeEvidence.objects.create(
        organization=own,
        evidence_type=KnowledgeEvidence.EvidenceType.HUMAN_ENTRY,
        excerpt="own",
        status=KnowledgeEvidence.Status.APPROVED,
    )
    KnowledgeEvidence.objects.create(
        organization=other,
        evidence_type=KnowledgeEvidence.EvidenceType.HUMAN_ENTRY,
        excerpt="other",
        status=KnowledgeEvidence.Status.APPROVED,
    )

    assert list(OntologyContextService(own).visible_evidence()) == [own_evidence]


@pytest.mark.django_db
def test_deprecate_is_the_durable_replacement_for_deleting_referenced_knowledge(organizations, roles) -> None:
    from .conftest import create_member_client

    membership, _ = create_member_client(
        organization=organizations[0], role=roles["ADMINISTRATOR"], username="admin-deprecate"
    )
    concept = make_concept(code="REFERENCED_GEAR")

    result = OntologyContextService(organizations[0]).deprecate(concept.id, actor=membership.user)

    assert result.status == KnowledgeConcept.Status.DEPRECATED
    assert KnowledgeConcept.objects.filter(id=concept.id).exists()


@pytest.mark.django_db
def test_evidence_source_snapshot_cannot_be_overwritten(organizations) -> None:
    evidence = KnowledgeEvidence.objects.create(
        organization=organizations[0],
        evidence_type=KnowledgeEvidence.EvidenceType.PUBLIC_SOURCE,
        source_url="https://example.test/original",
        excerpt="Original excerpt",
        status=KnowledgeEvidence.Status.APPROVED,
    )
    evidence.excerpt = "Replacement excerpt"

    with pytest.raises(ValidationError, match="immutable"):
        evidence.save()
