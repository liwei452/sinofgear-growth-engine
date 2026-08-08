import pytest

from apps.knowledge.models import KnowledgeAlias, KnowledgeConcept
from apps.knowledge.normalization import normalize_alias
from apps.knowledge.services import OntologyContextService

from .conftest import make_concept


@pytest.mark.parametrize(
    ("value", "language", "expected"),
    [("  HELICAL   Gears ", "en", "helical gears"), ("  斜 齿轮  ", "zh", "斜 齿轮")],
)
def test_alias_normalization_is_deterministic(value, language, expected) -> None:
    assert normalize_alias(value, language=language) == expected


@pytest.mark.django_db
def test_resolve_alias_matches_language_case_and_whitespace(organizations) -> None:
    concept = make_concept(code="HELICAL_GEAR")
    KnowledgeAlias.objects.create(
        concept=concept,
        language="en",
        alias="Helical Gears",
        normalized_alias="helical gears",
        alias_type=KnowledgeAlias.AliasType.SYNONYM,
        status=KnowledgeAlias.Status.APPROVED,
    )

    result = OntologyContextService(organizations[0]).resolve_alias(text=" HELICAL   gears ", language="EN")

    assert result.ambiguous is False
    assert [candidate.code for candidate in result.candidates] == ["HELICAL_GEAR"]


@pytest.mark.django_db
def test_ambiguous_alias_returns_ordered_candidates_without_choosing(organizations) -> None:
    own, _ = organizations
    system = make_concept(code="SYSTEM_GEAR")
    custom = make_concept(code="CUSTOM_GEAR", organization=own)
    for concept in (system, custom):
        KnowledgeAlias.objects.create(
            concept=concept,
            organization=concept.organization,
            language="en",
            alias="gear solution",
            normalized_alias="gear solution",
            alias_type=KnowledgeAlias.AliasType.MARKET_TERM,
            status=KnowledgeAlias.Status.APPROVED,
        )

    result = OntologyContextService(own).resolve_alias(text="Gear Solution", language="en")

    assert result.ambiguous is True
    assert result.selected is None
    assert [item.code for item in result.candidates] == ["CUSTOM_GEAR", "SYSTEM_GEAR"]


@pytest.mark.django_db
def test_unapproved_and_other_organization_aliases_never_resolve(organizations) -> None:
    own, other = organizations
    suggested = make_concept(code="SUGGESTED", organization=own, status=KnowledgeConcept.Status.SUGGESTED)
    foreign = make_concept(code="FOREIGN", organization=other)
    for concept in (suggested, foreign):
        KnowledgeAlias.objects.create(
            concept=concept,
            organization=concept.organization,
            language="en",
            alias="hidden alias",
            normalized_alias="hidden alias",
            status=KnowledgeAlias.Status.APPROVED,
        )

    assert OntologyContextService(own).resolve_alias(text="hidden alias", language="en").candidates == ()
