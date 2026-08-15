from jsonschema import Draft202012Validator, FormatChecker


CONTENT_GENERATION_INPUT_SCHEMA_VERSION = "1.0"

UUID = {"type": "string", "format": "uuid"}
STRING = {"type": "string"}
NON_EMPTY_STRING = {"type": "string", "minLength": 1}
VERSION = {"type": "integer", "minimum": 1}
STRING_LIST = {"type": "array", "items": STRING}


def object_schema(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


PRODUCT_CONCEPT_VERSION_SCHEMA = object_schema(
    {
        "link_id": UUID,
        "link_version": VERSION,
        "role": NON_EMPTY_STRING,
        "concept_id": UUID,
        "concept_code": NON_EMPTY_STRING,
        "concept_type": NON_EMPTY_STRING,
        "concept_version": VERSION,
    },
    ["link_id", "link_version", "role", "concept_id", "concept_code", "concept_type", "concept_version"],
)

PRODUCT_SCHEMA = object_schema(
    {
        "product_id": UUID,
        "product_version": VERSION,
        "name_zh": STRING,
        "name_en": STRING,
        "module_min": {"type": "string"},
        "module_max": {"type": "string"},
        "tooth_count_min": {"type": "integer"},
        "tooth_count_max": {"type": "integer"},
        "pressure_angle": {"type": "string"},
        "accuracy_grade": STRING,
        "heat_treatment": STRING,
        "surface_treatment": STRING,
        "manufacturing_capabilities": STRING_LIST,
        "inspection_capabilities": STRING_LIST,
        "moq": {"type": "integer", "minimum": 0},
        "lead_time": STRING,
        "landing_page_url": STRING,
        "status": NON_EMPTY_STRING,
        "concept_versions": {"type": "array", "items": PRODUCT_CONCEPT_VERSION_SCHEMA},
    },
    [
        "product_id", "product_version", "name_zh", "name_en", "module_min", "module_max",
        "tooth_count_min", "tooth_count_max", "pressure_angle", "accuracy_grade",
        "heat_treatment", "surface_treatment", "manufacturing_capabilities",
        "inspection_capabilities", "moq", "lead_time", "landing_page_url", "status",
        "concept_versions",
    ],
)

ASSET_SCHEMA = object_schema(
    {
        "asset_id": UUID,
        "checksum": NON_EMPTY_STRING,
        "mime_type": NON_EMPTY_STRING,
        "asset_type": NON_EMPTY_STRING,
        "language": STRING,
        "tags": STRING_LIST,
        "product_ids": {"type": "array", "items": UUID},
    },
    ["asset_id", "checksum", "mime_type", "asset_type", "language", "tags", "product_ids"],
)

PLATFORM_SCHEMA = object_schema(
    {
        "platform_id": UUID,
        "code": NON_EMPTY_STRING,
        "name": NON_EMPTY_STRING,
        "capability_codes": STRING_LIST,
    },
    ["platform_id", "code", "name", "capability_codes"],
)

VERIFIED_PRODUCT_FACT_SCHEMA = object_schema(
    {
        "fact_id": UUID,
        "product_id": UUID,
        "field_name": NON_EMPTY_STRING,
        "value": NON_EMPTY_STRING,
        "category": NON_EMPTY_STRING,
        "source_asset_id": UUID,
        "source_filename": NON_EMPTY_STRING,
        "source_page": {"type": ["integer", "null"], "minimum": 1},
        "source_excerpt": NON_EMPTY_STRING,
        "is_demo": {"type": "boolean"},
    },
    ["fact_id", "product_id", "field_name", "value", "category", "source_asset_id", "source_filename", "source_page", "source_excerpt", "is_demo"],
)

CONCEPT_VERSION_SCHEMA = object_schema(
    {
        "concept_id": UUID,
        "code": NON_EMPTY_STRING,
        "concept_type": NON_EMPTY_STRING,
        "label_zh": STRING,
        "label_en": STRING,
        "version": VERSION,
        "status": {"const": "APPROVED"},
    },
    ["concept_id", "code", "concept_type", "label_zh", "label_en", "version", "status"],
)

RELATION_VERSION_SCHEMA = object_schema(
    {
        "relation_id": UUID,
        "subject_concept_id": UUID,
        "predicate": NON_EMPTY_STRING,
        "object_concept_id": UUID,
        "version": VERSION,
        "status": {"const": "APPROVED"},
    },
    ["relation_id", "subject_concept_id", "predicate", "object_concept_id", "version", "status"],
)

EVIDENCE_REFERENCE_SCHEMA = object_schema(
    {
        "evidence_id": UUID,
        "evidence_type": NON_EMPTY_STRING,
        "source_object_type": STRING,
        "source_object_id": {"oneOf": [UUID, {"type": "null"}]},
        "source_url": {"type": ["string", "null"]},
        "excerpt": STRING,
        "captured_at": {"oneOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]},
        "version": VERSION,
        "status": {"const": "APPROVED"},
    },
    [
        "evidence_id", "evidence_type", "source_object_type", "source_object_id",
        "source_url", "excerpt", "captured_at", "version", "status",
    ],
)

ONTOLOGY_SNAPSHOT_SCHEMA = object_schema(
    {
        "organization_id": UUID,
        "concept_versions": {"type": "array", "items": CONCEPT_VERSION_SCHEMA},
        "relation_versions": {"type": "array", "items": RELATION_VERSION_SCHEMA},
        "evidence_references": {"type": "array", "items": EVIDENCE_REFERENCE_SCHEMA},
        "generated_at": {"type": "string", "format": "date-time"},
    },
    ["organization_id", "concept_versions", "relation_versions", "evidence_references", "generated_at"],
)

CONTENT_GENERATION_INPUT_SCHEMA = object_schema(
    {
        "schema_version": {"const": CONTENT_GENERATION_INPUT_SCHEMA_VERSION},
        "organization_id": UUID,
        "brief_id": UUID,
        "brief_version": VERSION,
        "campaign_id": UUID,
        "campaign_version": VERSION,
        "products": {"type": "array", "items": PRODUCT_SCHEMA, "minItems": 1},
        "assets": {"type": "array", "items": ASSET_SCHEMA},
        "target_country": NON_EMPTY_STRING,
        "customer_type": NON_EMPTY_STRING,
        "content_objective": NON_EMPTY_STRING,
        "cta": NON_EMPTY_STRING,
        "landing_page_url": NON_EMPTY_STRING,
        "language": NON_EMPTY_STRING,
        "keywords": STRING_LIST,
        "prohibited_claims": STRING_LIST,
        "selling_points": STRING_LIST,
        "advantages": STRING_LIST,
        "target_platforms": {"type": "array", "items": PLATFORM_SCHEMA, "minItems": 1},
        "ontology_snapshot": ONTOLOGY_SNAPSHOT_SCHEMA,
        "verified_product_facts": {"type": "array", "items": VERIFIED_PRODUCT_FACT_SCHEMA},
        "generated_at": {"type": "string", "format": "date-time"},
    },
    [
        "schema_version", "organization_id", "brief_id", "brief_version", "campaign_id",
        "campaign_version", "products", "assets", "target_country", "customer_type",
        "content_objective", "cta", "landing_page_url", "language", "keywords",
        "prohibited_claims", "selling_points", "advantages", "target_platforms",
        "ontology_snapshot", "generated_at",
    ],
)

CONTENT_GENERATION_INPUT_VALIDATOR = Draft202012Validator(
    CONTENT_GENERATION_INPUT_SCHEMA, format_checker=FormatChecker()
)


def generation_input_errors(value) -> list:
    return sorted(
        CONTENT_GENERATION_INPUT_VALIDATOR.iter_errors(value),
        key=lambda error: [str(item) for item in error.absolute_path],
    )
