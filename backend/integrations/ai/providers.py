import json
from typing import Protocol


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
        base_prompt, separator, facts_text = prompt.partition("||FACTS:")
        product, country, platform, cta, codes_text = base_prompt.split("|", 4)
        codes = [item.strip() for item in codes_text.split(",") if item.strip()]
        facts = json.loads(facts_text) if separator else []
        verified = "" if not facts else " Verified facts: " + "; ".join(
            f"{item['field_name']}={item['value']}" for item in facts
        ) + "."
        return {
            "title": f"{product} for {country} on {platform}",
            "body": f"{product} for {country}. Approved concepts: {', '.join(codes)}.{verified}",
            "cta": cta,
            "concept_codes": codes,
        }


provider_registry = ProviderRegistry()
provider_registry.register("fake", FakeAIProvider())
