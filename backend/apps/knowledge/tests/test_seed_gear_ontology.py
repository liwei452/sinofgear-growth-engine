import pytest
from django.core.management import call_command

from apps.knowledge.models import KnowledgeAlias, KnowledgeConcept, KnowledgeRelation


EXPECTED_CODES = {
    "SPUR_GEAR", "HELICAL_GEAR", "BEVEL_GEAR", "WORM_GEAR", "GEAR_SHAFT",
    "MODULE", "TOOTH_COUNT", "PRESSURE_ANGLE", "ACCURACY_GRADE",
    "20CRMNTI", "42CRMO", "STAINLESS_STEEL", "NYLON",
    "HOBBING", "SHAPING", "GRINDING", "CARBURIZING", "QUENCHING", "HEAT_TREATMENT",
    "DIN", "ISO", "AGMA",
    "PACKAGING_MACHINERY", "AGRICULTURAL_MACHINERY", "ROBOTICS", "FOOD_MACHINERY", "AUTOMATION_EQUIPMENT",
    "AUTOMATED_PACKAGING_LINE", "CONVEYOR_DRIVE", "ROBOT_JOINT", "AGRICULTURAL_GEARBOX",
    "OEM", "EQUIPMENT_MANUFACTURER", "REPAIR_COMPANY", "DISTRIBUTOR",
    "NEED_SUPPLIER", "NEED_QUOTATION", "NEED_CUSTOM_MANUFACTURING", "NEED_REPLACEMENT_PART",
}


@pytest.mark.django_db
def test_seed_is_idempotent_exact_and_preserves_organization_knowledge(organizations) -> None:
    own, _ = organizations
    KnowledgeConcept.objects.create(
        scope="ORGANIZATION", organization=own, concept_type="PRODUCT_TYPE", code="PRIVATE_GEAR",
        label_zh="企业齿轮", label_en="Private Gear", status="SUGGESTED",
    )

    call_command("seed_gear_ontology")
    first_counts = (
        KnowledgeConcept.objects.filter(scope="SYSTEM").count(),
        KnowledgeAlias.objects.filter(organization__isnull=True).count(),
        KnowledgeRelation.objects.filter(organization__isnull=True).count(),
    )
    first_links = set(KnowledgeRelation.objects.values_list("subject_concept__code", "predicate", "object_concept__code"))
    call_command("seed_gear_ontology")

    assert set(KnowledgeConcept.objects.filter(scope="SYSTEM").values_list("code", flat=True)) == EXPECTED_CODES
    assert first_counts == (
        KnowledgeConcept.objects.filter(scope="SYSTEM").count(),
        KnowledgeAlias.objects.filter(organization__isnull=True).count(),
        KnowledgeRelation.objects.filter(organization__isnull=True).count(),
    )
    assert first_links == set(KnowledgeRelation.objects.values_list("subject_concept__code", "predicate", "object_concept__code"))
    assert ("HELICAL_GEAR", "APPLIES_TO", "AUTOMATED_PACKAGING_LINE") in first_links
    assert ("HELICAL_GEAR", "COMPLIES_WITH", "DIN") in first_links
    assert KnowledgeConcept.objects.get(code="PRIVATE_GEAR").organization == own
    assert not KnowledgeConcept.objects.filter(scope="SYSTEM").exclude(status="APPROVED", version=1).exists()


@pytest.mark.django_db
def test_seed_includes_the_specified_helical_gear_aliases() -> None:
    call_command("seed_gear_ontology")

    aliases = set(KnowledgeAlias.objects.filter(concept__code="HELICAL_GEAR").values_list("alias", flat=True))

    assert {"斜齿轮", "helical gears", "hélicoïdal gear"} <= aliases
