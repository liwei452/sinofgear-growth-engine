import json
from copy import deepcopy

import pytest
from django.test import override_settings
from jsonschema.validators import validator_for

from apps.leads.schemas import LEAD_ANALYSIS_OUTPUT_SCHEMA, lead_analysis_errors
from integrations.ai.providers import SchemaAwareFakeAIProvider, provider_registry


EVIDENCE_ID = "30000000-0000-4000-8000-000000000001"
KNOWLEDGE_ID = "30000000-0000-4000-8000-000000000002"


def test_schema_fake_is_unreachable_without_an_explicit_safety_gate():
    with pytest.raises(ValueError, match="Unknown AI provider 'schema-fake'"):
        provider_registry.get("schema-fake")


@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_schema_fake_is_reachable_with_an_explicit_safety_gate():
    assert isinstance(provider_registry.get("schema-fake"), SchemaAwareFakeAIProvider)


@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_schema_fake_is_deterministic_for_a_supported_nested_schema():
    schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "minLength": 3, "maxLength": 12},
            "quantity": {"type": "integer", "minimum": 2, "maximum": 8},
            "ratio": {"type": "number", "minimum": 0.25, "maximum": 0.75},
            "enabled": {"type": "boolean"},
            "tags": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 2,
            },
            "metadata": {
                "type": "object",
                "properties": {"note": {"type": "string", "minLength": 1}},
                "required": ["note"],
                "additionalProperties": False,
            },
        },
        "required": ["label", "quantity", "ratio", "enabled", "tags", "metadata"],
        "additionalProperties": False,
    }
    provider = SchemaAwareFakeAIProvider()

    first = provider.generate(prompt="A generic deterministic fixture", schema=schema)
    second = provider.generate(prompt="A generic deterministic fixture", schema=schema)

    assert first == second
    validator = validator_for(schema)(schema)
    assert list(validator.iter_errors(first)) == []
    assert (
        provider_registry.get("schema-fake").generate(
            prompt="A generic deterministic fixture", schema=schema
        )
        == first
    )


@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_schema_fake_extracts_actual_fields_from_explicit_frozen_evidence():
    snapshot = {
        "candidate": {
            "company_name": "Fixture Packaging GmbH",
            "company_domain": "fixture-packaging.example",
            "country_hint": "DE",
        },
        "evidence": [
            {
                "id": EVIDENCE_ID,
                "original_text": "We need 200 replacement helical gears for a packaging machine, DIN 6 if possible.",
            }
        ],
        "ontology_snapshot": {
            "concept_versions": [
                {"concept_type": "REQUIREMENT", "code": "REQ-DIN6"},
                {"concept_type": "CAPABILITY", "code": "CAP-GEAR-GRINDING"},
            ]
        },
        "capability_bindings": [
            {
                "capability_code": "CAP-GEAR-GRINDING",
                "knowledge_evidence_ids": [KNOWLEDGE_ID],
            }
        ],
    }
    prompt = f"INPUT_JSON_BEGIN\n{json.dumps(snapshot)}\nINPUT_JSON_END"

    output = SchemaAwareFakeAIProvider().generate(
        prompt=prompt,
        schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
    )

    assert lead_analysis_errors(output, snapshot=snapshot) == []
    assert output["company_name"] == "Fixture Packaging GmbH"
    assert output["reasons"][0]["evidence_ids"] == [EVIDENCE_ID]
    assert output["requirements"] == [
        {
            "type": "REQ-DIN6",
            "value": "DIN 6",
            "unit": "",
            "evidence_ids": [EVIDENCE_ID],
        }
    ]
    assert output["capability_matches"] == []


@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_schema_fake_does_not_invent_requirements_for_ordinary_engagement():
    snapshot = {
        "candidate": {
            "company_name": "Fixture Packaging GmbH",
            "company_domain": "fixture-packaging.example",
            "country_hint": "DE",
        },
        "evidence": [
            {
                "id": EVIDENCE_ID,
                "original_text": "Thanks for sharing this explanation of involute gear geometry.",
            }
        ],
        "ontology_snapshot": {
            "concept_versions": [
                {"concept_type": "REQUIREMENT", "code": "REQ-DIN6"},
                {"concept_type": "CAPABILITY", "code": "CAP-GEAR-GRINDING"},
            ]
        },
        "capability_bindings": [
            {
                "capability_code": "CAP-GEAR-GRINDING",
                "knowledge_evidence_ids": [KNOWLEDGE_ID],
            }
        ],
    }
    prompt = f"INPUT_JSON_BEGIN\n{json.dumps(snapshot)}\nINPUT_JSON_END"

    output = provider_registry.get("schema-fake").generate(
        prompt=prompt,
        schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
    )

    assert lead_analysis_errors(output, snapshot=snapshot) == []
    assert output["insufficient_evidence"] is True
    assert output["requirements"] == []
    assert output["capability_matches"] == []
    assert output["need_summary_en"] == snapshot["evidence"][0]["original_text"]

    invented = deepcopy(output)
    invented["requirements"] = [
        {
            "type": "REQ-DIN6",
            "value": "DIN 6",
            "unit": "",
            "evidence_ids": [EVIDENCE_ID],
        }
    ]
    invented["capability_matches"] = [
        {
            "capability_code": "CAP-GEAR-GRINDING",
            "knowledge_evidence_ids": [KNOWLEDGE_ID],
            "source_evidence_ids": [EVIDENCE_ID],
        }
    ]

    errors = lead_analysis_errors(invented, snapshot=snapshot)
    assert any("requirements.0.value" in error for error in errors)
    assert any("capability_matches.0.capability_code" in error for error in errors)
