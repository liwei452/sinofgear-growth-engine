import pytest
from django.core.management import call_command

from apps.knowledge.models import KnowledgeAlias, KnowledgeConcept, KnowledgeRelation


EXPECTED_CONCEPTS = {
    ("PRODUCT_TYPE", "SPUR_GEAR", "直齿轮", "Spur Gear"),
    ("PRODUCT_TYPE", "HELICAL_GEAR", "斜齿轮", "Helical Gear"),
    ("PRODUCT_TYPE", "BEVEL_GEAR", "锥齿轮", "Bevel Gear"),
    ("PRODUCT_TYPE", "WORM_GEAR", "蜗轮", "Worm Gear"),
    ("PRODUCT_TYPE", "GEAR_SHAFT", "齿轮轴", "Gear Shaft"),
    ("PARAMETER", "MODULE", "模数", "Module"),
    ("PARAMETER", "TOOTH_COUNT", "齿数", "Tooth Count"),
    ("PARAMETER", "PRESSURE_ANGLE", "压力角", "Pressure Angle"),
    ("PARAMETER", "ACCURACY_GRADE", "精度等级", "Accuracy Grade"),
    ("MATERIAL", "20CRMNTI", "20CrMnTi", "20CrMnTi"),
    ("MATERIAL", "42CRMO", "42CrMo", "42CrMo"),
    ("MATERIAL", "STAINLESS_STEEL", "不锈钢", "Stainless Steel"),
    ("MATERIAL", "NYLON", "尼龙", "Nylon"),
    ("PROCESS", "HOBBING", "滚齿", "Hobbing"),
    ("PROCESS", "SHAPING", "插齿", "Shaping"),
    ("PROCESS", "GRINDING", "磨齿", "Grinding"),
    ("PROCESS", "CARBURIZING", "渗碳", "Carburizing"),
    ("PROCESS", "QUENCHING", "淬火", "Quenching"),
    ("PROCESS", "HEAT_TREATMENT", "热处理", "Heat Treatment"),
    ("STANDARD", "DIN", "德国工业标准", "DIN"),
    ("STANDARD", "ISO", "国际标准化组织标准", "ISO"),
    ("STANDARD", "AGMA", "美国齿轮制造商协会标准", "AGMA"),
    ("INDUSTRY", "PACKAGING_MACHINERY", "包装机械", "Packaging Machinery"),
    ("INDUSTRY", "AGRICULTURAL_MACHINERY", "农业机械", "Agricultural Machinery"),
    ("INDUSTRY", "ROBOTICS", "机器人", "Robotics"),
    ("INDUSTRY", "FOOD_MACHINERY", "食品机械", "Food Machinery"),
    ("INDUSTRY", "AUTOMATION_EQUIPMENT", "自动化设备", "Automation Equipment"),
    ("APPLICATION", "AUTOMATED_PACKAGING_LINE", "自动包装线", "Automated Packaging Line"),
    ("APPLICATION", "CONVEYOR_DRIVE", "输送机驱动", "Conveyor Drive"),
    ("APPLICATION", "ROBOT_JOINT", "机器人关节", "Robot Joint"),
    ("APPLICATION", "AGRICULTURAL_GEARBOX", "农业齿轮箱", "Agricultural Gearbox"),
    ("CUSTOMER_TYPE", "OEM", "原始设备制造商", "OEM"),
    ("CUSTOMER_TYPE", "EQUIPMENT_MANUFACTURER", "设备制造商", "Equipment Manufacturer"),
    ("CUSTOMER_TYPE", "REPAIR_COMPANY", "维修公司", "Repair Company"),
    ("CUSTOMER_TYPE", "DISTRIBUTOR", "经销商", "Distributor"),
    ("PURCHASE_INTENT", "NEED_SUPPLIER", "寻找供应商", "Need Supplier"),
    ("PURCHASE_INTENT", "NEED_QUOTATION", "需要报价", "Need Quotation"),
    (
        "PURCHASE_INTENT",
        "NEED_CUSTOM_MANUFACTURING",
        "需要定制制造",
        "Need Custom Manufacturing",
    ),
    ("PURCHASE_INTENT", "NEED_REPLACEMENT_PART", "需要替换零件", "Need Replacement Part"),
}

EXPECTED_ALIASES = {
    ("HELICAL_GEAR", "zh", "斜齿轮", "SYNONYM"),
    ("HELICAL_GEAR", "en", "helical gears", "SYNONYM"),
    ("HELICAL_GEAR", "fr", "hélicoïdal gear", "MARKET_TERM"),
}

EXPECTED_RELATIONS = {
    ("HELICAL_GEAR", "APPLIES_TO", "AUTOMATED_PACKAGING_LINE"),
    ("HELICAL_GEAR", "COMPLIES_WITH", "DIN"),
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
    first_links = set(
        KnowledgeRelation.objects.filter(organization__isnull=True).values_list(
            "subject_concept__code", "predicate", "object_concept__code"
        )
    )
    call_command("seed_gear_ontology")

    assert set(
        KnowledgeConcept.objects.filter(scope="SYSTEM").values_list(
            "concept_type", "code", "label_zh", "label_en"
        )
    ) == EXPECTED_CONCEPTS
    assert set(
        KnowledgeAlias.objects.filter(organization__isnull=True).values_list(
            "concept__code", "language", "alias", "alias_type"
        )
    ) == EXPECTED_ALIASES
    assert first_counts == (
        KnowledgeConcept.objects.filter(scope="SYSTEM").count(),
        KnowledgeAlias.objects.filter(organization__isnull=True).count(),
        KnowledgeRelation.objects.filter(organization__isnull=True).count(),
    )
    assert first_links == set(
        KnowledgeRelation.objects.filter(organization__isnull=True).values_list(
            "subject_concept__code", "predicate", "object_concept__code"
        )
    ) == EXPECTED_RELATIONS
    assert KnowledgeConcept.objects.get(code="PRIVATE_GEAR").organization == own
    assert not KnowledgeConcept.objects.filter(scope="SYSTEM").exclude(status="APPROVED", version=1).exists()


@pytest.mark.django_db
def test_seed_includes_the_specified_helical_gear_aliases() -> None:
    call_command("seed_gear_ontology")

    aliases = set(KnowledgeAlias.objects.filter(concept__code="HELICAL_GEAR").values_list("alias", flat=True))

    assert {"斜齿轮", "helical gears", "hélicoïdal gear"} <= aliases
