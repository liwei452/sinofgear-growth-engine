from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from apps.common.rls_manifest import (
    RLS_MANIFEST,
    RLSManifestError,
    RLSPhase,
    assert_rls_coverage,
)


class Command(BaseCommand):
    help = "Validate that every managed concrete business table has one RLS classification."

    def handle(self, *args, **options) -> None:
        del args, options
        try:
            assert_rls_coverage()
        except RLSManifestError as error:
            raise CommandError(f"RLS coverage audit failed:\n{error}") from error

        phase_counts = Counter(entry.phase for entry in RLS_MANIFEST)
        summary = " ".join(f"{phase.value}={phase_counts[phase]}" for phase in RLSPhase)
        self.stdout.write(
            self.style.SUCCESS(
                f"RLS coverage manifest valid: tables={len(RLS_MANIFEST)} {summary}"
            )
        )
