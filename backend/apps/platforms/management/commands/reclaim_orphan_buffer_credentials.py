from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.platforms.models import EncryptedOAuthCredential, ProviderConnection


MINIMUM_CREDENTIAL_AGE = timedelta(hours=1)


class Command(BaseCommand):
    help = "Reclaim orphaned Buffer API credentials that are no longer referenced."

    def handle(self, *args, **options):
        del args, options
        cutoff = timezone.now() - MINIMUM_CREDENTIAL_AGE
        referenced = set(
            ProviderConnection.objects.filter(
                provider=ProviderConnection.Provider.BUFFER,
            ).values_list("credential_reference", flat=True)
        )
        candidates = EncryptedOAuthCredential.objects.filter(
            platform_code="BUFFER",
            status=EncryptedOAuthCredential.Status.ACTIVE,
            updated_at__lt=cutoff,
        ).exclude(reference__in=referenced)

        reclaimed = 0
        with transaction.atomic():
            for row in candidates.select_for_update():
                if ProviderConnection.objects.filter(
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

        self.stdout.write(f"Reclaimed {reclaimed} orphaned Buffer credentials.")
