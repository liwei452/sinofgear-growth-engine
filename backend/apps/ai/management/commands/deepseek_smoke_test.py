from __future__ import annotations

import platform
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ai.deepseek_smoke import run_audited_deepseek_smoke
from apps.ai.models import AIProviderConfiguration
from apps.identity.models import Organization
from integrations.ai.deepseek import DeepSeekProvider
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


def _execute_checks(*, organization, credential_store, include_content_generation):
    provider = DeepSeekProvider(credential_store=credential_store)
    checks = [('Return exactly {"connected": true}.', _CONNECTION_SCHEMA, "connection")]
    if include_content_generation:
        checks.append(
            (
                "Write one short industrial gear manufacturing test message.",
                _GENERATION_SCHEMA,
                "content-generation",
            )
        )
    return [
        run_audited_deepseek_smoke(
            organization=organization,
            provider=provider,
            prompt=prompt,
            schema=schema,
            check_code=check_code,
        )
        for prompt, schema, check_code in checks
    ]


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
        del configuration
        outcomes = _execute_checks(
            organization=organization,
            credential_store=credential_store,
            include_content_generation=options.get("include_content_generation"),
        )
        del credential_store
        for outcome in outcomes:
            if not outcome.passed:
                raise CommandError(outcome.error_code or "deepseek smoke test failed") from None
            self._write_outcome(outcome)

    def _write_outcome(self, outcome):
        self.stdout.write(
            " ".join(
                [
                    "PASS",
                    f"run_id={outcome.run_id}",
                    f"model={outcome.model}",
                    f"thinking={str(outcome.thinking_enabled).lower()}",
                    f"input_tokens={outcome.input_tokens}",
                    f"output_tokens={outcome.output_tokens}",
                    f"cache_hit_tokens={outcome.cache_hit_tokens}",
                    f"estimated_cost_usd={outcome.estimated_cost_usd}",
                ]
            )
        )
