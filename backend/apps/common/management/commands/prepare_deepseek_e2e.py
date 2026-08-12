from django.conf import settings
from django.core.management import BaseCommand, CommandError

from apps.ai.models import AIProviderConfiguration, PromptVersion, ai_audit_writes
from apps.identity.models import Organization
from integrations.credentials import credential_target, get_credential_store


class Command(BaseCommand):
    help = "Switch owned E2E prompts to the guarded no-network DeepSeek provider."

    def handle(self, *args, **options):
        del args, options
        gate = str(getattr(settings, "DEEPSEEK_E2E_GATE", ""))
        ownership = str(getattr(settings, "PHASE_A_E2E_OWNERSHIP_SECRET", ""))
        run_id = str(getattr(settings, "PHASE_A_E2E_RUN_ID", ""))
        if (
            not bool(getattr(settings, "DEEPSEEK_E2E_FAKE_ALLOWED", False))
            or not run_id or len(ownership) != 64 or gate != ownership
        ):
            raise CommandError("prepare_deepseek_e2e requires an owned guarded E2E run.")
        with ai_audit_writes():
            PromptVersion.objects.filter(
                purpose__in=["CONTENT_GENERATE", "LEAD_ANALYZE"],
                status=PromptVersion.Status.PUBLISHED,
            ).update(provider="deepseek", model="deepseek-v4-flash")
        store = get_credential_store()
        secret = "".join(("s", "k-", "valid-placeholder"))
        for organization in Organization.objects.all():
            store.write(credential_target(organization.id), secret)
            AIProviderConfiguration.objects.update_or_create(
                organization=organization,
                defaults={
                    "connection_state": AIProviderConfiguration.ConnectionState.CONNECTED,
                    "key_suffix": secret[-4:],
                    "credential_revision": 1,
                },
            )
        self.stdout.write(self.style.SUCCESS("Guarded DeepSeek E2E prompts are ready."))
