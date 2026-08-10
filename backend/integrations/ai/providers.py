import json
from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from jsonschema.validators import validator_for


class AIProvider(Protocol):
    def generate(self, *, prompt: str, schema: dict) -> dict: ...


class ProviderRegistry:
    def __init__(self):
        self._providers: dict[str, AIProvider] = {}

    def register(self, code: str, provider: AIProvider, *, replace: bool = False):
        normalized = code.strip().lower()
        if not normalized:
            raise ValueError("Provider code must not be blank.")
        if normalized in self._providers and not replace:
            raise ValueError(f"Provider '{normalized}' is already registered.")
        self._providers[normalized] = provider

    def get(self, code: str) -> AIProvider:
        try:
            return self._providers[code.strip().lower()]
        except KeyError as exc:
            raise ValueError(f"Unknown AI provider '{code}'.") from exc


class FakeAIProvider:
    def generate(self, *, prompt: str, schema: dict) -> dict:
        del schema
        product, country, platform, cta, codes_text = prompt.split("|", 4)
        codes = [item.strip() for item in codes_text.split(",") if item.strip()]
        return {
            "title": f"{product} for {country} on {platform}",
            "body": f"{product} for {country}. Approved concepts: {', '.join(codes)}.",
            "cta": cta,
            "concept_codes": codes,
        }


@dataclass
class _SchemaContext:
    prompt: str
    snapshot: dict
    evaluation: object | None

    @classmethod
    def from_prompt(cls, prompt: str):
        snapshot = {}
        start_marker = "INPUT_JSON_BEGIN"
        end_marker = "INPUT_JSON_END"
        if start_marker in prompt and end_marker in prompt:
            payload = prompt.split(start_marker, 1)[1].split(end_marker, 1)[0].strip()
            try:
                parsed = json.loads(payload)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                snapshot = parsed
        evaluation = None
        evidence = snapshot.get("evidence")
        if isinstance(evidence, list) and evidence and isinstance(evidence[0], dict):
            original_text = evidence[0].get("original_text")
            if isinstance(original_text, str) and original_text.strip():
                from apps.leads.scoring import evaluate_public_signal

                language = (
                    "zh"
                    if any("\u4e00" <= char <= "\u9fff" for char in original_text)
                    else "en"
                )
                evaluation = evaluate_public_signal(original_text, language=language)
        return cls(prompt=prompt, snapshot=snapshot, evaluation=evaluation)

    def candidate_value(self, name: str):
        candidate = self.snapshot.get("candidate")
        return candidate.get(name) if isinstance(candidate, dict) else None

    def evidence_ids(self) -> list[str]:
        evidence = self.snapshot.get("evidence")
        if not isinstance(evidence, list):
            return []
        return [
            str(row["id"])
            for row in evidence
            if isinstance(row, dict) and row.get("id")
        ]

    def original_text(self) -> str:
        evidence = self.snapshot.get("evidence")
        if not isinstance(evidence, list):
            return "Deterministic schema fixture"
        texts = [
            str(row.get("original_text", "")).strip()
            for row in evidence
            if isinstance(row, dict) and str(row.get("original_text", "")).strip()
        ]
        return "\n".join(texts) or "Deterministic schema fixture"

    def requirement_code(self) -> str | None:
        ontology = self.snapshot.get("ontology_snapshot")
        rows = ontology.get("concept_versions") if isinstance(ontology, dict) else None
        if not isinstance(rows, list):
            return None
        return next(
            (
                str(row["code"])
                for row in rows
                if isinstance(row, dict)
                and row.get("concept_type") == "REQUIREMENT"
                and row.get("code")
            ),
            None,
        )

    def capability_binding(self) -> dict:
        rows = self.snapshot.get("capability_bindings")
        if not isinstance(rows, list):
            return {}
        return next((row for row in rows if isinstance(row, dict)), {})


class _SchemaValueBuilder:
    def __init__(self, context: _SchemaContext):
        self.context = context

    def build(self, schema: dict, *, name: str = "value", index: int = 0):
        if "const" in schema:
            return schema["const"]
        if schema.get("enum"):
            return schema["enum"][0]
        if "oneOf" in schema:
            return self.build(schema["oneOf"][0], name=name, index=index)
        if "anyOf" in schema:
            options = [item for item in schema["anyOf"] if item.get("type") != "null"]
            return self.build((options or schema["anyOf"])[0], name=name, index=index)
        value_type = schema.get(
            "type", "object" if "properties" in schema else "string"
        )
        if isinstance(value_type, list):
            value_type = next((item for item in value_type if item != "null"), "null")
        if value_type == "object":
            return {
                key: self.build(value, name=key, index=0)
                for key, value in schema.get("properties", {}).items()
            }
        if value_type == "array":
            reference = self._reference_array(name)
            if reference:
                return reference[: schema.get("maxItems", len(reference))]
            count = max(1, int(schema.get("minItems", 0)))
            maximum = schema.get("maxItems")
            if isinstance(maximum, int):
                count = min(count, maximum)
            return [
                self.build(schema.get("items", {}), name=name, index=item_index)
                for item_index in range(count)
            ]
        if value_type == "integer":
            semantic = self._semantic_number(name, schema=schema)
            if semantic is not None:
                return int(semantic)
            return int(schema.get("minimum", 0))
        if value_type == "number":
            semantic = self._semantic_number(name, schema=schema)
            if semantic is not None:
                return float(semantic)
            return float(schema.get("minimum", 0))
        if value_type == "boolean":
            if name == "insufficient_evidence" and self.context.evaluation is not None:
                return not self.context.evaluation.is_explicit_need
            return False
        if value_type == "null":
            return None
        return self._string(schema, name=name, index=index)

    def _reference_array(self, name: str) -> list[str]:
        if name in {"evidence_ids", "source_evidence_ids"}:
            return self.context.evidence_ids()
        if name == "knowledge_evidence_ids":
            values = self.context.capability_binding().get("knowledge_evidence_ids")
            return [str(value) for value in values] if isinstance(values, list) else []
        return []

    def _semantic_number(self, name: str, *, schema: dict):
        evaluation = self.context.evaluation
        if evaluation is None:
            return None
        if schema.get("maximum") == 1:
            return {
                "intent": evaluation.intent_confidence,
                "company_fit": evaluation.company_match_confidence,
                "capability": evaluation.capability_confidence,
            }.get(name)
        if name in {
            "intent",
            "company_fit",
            "specificity",
            "capability_fit",
            "recency",
        }:
            return getattr(evaluation.dimensions, name)
        return None

    def _string(self, schema: dict, *, name: str, index: int) -> str:
        if name in {"company_name", "company_domain", "country_hint"}:
            value = self.context.candidate_value(name)
            if isinstance(value, str):
                return value
        if name in {"need_summary_zh", "need_summary_en", "text"}:
            return self.context.original_text()
        if name == "type":
            value = self.context.requirement_code()
            if value:
                return value
        if name == "capability_code":
            value = self.context.capability_binding().get("capability_code")
            if value:
                return str(value)
        if schema.get("format") == "uuid" or "[0-9a-fA-F]{8}" in str(
            schema.get("pattern", "")
        ):
            return (
                self.context.evidence_ids()[0]
                if self.context.evidence_ids()
                else str(uuid5(NAMESPACE_URL, f"{self.context.prompt}:{name}:{index}"))
            )
        minimum = int(schema.get("minLength", 0))
        maximum = int(schema.get("maxLength", max(32, minimum)))
        value = (
            ""
            if minimum == 0 and name in {"unit", "company_domain", "country_hint"}
            else f"{name}-{index + 1}"
        )
        if len(value) < minimum:
            value += "x" * (minimum - len(value))
        return value[:maximum]


class SchemaAwareFakeAIProvider:
    """Deterministically materialize valid JSON from a caller-supplied schema.

    The provider has no network, credential, authentication, or persistence
    behavior. Frozen prompt context is used only to preserve values and references
    required by the schema being generated.
    """

    def generate(self, *, prompt: str, schema: dict) -> dict:
        validator_class = validator_for(schema)
        validator_class.check_schema(schema)
        output = _SchemaValueBuilder(_SchemaContext.from_prompt(prompt)).build(schema)
        errors = list(validator_class(schema).iter_errors(output))
        if errors:
            raise ValueError(
                f"Schema fake cannot materialize this schema: {errors[0].message}"
            )
        if not isinstance(output, dict):
            raise ValueError("Schema fake requires an object output schema.")
        return output


provider_registry = ProviderRegistry()
provider_registry.register("fake", FakeAIProvider())
provider_registry.register("schema-fake", SchemaAwareFakeAIProvider())
