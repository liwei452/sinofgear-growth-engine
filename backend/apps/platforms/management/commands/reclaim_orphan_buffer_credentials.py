from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.platforms.models import EncryptedOAuthCredential, ProviderConnection


class Command(BaseCommand):
    help = "Reclaim orphaned Buffer API credentials that are no longer referenced."

    def handle(self, *args, **options):
        del args, options
        referenced = set(
            ProviderConnection.objects.filter(
                provider=ProviderConnection.Provider.BUFFER,
            ).values_list("credential_reference", flat=True)
        )
        orphans = EncryptedOAuthCredential.objects.filter(
            platform_code="BUFFER",
            status=EncryptedOAuthCredential.Status.ACTIVE,
        ).exclude(reference__in=referenced)

        reclaimed = 0
        for row in orphans:
            row.status = EncryptedOAuthCredential.Status.DISCONNECTED
            row.ciphertext = b""
            row.nonce = b""
            row.disconnected_at = timezone.now()
            row.save(update_fields=[
                "status", "ciphertext", "nonce", "disconnected_at", "updated_at",
            ])
            reclaimed += 1

        self.stdout.write(f"Reclaimed {reclaimed} orphaned Buffer credentials.")
