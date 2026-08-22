from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.common.tenant_tasks import (
    TenantTaskError,
    resolve_control_plane_organization_ids,
    tenant_task_context,
)
from apps.platforms.models import EncryptedOAuthCredential
from integrations.platforms.encrypted_token_store import EncryptedDatabaseTokenStore
from integrations.platforms.secret_resolver import EnvironmentSecretResolver


class Command(BaseCommand):
    help = "Rotate encrypted social OAuth credential envelopes in bounded batches."

    def add_arguments(self, parser):
        parser.add_argument("--from-version", required=True)
        parser.add_argument("--to-version", required=True)
        parser.add_argument("--new-key-reference", required=True)
        parser.add_argument("--organization")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        del args
        old_reference = settings.SOCIAL_OAUTH_TOKEN_KEY_REFERENCE
        if not old_reference:
            raise CommandError("Social credential rotation is not configured.")
        resolver = EnvironmentSecretResolver()
        old_store = EncryptedDatabaseTokenStore(
            secret_resolver=resolver,
            key_reference=old_reference,
            key_version=options["from_version"],
            clock=timezone.now,
        )
        new_store = EncryptedDatabaseTokenStore(
            secret_resolver=resolver,
            key_reference=options["new_key_reference"],
            key_version=options["to_version"],
            clock=timezone.now,
        )
        try:
            organization_ids = resolve_control_plane_organization_ids(
                options.get("organization")
            )
        except TenantTaskError as error:
            raise CommandError(str(error)) from error

        eligible = 0
        rotated = 0
        try:
            for organization_id in organization_ids:
                with tenant_task_context(str(organization_id)):
                    queryset = EncryptedOAuthCredential.objects.filter(
                        organization_id=organization_id,
                        status=EncryptedOAuthCredential.Status.ACTIVE,
                        key_version=options["from_version"],
                    )
                    if options["dry_run"]:
                        eligible += queryset.count()
                        continue
                    while True:
                        ids = list(
                            queryset.order_by("id").values_list("id", flat=True)[:100]
                        )
                        if not ids:
                            break
                        for row_id in ids:
                            with transaction.atomic():
                                row = EncryptedOAuthCredential.objects.select_for_update().get(
                                    id=row_id,
                                    organization_id=organization_id,
                                    status=EncryptedOAuthCredential.Status.ACTIVE,
                                    key_version=options["from_version"],
                                )
                                payload = old_store._decrypt_row(row)
                                row.key_version = options["to_version"]
                                new_store._encrypt_row(row, payload)
                                row.save(
                                    update_fields=[
                                        "key_version", "nonce", "ciphertext", "updated_at",
                                    ]
                                )
                            rotated += 1
        except Exception as error:
            raise CommandError("Social credential rotation failed.") from error
        self.stdout.write(
            f"eligible={eligible} rotated={rotated} "
            f"dry_run={'true' if options['dry_run'] else 'false'}"
        )
