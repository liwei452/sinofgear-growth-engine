from __future__ import annotations

import platform
from dataclasses import dataclass
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ai.budget import calculate_actual_cost
from apps.ai.models import AIProviderConfiguration
from apps.identity.models import Organization
from integrations.ai.deepseek import DeepSeekProvider
from integrations.ai.providers import ProviderCallError
from integrations.credentials import (
    CredentialStoreUnavailableError,
    get_credential_store,
)


_CONNECTION_SCHEMA = {
    "type": "object",
    "required": ["connected"],
    "properties": {"connected": {"type": "boolean", "const": True}},
    "additionalProperties": False,
}
_GENERATION_SCHEMA = {
    "type": "object",
    "required": ["title", "body"],
    "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 80},
        "body": {"type": "string", "minLength": 1, "maxLength": 240},
    },
    "additionalProperties": False,
}


@dataclass(frozen=True)
class _SmokeExecution:
    organization_id: object
    model: str = "deepseek-v4-flash"
    thinking_enabled: bool = False
    max_output_tokens: int = 64
    timeout_seconds: int = 30


class Command(BaseCommand):
    help = "Run an explicitly acknowledged paid DeepSeek connection smoke test."

    def add_arguments(self, parser):
        parser.add_argument("--organization-slug", required=False)
        parser.add_argument("--acknowledge-paid-call", action="store_true")
        parser.add_argument("--include-content-generation", action="store_true")

    def handle(self, *args, **options):
        del args
        if not options["acknowledge_paid_call"]:
            raise CommandError(
                "Refusing a paid request without --acknowledge-paid-call."
            )
        organization_slug = options.get("organization_slug")
        if not organization_slug:
            raise CommandError("Provide exactly one --organization-slug.")
        if getattr(settings, "PHASE_B1_SCHEMA_FAKE_ALLOWED", False):
            raise CommandError("Refusing paid smoke test while fake provider mode is enabled.")
        if (
            str(getattr(settings, "AI_CREDENTIAL_STORE", "windows")).lower()
            != "windows"
            or platform.system() != "Windows"
        ):
            raise CommandError("DeepSeek smoke test requires Windows Credential Manager.")
        try:
            organization = Organization.objects.get(slug=organization_slug)
        except Organization.DoesNotExist:
            raise CommandError("The explicit organization was not found.") from None
        try:
            configuration = AIProviderConfiguration.objects.get(
                organization=organization,
                provider_code="deepseek",
                connection_state=AIProviderConfiguration.ConnectionState.CONNECTED,
                operation_token__isnull=True,
                operation_started_at__isnull=True,
            )
        except AIProviderConfiguration.DoesNotExist:
            raise CommandError(
                "DeepSeek requires a stable CONNECTED configuration for this organization."
            ) from None
        try:
            credential_store = get_credential_store()
        except CredentialStoreUnavailableError:
            raise CommandError("DeepSeek requires Windows Credential Manager.") from None
        provider = DeepSeekProvider(credential_store=credential_store)
        execution = _SmokeExecution(
            organization_id=organization.id,
            timeout_seconds=configuration.timeout_seconds,
        )
        checks = [
            (
                'Return exactly {"connected": true}.',
                _CONNECTION_SCHEMA,
            )
        ]
        if options.get("include_content_generation"):
            checks.append(
                (
                    "Write one short industrial gear manufacturing test message.",
                    _GENERATION_SCHEMA,
                )
            )
        for prompt, schema in checks:
            self._run_check(provider, prompt=prompt, schema=schema, execution=execution)

    def _run_check(self, provider, *, prompt, schema, execution):
        run_id = uuid4()
        try:
            result = provider.generate(prompt=prompt, schema=schema, execution=execution)
            metadata = result.metadata if isinstance(result.metadata, dict) else {}
            usage = {
                "input_tokens": self._safe_token(metadata.get("input_tokens")),
                "output_tokens": self._safe_token(metadata.get("output_tokens")),
                "cache_hit_tokens": self._safe_token(metadata.get("cache_hit_tokens")),
            }
            cost = calculate_actual_cost(model=execution.model, metadata=usage)
        except (ProviderCallError, ValueError):
            raise CommandError("deepseek smoke test failed") from None
        self.stdout.write(
            " ".join(
                [
                    "PASS",
                    f"run_id={run_id}",
                    f"model={execution.model}",
                    "thinking=false",
                    f"input_tokens={usage['input_tokens']}",
                    f"output_tokens={usage['output_tokens']}",
                    f"cache_hit_tokens={usage['cache_hit_tokens']}",
                    f"estimated_cost_usd={cost}",
                ]
            )
        )

    @staticmethod
    def _safe_token(value) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
