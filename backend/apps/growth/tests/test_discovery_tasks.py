from datetime import timedelta

import pytest
from django.utils import timezone

from apps.growth.discovery import run_due_discovery_profiles
from apps.growth.models import DiscoveryProfile
from apps.identity.models import Organization
from integrations.sources.base import SourceBatch


class EmptySource:
    def fetch(self, query):
        return SourceBatch(
            items=(),
            capability_snapshot={
                "source": "TED", "capture_method": "OFFICIAL_PUBLIC_API",
                "authentication": "ANONYMOUS", "result_limit": query.limit,
            },
        )


@pytest.mark.django_db
def test_due_runner_only_executes_enabled_profiles_that_are_due():
    due_org = Organization.objects.create(name="Due", slug="due-discovery")
    future_org = Organization.objects.create(name="Future", slug="future-discovery")
    disabled_org = Organization.objects.create(name="Disabled", slug="disabled-discovery")
    due = DiscoveryProfile.objects.create(
        organization=due_org, next_run_at=timezone.now() - timedelta(minutes=1),
    )
    future = DiscoveryProfile.objects.create(
        organization=future_org, next_run_at=timezone.now() + timedelta(hours=1),
    )
    disabled = DiscoveryProfile.objects.create(
        organization=disabled_org,
        enabled=False,
        next_run_at=timezone.now() - timedelta(minutes=1),
    )

    result = run_due_discovery_profiles(source_factory=EmptySource)

    due.refresh_from_db()
    future.refresh_from_db()
    disabled.refresh_from_db()
    assert result == {"scanned": 1, "succeeded": 1, "failed": 0, "overlapping": 0}
    assert due.runs.count() == 1
    assert future.runs.count() == 0
    assert disabled.runs.count() == 0
