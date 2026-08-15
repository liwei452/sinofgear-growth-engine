from datetime import datetime, timezone as dt_timezone

import pytest
from django.utils import timezone

from apps.growth.discovery import DiscoveryAlreadyRunning, run_discovery
from apps.growth.models import DiscoveryProfile, DiscoveryRun, IntentSignal, TargetAccount
from apps.identity.models import Organization
from integrations.sources.base import SourceAdapterError, SourceBatch, SourceItem


class FakeSource:
    def __init__(self, batch=None, error=None):
        self.batch = batch
        self.error = error

    def fetch(self, query):
        if self.error:
            raise self.error
        return self.batch


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Discovery service", slug="discovery-service")


@pytest.fixture
def profile(organization):
    return DiscoveryProfile.objects.create(organization=organization, result_limit=10)


@pytest.fixture
def source_batch():
    return SourceBatch(
        items=(SourceItem(
            external_id="534032-2026",
            buyer_name="Example Contracting Authority",
            buyer_country="DEU",
            title="Industrial gears and transmission parts",
            published_at=datetime(2026, 8, 3, tzinfo=dt_timezone.utc),
            deadline_at=datetime(2026, 9, 8, tzinfo=dt_timezone.utc),
            source_url="https://ted.europa.eu/en/notice/-/detail/534032-2026",
            cpv_codes=("42141300", "42142000"),
        ),),
        capability_snapshot={
            "source": "TED", "capture_method": "OFFICIAL_PUBLIC_API",
            "authentication": "ANONYMOUS", "result_limit": 10,
        },
        total_count=1,
    )


def test_official_notice_creates_a_target_account_and_intent_signal(profile, source_batch):
    run = run_discovery(profile.id, trigger="MANUAL", source=FakeSource(source_batch))

    account = TargetAccount.objects.get(organization=profile.organization)
    signal = IntentSignal.objects.get(organization=profile.organization)
    profile.refresh_from_db()
    assert account.name == "Example Contracting Authority"
    assert account.country == "DEU"
    assert account.is_demo is False
    assert signal.account == account
    assert signal.collection_method == "OFFICIAL_PUBLIC_API"
    assert signal.source_label == "TED 欧盟官方采购公告"
    assert signal.source_url.endswith("534032-2026")
    assert signal.is_demo is False
    assert signal.confidence == 80
    assert signal.scoring_rule_version == "ted-procurement-v1"
    assert signal.score_breakdown == {
        "icp_fit": 20,
        "intent_strength": 24,
        "recency": 18,
        "role_relevance": 5,
        "evidence_coverage": 18,
        "risk_penalty": 5,
    }
    assert "534032-2026" in signal.evidence_text
    assert run.status == DiscoveryRun.Status.SUCCEEDED
    assert run.created_account_count == 1
    assert run.created_signal_count == 1
    assert profile.last_succeeded_at is not None
    assert profile.next_run_at > timezone.now()


def test_repeat_notice_is_idempotent(profile, source_batch):
    first = run_discovery(profile.id, trigger="MANUAL", source=FakeSource(source_batch))
    second = run_discovery(profile.id, trigger="MANUAL", source=FakeSource(source_batch))

    assert first.created_signal_count == 1
    assert second.created_signal_count == 0
    assert second.duplicate_count == 1
    assert TargetAccount.objects.filter(organization=profile.organization).count() == 1
    assert IntentSignal.objects.filter(organization=profile.organization).count() == 1


def test_source_failure_is_recorded_safely_and_backed_off(profile):
    with pytest.raises(SourceAdapterError, match="SOURCE_RATE_LIMITED"):
        run_discovery(
            profile.id,
            trigger="MANUAL",
            source=FakeSource(error=SourceAdapterError("SOURCE_RATE_LIMITED")),
        )

    run = DiscoveryRun.objects.get(profile=profile)
    profile.refresh_from_db()
    assert run.status == DiscoveryRun.Status.FAILED
    assert run.error_code == "SOURCE_RATE_LIMITED"
    assert run.finished_at is not None
    assert profile.consecutive_failures == 1
    assert profile.last_error_code == "SOURCE_RATE_LIMITED"
    assert profile.next_run_at > timezone.now()
    assert TargetAccount.objects.count() == 0
    assert IntentSignal.objects.count() == 0


def test_active_run_prevents_overlapping_discovery(profile, source_batch):
    DiscoveryRun.objects.create(
        organization=profile.organization,
        profile=profile,
        source_code="TED",
        trigger="SCHEDULED",
        status=DiscoveryRun.Status.RUNNING,
    )

    with pytest.raises(DiscoveryAlreadyRunning):
        run_discovery(profile.id, trigger="MANUAL", source=FakeSource(source_batch))

