import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from apps.knowledge.guards import _system_seed_writes, _test_fixture_writes
from apps.knowledge.models import (
    KnowledgeAlias,
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeRelation,
)
from apps.knowledge.relation_rules import RelationCycleError, RelationRuleError
from apps.knowledge.services import KnowledgeRelationService

from .conftest import make_concept


def _organization_record(model_name, own):
    concept = make_concept(code=f"OWNER_{model_name}", organization=own, status="SUGGESTED")
    if model_name == "concept":
        return concept
    if model_name == "alias":
        return KnowledgeAlias.objects.create(
            organization=own, concept=concept, language="en", alias="owner", status="SUGGESTED"
        )
    if model_name == "evidence":
        return KnowledgeEvidence.objects.create(
            organization=own, evidence_type="HUMAN_ENTRY", excerpt="owner", status="SUGGESTED"
        )
    target = make_concept(
        code="OWNER_TARGET", concept_type="APPLICATION", organization=own, status="SUGGESTED"
    )
    return KnowledgeRelation.objects.create(
        organization=own,
        subject_concept=concept,
        predicate="APPLIES_TO",
        object_concept=target,
        status="SUGGESTED",
    )


@pytest.mark.django_db
@pytest.mark.parametrize("model_name", ["concept", "alias", "evidence", "relation"])
@pytest.mark.parametrize("write_style", ["save", "queryset", "bulk"])
def test_knowledge_organization_is_immutable(organizations, model_name, write_style) -> None:
    own, other = organizations
    instance = _organization_record(model_name, own)

    with pytest.raises(ValidationError, match="ownership|identity"):
        if write_style == "save":
            instance.organization = other
            instance.save()
        elif write_style == "queryset":
            type(instance).objects.filter(id=instance.id).update(organization=other)
        else:
            instance.organization = other
            type(instance).objects.bulk_update([instance], ["organization"])

    instance.refresh_from_db()
    assert instance.organization == own


@pytest.mark.django_db
@pytest.mark.parametrize("write_style", ["save", "queryset", "bulk"])
def test_concept_scope_is_immutable(organizations, write_style) -> None:
    concept = make_concept(code="SCOPE_FIXED", organization=organizations[0], status="SUGGESTED")

    with pytest.raises(ValidationError, match="ownership|identity"):
        if write_style == "save":
            concept.scope = "SYSTEM"
            concept.save()
        elif write_style == "queryset":
            KnowledgeConcept.objects.filter(id=concept.id).update(scope="SYSTEM")
        else:
            concept.scope = "SYSTEM"
            KnowledgeConcept.objects.bulk_update([concept], ["scope"])

    concept.refresh_from_db()
    assert concept.scope == "ORGANIZATION"


@pytest.mark.django_db
def test_rejected_owner_move_preserves_existing_alias_and_evidence_links(organizations) -> None:
    own, other = organizations
    concept = make_concept(code="LINKED_OWNER", organization=own, status="SUGGESTED")
    alias = KnowledgeAlias.objects.create(
        organization=own, concept=concept, language="en", alias="linked owner", status="SUGGESTED"
    )
    evidence = KnowledgeEvidence.objects.create(
        organization=own, evidence_type="HUMAN_ENTRY", excerpt="linked", status="SUGGESTED"
    )
    concept.evidence.add(evidence)
    concept.organization = other

    with pytest.raises(ValidationError, match="ownership"):
        concept.save()

    concept.refresh_from_db()
    assert concept.organization == own
    assert alias.concept == concept
    assert concept.evidence.get() == evidence


@pytest.mark.django_db
@pytest.mark.parametrize("write_style", ["save", "queryset", "bulk"])
@pytest.mark.parametrize("field", ["subject_concept", "object_concept", "predicate"])
def test_relation_graph_identity_is_immutable(organizations, write_style, field) -> None:
    own, _ = organizations
    first = make_concept(code="IDENTITY_FIRST", organization=own, status="SUGGESTED")
    second = make_concept(code="IDENTITY_SECOND", organization=own, status="SUGGESTED")
    replacement = make_concept(code="IDENTITY_REPLACEMENT", organization=own, status="SUGGESTED")
    relation = KnowledgeRelation.objects.create(
        organization=own,
        subject_concept=first,
        predicate="IS_A",
        object_concept=second,
        status="SUGGESTED",
    )
    value = "APPLIES_TO" if field == "predicate" else replacement

    with pytest.raises(ValidationError, match="identity"):
        if write_style == "save":
            setattr(relation, field, value)
            relation.save()
        elif write_style == "queryset":
            KnowledgeRelation.objects.filter(id=relation.id).update(**{field: value})
        else:
            setattr(relation, field, value)
            KnowledgeRelation.objects.bulk_update([relation], [field])


@pytest.mark.django_db
def test_alias_save_update_fields_persists_recomputed_normalization(organizations) -> None:
    concept = make_concept(code="ALIAS_SAVE", organization=organizations[0], status="SUGGESTED")
    alias = KnowledgeAlias.objects.create(
        organization=organizations[0], concept=concept, language="en", alias="old", status="SUGGESTED"
    )
    alias.alias = "  New   TERM  "

    alias.save(update_fields=["alias"])

    alias.refresh_from_db()
    assert alias.alias == "  New   TERM  "
    assert alias.normalized_alias == "new term"


@pytest.mark.django_db
def test_alias_queryset_text_update_is_explicitly_rejected(organizations) -> None:
    concept = make_concept(code="ALIAS_QUERY", organization=organizations[0], status="SUGGESTED")
    alias = KnowledgeAlias.objects.create(
        organization=organizations[0], concept=concept, language="en", alias="old", status="SUGGESTED"
    )

    with pytest.raises(ValidationError, match="alias.*queryset|queryset.*alias"):
        KnowledgeAlias.objects.filter(id=alias.id).update(alias="new term")


@pytest.mark.django_db
def test_alias_queryset_cannot_write_normalized_alias_directly(organizations) -> None:
    concept = make_concept(code="ALIAS_DERIVED", organization=organizations[0], status="SUGGESTED")
    alias = KnowledgeAlias.objects.create(
        organization=organizations[0], concept=concept, language="en", alias="derived", status="SUGGESTED"
    )

    with pytest.raises(ValidationError, match="normalized_alias"):
        KnowledgeAlias.objects.filter(id=alias.id).update(normalized_alias="stale")

    alias.refresh_from_db()
    assert alias.normalized_alias == "derived"


@pytest.mark.django_db
def test_alias_bulk_update_persists_recomputed_normalization(organizations) -> None:
    concept = make_concept(code="ALIAS_BULK", organization=organizations[0], status="SUGGESTED")
    alias = KnowledgeAlias.objects.create(
        organization=organizations[0], concept=concept, language="en", alias="old", status="SUGGESTED"
    )
    alias.alias = "  Bulk   TERM  "

    KnowledgeAlias.objects.bulk_update([alias], ["alias"])

    alias.refresh_from_db()
    assert alias.normalized_alias == "bulk term"


@pytest.mark.django_db
@pytest.mark.parametrize("write_style", ["save", "bulk"])
def test_alias_language_update_recomputes_and_persists_normalization(organizations, write_style) -> None:
    concept = make_concept(code=f"ALIAS_LANGUAGE_{write_style}", organization=organizations[0], status="SUGGESTED")
    alias = KnowledgeAlias.objects.create(
        organization=organizations[0], concept=concept, language="en", alias="Language Term",
        status="SUGGESTED",
    )
    with _test_fixture_writes():
        KnowledgeAlias.objects.filter(id=alias.id).update(normalized_alias="stale")
    alias.refresh_from_db()
    alias.language = "fr"

    if write_style == "save":
        alias.save(update_fields=["language"])
    else:
        KnowledgeAlias.objects.bulk_update([alias], ["language"])

    alias.refresh_from_db()
    assert alias.language == "fr"
    assert alias.normalized_alias == "language term"


@pytest.mark.django_db
def test_direct_relation_create_enforces_predicate_types(organizations) -> None:
    own, _ = organizations
    product = make_concept(code="DIRECT_PRODUCT", organization=own, status="SUGGESTED")
    material = make_concept(
        code="DIRECT_MATERIAL", concept_type="MATERIAL", organization=own, status="SUGGESTED"
    )

    with pytest.raises(RelationRuleError, match="APPLIES_TO"):
        KnowledgeRelation.objects.create(
            organization=own,
            subject_concept=product,
            predicate="APPLIES_TO",
            object_concept=material,
            status="SUGGESTED",
        )


@pytest.mark.django_db
def test_direct_relation_create_rejects_reciprocal_is_a_cycle(organizations) -> None:
    own, _ = organizations
    first = make_concept(code="DIRECT_A", organization=own, status="SUGGESTED")
    second = make_concept(code="DIRECT_B", organization=own, status="SUGGESTED")
    KnowledgeRelation.objects.create(
        organization=own, subject_concept=first, predicate="IS_A", object_concept=second,
        status="SUGGESTED",
    )

    with pytest.raises(RelationCycleError, match="cycle"):
        KnowledgeRelation.objects.create(
            organization=own, subject_concept=second, predicate="IS_A", object_concept=first,
            status="SUGGESTED",
        )


@pytest.mark.django_db
def test_is_a_bulk_create_is_rejected_as_unsafe(organizations) -> None:
    own, _ = organizations
    first = make_concept(code="BULK_A", organization=own, status="SUGGESTED")
    second = make_concept(code="BULK_B", organization=own, status="SUGGESTED")
    relation = KnowledgeRelation(
        organization=own, subject_concept=first, predicate="IS_A", object_concept=second,
        status="SUGGESTED",
    )

    with pytest.raises(ValidationError, match="IS_A.*bulk|bulk.*IS_A"):
        KnowledgeRelation.objects.bulk_create([relation])


@pytest.mark.django_db
def test_longer_path_closure_is_rejected_through_direct_orm(organizations) -> None:
    own, _ = organizations
    concepts = {
        code: make_concept(code=f"LONG_{code}", organization=own, status="SUGGESTED")
        for code in "ABCD"
    }
    for source, target in (("B", "C"), ("D", "A"), ("A", "B")):
        KnowledgeRelation.objects.create(
            organization=own, subject_concept=concepts[source], predicate="IS_A",
            object_concept=concepts[target], status="SUGGESTED",
        )

    with pytest.raises(RelationCycleError) as error:
        KnowledgeRelation.objects.create(
            organization=own, subject_concept=concepts["C"], predicate="IS_A",
            object_concept=concepts["D"], status="SUGGESTED",
        )

    assert error.value.path == ["LONG_C", "LONG_D", "LONG_A", "LONG_B", "LONG_C"]


@pytest.mark.django_db
@pytest.mark.parametrize("write_path", ["direct", "service"])
def test_every_is_a_create_path_reads_the_same_global_lock_row(organizations, write_path) -> None:
    own, _ = organizations
    first = make_concept(code=f"LOCK_{write_path}_A", organization=own, status="SUGGESTED")
    second = make_concept(code=f"LOCK_{write_path}_B", organization=own, status="SUGGESTED")

    with CaptureQueriesContext(connection) as queries, transaction.atomic():
        if write_path == "direct":
            KnowledgeRelation.objects.create(
                organization=own, subject_concept=first, predicate="IS_A", object_concept=second,
                status="SUGGESTED",
            )
        else:
            KnowledgeRelationService(own).create(
                subject=first, predicate="IS_A", object=second, scope="ORGANIZATION"
            )

    lock_queries = [query["sql"] for query in queries if "knowledge_knowledgegraphlock" in query["sql"].lower()]
    assert len(lock_queries) == 1


@pytest.mark.django_db
def test_system_seed_is_a_queryset_write_also_reads_global_lock() -> None:
    first = make_concept(code="LOCK_SEED_A", status="SUGGESTED")
    second = make_concept(code="LOCK_SEED_B", status="SUGGESTED")
    relation = KnowledgeRelation.objects.create(
        organization=None, subject_concept=first, predicate="IS_A", object_concept=second,
        status="SUGGESTED",
    )

    with CaptureQueriesContext(connection) as queries, transaction.atomic(), _system_seed_writes():
        KnowledgeRelation.objects.filter(id=relation.id).update(confidence="0.7500")

    lock_queries = [query["sql"] for query in queries if "knowledge_knowledgegraphlock" in query["sql"].lower()]
    assert len(lock_queries) == 1


@pytest.mark.django_db
def test_graph_lock_singleton_is_migrated_and_seed_is_idempotent() -> None:
    graph_lock = django_apps.get_model("knowledge", "KnowledgeGraphLock")
    assert list(graph_lock.objects.values_list("id", flat=True)) == [1]
    call_command("seed_gear_ontology")
    call_command("seed_gear_ontology")
    assert list(graph_lock.objects.values_list("id", flat=True)) == [1]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("model_name", "field", "value"),
    [
        ("concept", "scope", "ORGANIZATION"),
        ("evidence", "excerpt", "mutated"),
        ("relation", "predicate", "APPLIES_TO"),
    ],
)
@pytest.mark.parametrize("write_style", ["queryset", "bulk"])
def test_system_seed_rejects_unsafe_fields(organizations, model_name, field, value, write_style) -> None:
    first = make_concept(code=f"SEED_{model_name}_A", status="SUGGESTED")
    if model_name == "concept":
        instance = first
    elif model_name == "evidence":
        instance = KnowledgeEvidence.objects.create(
            organization=None, evidence_type="HUMAN_ENTRY", excerpt="original", status="SUGGESTED"
        )
    else:
        second = make_concept(code="SEED_RELATION_B", status="SUGGESTED")
        instance = KnowledgeRelation.objects.create(
            organization=None, subject_concept=first, predicate="IS_A", object_concept=second,
            status="SUGGESTED",
        )

    context = _system_seed_writes()
    with pytest.raises(ValidationError, match="SYSTEM seed"), context:
        if write_style == "queryset":
            type(instance).objects.filter(id=instance.id).update(**{field: value})
        else:
            setattr(instance, field, value)
            type(instance).objects.bulk_update([instance], [field])


@pytest.mark.django_db
def test_system_seed_allows_declared_seed_content_fields() -> None:
    concept = make_concept(code="SEED_SAFE", status="SUGGESTED")
    concept.label_en = "Seed-safe label"

    with _system_seed_writes():
        KnowledgeConcept.objects.bulk_update([concept], ["label_en"])

    concept.refresh_from_db()
    assert concept.label_en == "Seed-safe label"


@pytest.mark.django_db
def test_system_seed_full_save_rejects_unsafe_changed_field() -> None:
    concept = make_concept(code="SEED_FULL_SAVE", status="SUGGESTED")
    concept.code = "SEED_FULL_SAVE_MUTATED"

    with pytest.raises(ValidationError, match="SYSTEM seed"), _system_seed_writes():
        concept.save()


@pytest.mark.django_db
def test_system_seed_queryset_cannot_bypass_alias_normalization() -> None:
    concept = make_concept(code="SEED_ALIAS_QUERY", status="SUGGESTED")
    alias = KnowledgeAlias.objects.create(
        organization=None, concept=concept, language="en", alias="old", status="SUGGESTED"
    )

    with pytest.raises(ValidationError, match="queryset"), _system_seed_writes():
        KnowledgeAlias.objects.filter(id=alias.id).update(alias="new term")

    alias.refresh_from_db()
    assert alias.alias == alias.normalized_alias == "old"
