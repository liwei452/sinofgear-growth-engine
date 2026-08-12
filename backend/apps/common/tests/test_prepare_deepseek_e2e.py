import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.ai.models import AIProviderConfiguration, PromptVersion
from apps.identity.models import Organization
from integrations.credentials import credential_target, get_credential_store
from apps.ai.services import PromptVersionService


@pytest.mark.django_db
def test_prepare_deepseek_e2e_fails_closed_without_owned_gate():
    with override_settings(
        DEEPSEEK_E2E_FAKE_ALLOWED=False,
        DEEPSEEK_E2E_GATE="",
        PHASE_A_E2E_OWNERSHIP_SECRET="",
        PHASE_A_E2E_RUN_ID="",
    ):
        with pytest.raises(CommandError):
            call_command("prepare_deepseek_e2e")


@pytest.mark.django_db
def test_prepare_deepseek_e2e_switches_only_published_generation_prompts():
    organization = Organization.objects.create(name="Owned", slug="owned")
    published = PromptVersionService.create(
        purpose="CONTENT_GENERATE", code="e2e-published", provider="fake",
        model="fake-v1", template="x", output_schema={"type": "object"},
        status=PromptVersion.Status.PUBLISHED,
    )
    draft = PromptVersionService.create(
        purpose="CONTENT_GENERATE", code="e2e-draft", provider="fake",
        model="fake-v1", template="x", output_schema={"type": "object"},
        status=PromptVersion.Status.DRAFT,
    )
    gate = "a" * 64
    with override_settings(
        DEEPSEEK_E2E_FAKE_ALLOWED=True, DEEPSEEK_E2E_GATE=gate,
        PHASE_A_E2E_OWNERSHIP_SECRET=gate, PHASE_A_E2E_RUN_ID="owned-run",
    ):
        call_command("prepare_deepseek_e2e")
    published.refresh_from_db()
    draft.refresh_from_db()
    assert (published.provider, published.model) == ("deepseek", "deepseek-v4-flash")
    assert (draft.provider, draft.model) == ("fake", "fake-v1")
    configuration = AIProviderConfiguration.objects.get(organization=organization)
    assert configuration.connection_state == AIProviderConfiguration.ConnectionState.CONNECTED
    assert get_credential_store().read(credential_target(organization.id)) == "".join(
        ("s", "k-", "valid-placeholder")
    )
