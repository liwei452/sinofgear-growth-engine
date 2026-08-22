from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from apps.common.tenant_tasks import (
    TenantTaskError,
    resolve_control_plane_organization_ids,
    tenant_task_context,
)
from apps.platforms.models import EncryptedOAuthCredential, ProviderConnection


MINIMUM_CREDENTIAL_AGE = timedelta(hours=1)


class Command(BaseCommand):
    help = "Reclaim orphaned Buffer API credentials that are no longer referenced."

    def add_arguments(self, parser):
        parser.add_argument("--organization")

    def handle(self, *args, **options):
        del args
        cutoff = timezone.now() - MINIMUM_CREDENTIAL_AGE
        try:
            organization_ids = resolve_control_plane_organization_ids(
                options.get("organization")
            )
        except TenantTaskError as error:
            raise CommandError(str(error)) from error

        reclaimed = 0
        for organization_id in organization_ids:
            with tenant_task_context(str(organization_id)):
                reclaimed += self._reclaim_organization(organization_id, cutoff)

        self.stdout.write(f"Reclaimed {reclaimed} orphaned Buffer credentials.")

    @staticmethod
    def _reclaim_organization(organization_id, cutoff):
        referenced = set(
            ProviderConnection.objects.filter(
                organization_id=organization_id,
                provider=ProviderConnection.Provider.BUFFER,
            ).values_list("credential_reference", flat=True)
        )
        candidates = EncryptedOAuthCredential.objects.filter(
            organization_id=organization_id,
            platform_code="BUFFER",
            status=EncryptedOAuthCredential.Status.ACTIVE,
            updated_at__lt=cutoff,
        ).exclude(reference__in=referenced)

        reclaimed = 0
        with transaction.atomic():
            for row in candidates.select_for_update():
                if ProviderConnection.objects.filter(
                    organization_id=organization_id,
                    provider=ProviderConnection.Provider.BUFFER,
                    credential_reference=row.reference,
                ).exists():
                    continue
                row.status = EncryptedOAuthCredential.Status.DISCONNECTED
                row.ciphertext = b""
                row.nonce = b""
                row.disconnected_at = timezone.now()
                row.save(update_fields=[
                    "status", "ciphertext", "nonce", "disconnected_at", "updated_at",
                ])
                reclaimed += 1
        return reclaimed
