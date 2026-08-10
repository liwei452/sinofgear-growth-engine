import uuid

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.knowledge.models import (
    KnowledgeAlias,
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeGraphLock,
    KnowledgeRelation,
)
from apps.knowledge.guards import _system_seed_writes


CONCEPTS = (
    ("CAPABILITY", "CAP-GEAR-GRINDING", "磨齿能力", "Gear grinding capability"),
    ("CAPABILITY", "CAP-HEAT-TREATMENT", "热处理能力", "Heat treatment capability"),
    ("REQUIREMENT", "REQ-DIN6", "DIN 6 精度要求", "DIN 6 accuracy required"),
    ("REQUIREMENT", "REQ-SMALL-BATCH", "小批量要求", "Small-batch requirement"),
    ("REQUIREMENT", "REQ-URGENT-REPLACEMENT", "紧急替换要求", "Urgent replacement requirement"),
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
    ("PURCHASE_INTENT", "NEED_CUSTOM_MANUFACTURING", "需要定制制造", "Need Custom Manufacturing"),
    ("PURCHASE_INTENT", "NEED_REPLACEMENT_PART", "需要替换零件", "Need Replacement Part"),
)

ALIASES = (
    ("HELICAL_GEAR", "zh", "斜齿轮", "SYNONYM"),
    ("HELICAL_GEAR", "en", "helical gears", "SYNONYM"),
    ("HELICAL_GEAR", "fr", "hélicoïdal gear", "MARKET_TERM"),
)

RELATIONS = (
    ("HELICAL_GEAR", "APPLIES_TO", "AUTOMATED_PACKAGING_LINE"),
    ("HELICAL_GEAR", "COMPLIES_WITH", "DIN"),
)

CAPABILITY_EVIDENCE = (
    ("CAP-GEAR-GRINDING", "Documented gear grinding manufacturing capability."),
    ("CAP-HEAT-TREATMENT", "Documented heat treatment manufacturing capability."),
)


class Command(BaseCommand):
    help = "Seed the bounded approved Gear Manufacturing Ontology."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        KnowledgeGraphLock.objects.update_or_create(
            id=1, defaults={"name": "is_a_graph"}
        )
        with _system_seed_writes():
            self._seed()

    def _seed(self) -> None:
        concepts: dict[str, KnowledgeConcept] = {}
        for concept_type, code, label_zh, label_en in CONCEPTS:
            defaults = {
                "organization": None,
                "label_zh": label_zh,
                "label_en": label_en,
                "description": "",
                "status": KnowledgeConcept.Status.APPROVED,
                "version": 1,
                "suggested_by_ai_run_id": None,
            }
            concept, created = KnowledgeConcept.objects.get_or_create(
                scope=KnowledgeConcept.Scope.SYSTEM,
                concept_type=concept_type,
                code=code,
                defaults=defaults,
            )
            if not created:
                for field, value in defaults.items():
                    if field != "organization":
                        setattr(concept, field, value)
                concept.save(
                    update_fields=[
                        "label_zh", "label_en", "description", "status", "version",
                        "suggested_by_ai_run_id", "updated_at",
                    ]
                )
            concepts[code] = concept
        for capability_code, excerpt in CAPABILITY_EVIDENCE:
            evidence, created = KnowledgeEvidence.objects.get_or_create(
                organization=None,
                source_object_type="seed_gear_ontology",
                source_object_id=uuid.uuid5(uuid.NAMESPACE_URL, f"sinofgear:{capability_code}"),
                defaults={
                    "evidence_type": KnowledgeEvidence.EvidenceType.HUMAN_ENTRY,
                    "excerpt": excerpt,
                    "status": KnowledgeEvidence.Status.APPROVED,
                    "version": 1,
                    "suggested_by_ai_run_id": None,
                },
            )
            if not created:
                evidence.status = KnowledgeEvidence.Status.APPROVED
                evidence.version = 1
                evidence.suggested_by_ai_run_id = None
                evidence.save(
                    update_fields=["status", "version", "suggested_by_ai_run_id", "updated_at"]
                )
            concepts[capability_code].evidence.add(evidence)
        for code, language, alias, alias_type in ALIASES:
            concept = concepts[code]
            defaults = {
                "alias": alias,
                "alias_type": alias_type,
                "status": KnowledgeAlias.Status.APPROVED,
                "version": 1,
                "suggested_by_ai_run_id": None,
            }
            knowledge_alias, created = KnowledgeAlias.objects.get_or_create(
                organization=None,
                language=language,
                normalized_alias=alias.casefold(),
                defaults={"concept": concept, **defaults},
            )
            if not created:
                for field, value in defaults.items():
                    setattr(knowledge_alias, field, value)
                knowledge_alias.save(
                    update_fields=[
                        "alias", "alias_type", "status", "version",
                        "suggested_by_ai_run_id", "updated_at",
                    ]
                )
        for subject_code, predicate, object_code in RELATIONS:
            defaults = {
                "status": KnowledgeRelation.Status.APPROVED,
                "confidence": 1,
                "version": 1,
                "suggested_by_ai_run_id": None,
            }
            relation, created = KnowledgeRelation.objects.get_or_create(
                organization=None,
                subject_concept=concepts[subject_code],
                predicate=predicate,
                object_concept=concepts[object_code],
                defaults=defaults,
            )
            if not created:
                for field, value in defaults.items():
                    setattr(relation, field, value)
                relation.save(
                    update_fields=[
                        "status", "confidence", "version", "suggested_by_ai_run_id", "updated_at",
                    ]
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"Gear ontology seed present: {len(CONCEPTS)} concepts, {len(ALIASES)} aliases, {len(RELATIONS)} relations."
            )
        )
