from datetime import timedelta

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.growth.discovery import build_discovery_source
from apps.growth.models import DiscoveryProfile
from apps.identity.models import Organization
from integrations.sources.base import SourceBatch
from integrations.sources.composite import CompositeDiscoverySource


class EmptySource:
    def fetch(self, query):
        assert connection.in_atomic_block is False
        return SourceBatch(
            items=(),
            capability_snapshot={
                "source": "TED", "capture_method": "OFFICIAL_PUBLIC_API",
                "authentication": "ANONYMOUS", "result_limit": query.limit,
            },
        )


@override_settings(
    GROWTH_DISCOVERY_SOURCE_FACTORY=(
        "apps.growth.tests.test_discovery_tasks.EmptySource"
    )
)
@pytest.mark.django_db(transaction=True)
def test_due_runner_only_executes_enabled_profiles_that_are_due():
    from apps.growth.tasks import scan_due_discovery_profiles

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

    result = scan_due_discovery_profiles.run(limit=25)

    due.refresh_from_db()
    future.refresh_from_db()
    disabled.refresh_from_db()
    assert result == {"scanned": 1, "succeeded": 1, "failed": 0, "overlapping": 0}
    assert due.runs.count() == 1
    assert future.runs.count() == 0
    assert disabled.runs.count() == 0


@override_settings(
    GROWTH_DISCOVERY_SOURCE_FACTORY="apps.growth.e2e_sources.E2EDiscoverySource",
)
def test_configured_fixture_source_is_explicitly_demo_labeled():
    source = build_discovery_source()
    batch = source.fetch(type("Query", (), {"limit": 20})())

    assert batch.is_demo is True
    assert batch.capability_snapshot["source"] == "TED_E2E_FIXTURE"


@override_settings(
    GROWTH_DISCOVERY_SOURCE_FACTORY="",
    TED_DISCOVERY_TIMEOUT_SECONDS=7,
    TED_DISCOVERY_MAX_RESPONSE_BYTES=500_000,
    CONTRACTS_FINDER_DISCOVERY_TIMEOUT_SECONDS=8,
    CONTRACTS_FINDER_DISCOVERY_MAX_RESPONSE_BYTES=600_000,
)
def test_default_discovery_source_combines_bounded_official_sources():
    source = build_discovery_source()

    assert isinstance(source, CompositeDiscoverySource)
    assert [item.source_code for item in source.sources] == [
        "TED", "UK_CONTRACTS_FINDER",
    ]
    assert source.sources[0].timeout_seconds == 7
    assert source.sources[0].max_response_bytes == 500_000
    assert source.sources[1].timeout_seconds == 8
    assert source.sources[1].max_response_bytes == 600_000
