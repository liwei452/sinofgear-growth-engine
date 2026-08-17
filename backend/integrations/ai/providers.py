import json
import os
import re
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema.exceptions import SchemaError as JSONSchemaError
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
        if "options" in schema.get("properties", {}):
            _, separator, input_text = prompt.partition("||INPUT:")
            if not separator:
                raise RuntimeError("Fake recommendation input is unavailable.")
            snapshot = json.loads(input_text)
            product = snapshot["products"][0]
            fact_ids = [row["id"] for row in snapshot["facts"][:3]]
            markets = snapshot["markets"]
            channels = snapshot["channels"][:1]
            languages = snapshot["languages"]
            return {"options": [
                {
                    "product_id": product["id"],
                    "market_code": market["code"],
                    "language": languages[index % len(languages)],
                    "customer_profile": f"Verified industrial buyer {index + 1}",
                    "channel_codes": channels,
                    "theme": f"Verified product direction {index + 1}",
                    "rationale": "Explicit Fake/offline recommendation using verified fixture facts.",
                    "fact_ids": fact_ids,
                    "missing_information": [],
                }
                for index, market in enumerate((markets * 3)[:3])
            ]}
        base_prompt, input_separator, input_text = prompt.partition("||INPUT:")
        if input_separator:
            snapshot = json.loads(input_text)
            products = snapshot.get("products") or []
            product = (products[0].get("name_en") or products[0].get("name_zh")) if products else "Product"
            country = snapshot.get("target_country", "")
            cta = snapshot.get("cta", "")
            codes = sorted({
                item.get("code")
                for item in snapshot.get("ontology_snapshot", {}).get("concept_versions", [])
                if item.get("status") == "APPROVED" and item.get("code")
            })
            facts = snapshot.get("verified_product_facts") or []
            if schema.get("properties", {}).get("schema_version", {}).get("const") == 2:
                fact_ids = [str(item["fact_id"]) for item in facts]
                language = snapshot["language"]
                variants = []
                for index, platform in enumerate(snapshot["target_platforms"], start=1):
                    code = platform["code"]
                    variant = {
                        "platform_code": code,
                        "language": language,
                        "title": f"[{language}] {product} · {code}",
                        "body": f"[{language}] Fake offline {code} adaptation {index} for {country}.",
                        "cta": f"[{language}] {cta}",
                        "landing_page_url": snapshot["landing_page_url"],
                        "hashtags": [f"#{code.title()}", "#IndustrialGears"],
                        "evidence_fact_ids": fact_ids,
                    }
                    if code == "TIKTOK":
                        variant.update({
                            "duration_seconds": 30,
                            "aspect_ratio": "9:16",
                            "script": f"[{language}] Fake offline TikTok script.",
                            "shot_list": [{
                                "scene": "1",
                                "visual": "Verified product inspection close-up",
                                "on_screen_text": f"[{language}] Verified process",
                            }],
                            "voiceover": f"[{language}] Fake offline voiceover.",
                            "voiceover_language": language,
                            "subtitles": f"[{language}] Fake offline subtitles.",
                            "subtitle_language": language,
                        })
                    variants.append(variant)
                return {
                    "schema_version": 2,
                    "language": language,
                    "title": f"[{language}] {product} for {country}",
                    "body": f"[{language}] Fake offline master content for {country}.",
                    "cta": f"[{language}] {cta}",
                    "landing_page_url": snapshot["landing_page_url"],
                    "concept_codes": codes,
                    "evidence_fact_ids": fact_ids,
                    "platform_variants": variants,
                }
            platform = snapshot.get("target_platforms", [{}])[0].get("code", "")
        else:
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


class DeepSeekAIProvider:
    endpoint = "https://api.deepseek.com/chat/completions"
    max_response_bytes = 1_000_000

    def __init__(
        self, *, opener=urlopen, timeout_seconds: int = 30,
        max_attempts: int = 2, sleeper=time.sleep,
    ):
        self._opener = opener
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max(1, min(max_attempts, 2))
        self._sleeper = sleeper
        self.last_usage = None

    def generate(self, *, prompt: str, schema: dict) -> dict:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("DeepSeek API key is not configured.")
        model = os.environ.get("PRODUCT_AI_MODEL", "deepseek-chat").strip() or "deepseek-chat"
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", model):
            raise RuntimeError("DeepSeek model configuration is invalid.")
        schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": (
                    "Return one JSON object matching the supplied JSON schema. "
                    "Use only facts present in the user input. Never invent certifications, "
                    "performance, customers, prices, lead times, or capacity."
                )},
                {"role": "user", "content": f"JSON schema: {schema_text}\nInput: {prompt}"},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
            "max_tokens": 2_000,
        }, ensure_ascii=False).encode("utf-8")
        request = Request(self.endpoint, data=payload, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, method="POST")
        raw = None
        started = time.monotonic()
        for attempt in range(self._max_attempts):
            try:
                with self._opener(request, timeout=self._timeout_seconds) as response:
                    raw = response.read(self.max_response_bytes + 1)
                break
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt + 1 >= self._max_attempts:
                    raise RuntimeError("DeepSeek request failed.") from exc
            except (URLError, TimeoutError) as exc:
                if attempt + 1 >= self._max_attempts:
                    raise RuntimeError("DeepSeek request failed.") from exc
            self._sleeper(0.25)
        if raw is None:
            raise RuntimeError("DeepSeek request failed.")
        if len(raw) > self.max_response_bytes:
            raise RuntimeError("DeepSeek response exceeded the size limit.")
        try:
            envelope = json.loads(raw.decode("utf-8"))
            content = envelope["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("DeepSeek returned an invalid JSON response.") from exc
        usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
        first_choice = envelope.get("choices", [{}])[0] if isinstance(envelope.get("choices"), list) else {}
        self.last_usage = {
            "model": envelope.get("model"),
            "request_id": envelope.get("id"),
            "finish_reason": first_choice.get("finish_reason"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "latency_seconds": round(time.monotonic() - started, 3),
        }
        if not isinstance(result, dict):
            raise RuntimeError("DeepSeek returned an invalid JSON response.")
        try:
            validator_class = validator_for(schema)
            validator_class.check_schema(schema)
            validator_class(schema).validate(result)
        except (JSONSchemaValidationError, JSONSchemaError, ValueError, TypeError) as exc:
            raise RuntimeError("DeepSeek response did not match the required schema.") from exc
        return result


provider_registry = ProviderRegistry()
provider_registry.register("fake", FakeAIProvider())
provider_registry.register("deepseek", DeepSeekAIProvider())
