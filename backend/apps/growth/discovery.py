import hashlib
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils.module_loading import import_string
from django.utils import timezone

from integrations.sources.base import DiscoveryQuery, SourceAdapterError, governance_for
from integrations.sources.composite import CompositeDiscoverySource
from integrations.sources.contracts_finder import ContractsFinderSource
from integrations.sources.ted import TedSource

from .market_pilots import matched_gear_terms, validate_company_evidence_source
from .models import DiscoveryProfile, DiscoveryRun, IntentSignal, TargetAccount


PUBLIC_PROCUREMENT_SCORE = {
    "icp_fit": 20,
    "intent_strength": 24,
    "recency": 18,
    "role_relevance": 5,
    "evidence_coverage": 18,
    "risk_penalty": 5,
}
PUBLIC_PROCUREMENT_SCORE_TOTAL = (
    sum(PUBLIC_PROCUREMENT_SCORE.values())
    - (2 * PUBLIC_PROCUREMENT_SCORE["risk_penalty"])
)

SOURCE_LABELS = {
    "TED": "TED 欧盟官方采购公告",
    "UK_CONTRACTS_FINDER": "英国 Contracts Finder 官方采购公告",
}
DEMO_SOURCE_LABELS = {
    "TED": "Demo / Fake TED 采购样本",
    "UK_CONTRACTS_FINDER": "Demo / Fake 英国采购样本",
}


class DiscoveryAlreadyRunning(RuntimeError):
    pass


def run_discovery(profile_id, *, trigger, source=None) -> DiscoveryRun:
    profile, run = _start_run(profile_id=profile_id, trigger=trigger)
    query = DiscoveryQuery(
        cpv_codes=tuple(profile.cpv_codes),
        published_from=(timezone.now() - timedelta(days=30)).date(),
        limit=profile.result_limit,
    )
    run.query_snapshot = {
        "cpv_codes": list(query.cpv_codes),
        "published_from": query.published_from.isoformat(),
        "limit": query.limit,
    }
    run.save(update_fields=["query_snapshot", "updated_at"])
    try:
        live_source = source or build_discovery_source()
        batch = live_source.fetch(query)
    except SourceAdapterError as error:
        _record_failure(profile_id=profile.id, run_id=run.id, error_code=error.code)
        raise
    return _ingest_batch(profile_id=profile.id, run_id=run.id, batch=batch)


@transaction.atomic
def _start_run(*, profile_id, trigger):
    profile = DiscoveryProfile.objects.select_for_update().get(pk=profile_id)
    stale_before = timezone.now() - timedelta(minutes=30)
    stale_runs = DiscoveryRun.objects.filter(
        profile=profile,
        status=DiscoveryRun.Status.RUNNING,
        created_at__lt=stale_before,
    )
    stale_runs.update(
        status=DiscoveryRun.Status.FAILED,
        error_code="STALE_RUN_RECOVERED",
        finished_at=timezone.now(),
    )
    if DiscoveryRun.objects.filter(
        profile=profile, status=DiscoveryRun.Status.RUNNING,
    ).exists():
        raise DiscoveryAlreadyRunning("Discovery is already running for this organization.")
    run = DiscoveryRun.objects.create(
        organization=profile.organization,
        profile=profile,
        source_code=profile.source_code,
        trigger=trigger,
        status=DiscoveryRun.Status.RUNNING,
    )
    return profile, run


@transaction.atomic
def _ingest_batch(*, profile_id, run_id, batch) -> DiscoveryRun:
    profile = DiscoveryProfile.objects.select_for_update().get(pk=profile_id)
    run = DiscoveryRun.objects.select_for_update().get(pk=run_id)
    created_accounts = 0
    created_signals = 0
    duplicates = 0
    skipped = batch.skipped_count
    for item in batch.items[: profile.result_limit]:
        content_hash = _item_hash(item)
        if IntentSignal.objects.filter(
            organization=profile.organization, content_hash=content_hash,
        ).exists():
            duplicates += 1
            continue
        source_identity = (
            f"{item.source_code}:{item.buyer_country}:{item.buyer_identifier}"
            if item.buyer_identifier
            else f"{item.source_code}-NOTICE:{item.external_id}"
        )
        account, account_created = TargetAccount.objects.get_or_create(
            organization=profile.organization,
            source_identity=source_identity,
            defaults={
                "name": item.buyer_name,
                "country": item.buyer_country or "Unknown",
                "industry": "Public procurement buyer",
                "is_demo": batch.is_demo,
            },
        )
        created_accounts += int(account_created)
        deadline_text = (
            item.deadline_at.date().isoformat() if item.deadline_at else "not stated"
        )
        cpv_text = ", ".join(item.cpv_codes) or "not stated"
        notice_source = {
            "TED": "TED",
            "UK_CONTRACTS_FINDER": "Contracts Finder",
        }.get(item.source_code, "Official procurement")
        evidence_text = (
            f"{notice_source} notice {item.external_id}: {item.title}. "
            f"CPV {cpv_text}. Tender deadline: {deadline_text}."
        )
        license_contract = (
            "DEMO_FIXTURE"
            if batch.is_demo
            else governance_for(item.source_code)["license_contract"]
        )
        validate_company_evidence_source("TENDER")
        signal = IntentSignal(
            organization=profile.organization,
            account=account,
            signal_type="PUBLIC_PROCUREMENT_NOTICE",
            source_label=_source_label(item.source_code, is_demo=batch.is_demo),
            source_url=item.source_url,
            evidence_text=evidence_text,
            confidence=PUBLIC_PROCUREMENT_SCORE_TOTAL,
            is_demo=batch.is_demo,
            collection_method=(
                "DEMO_FIXTURE" if batch.is_demo else "OFFICIAL_PUBLIC_API"
            ),
            content_hash=content_hash,
            score_breakdown=PUBLIC_PROCUREMENT_SCORE,
            scoring_rule_version="public-procurement-v1",
            uncertainty_notes=[
                "采购方来自公开采购公告，但仍需人工核实供应商资格与采购范围",
                "尚未核实个人联系人，也不会自动联系客户",
            ],
            evidence_envelope={
                "field_value": item.title,
                "source_url": item.source_url,
                "source_excerpt": evidence_text,
                "confidence": PUBLIC_PROCUREMENT_SCORE_TOTAL,
                "observed_at": item.published_at.isoformat(),
                "source_cost_micros": 0,
                "license_contract": license_contract,
                "usage_rights": "INTERNAL_DISCOVERY_WITH_SOURCE_LINK",
                "review_status": "PENDING_REVIEW",
                "queue": "MONITORING",
                "source_type": "TENDER",
                "matched_keywords": matched_gear_terms(item.title),
                "company_match_confidence": PUBLIC_PROCUREMENT_SCORE_TOTAL,
                "ai_exclusion_reasons": [],
            },
        )
        signal.full_clean()
        signal.save()
        created_signals += 1
    now = timezone.now()
    run.status = DiscoveryRun.Status.SUCCEEDED
    run.capability_snapshot = batch.capability_snapshot
    run.fetched_count = len(batch.items)
    run.created_account_count = created_accounts
    run.created_signal_count = created_signals
    run.duplicate_count = duplicates
    run.skipped_count = skipped
    run.finished_at = now
    run.save(update_fields=[
        "status", "capability_snapshot", "fetched_count", "created_account_count",
        "created_signal_count", "duplicate_count", "skipped_count", "finished_at",
        "updated_at",
    ])
    profile.last_succeeded_at = now
    profile.next_run_at = now + timedelta(hours=24)
    profile.consecutive_failures = 0
    profile.last_error_code = ""
    profile.save(update_fields=[
        "last_succeeded_at", "next_run_at", "consecutive_failures",
        "last_error_code", "updated_at",
    ])
    return run


@transaction.atomic
def _record_failure(*, profile_id, run_id, error_code):
    profile = DiscoveryProfile.objects.select_for_update().get(pk=profile_id)
    run = DiscoveryRun.objects.select_for_update().get(pk=run_id)
    now = timezone.now()
    failures = min(profile.consecutive_failures + 1, 10)
    backoff_hours = min(2 ** (failures - 1), 24)
    run.status = DiscoveryRun.Status.FAILED
    run.error_code = error_code
    run.finished_at = now
    run.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
    profile.consecutive_failures = failures
    profile.last_error_code = error_code
    profile.next_run_at = now + timedelta(hours=backoff_hours)
    profile.save(update_fields=[
        "consecutive_failures", "last_error_code", "next_run_at", "updated_at",
    ])


def run_due_discovery_profiles(*, limit=25, source_factory=None):
    now = timezone.now()
    profile_ids = list(
        DiscoveryProfile.objects.filter(enabled=True)
        .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
        .order_by("next_run_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    result = {"scanned": len(profile_ids), "succeeded": 0, "failed": 0, "overlapping": 0}
    for profile_id in profile_ids:
        try:
            source = source_factory() if source_factory else None
            run_discovery(profile_id, trigger=DiscoveryRun.Trigger.SCHEDULED, source=source)
        except DiscoveryAlreadyRunning:
            result["overlapping"] += 1
        except SourceAdapterError:
            result["failed"] += 1
        else:
            result["succeeded"] += 1
    return result


def build_discovery_source():
    factory_path = settings.GROWTH_DISCOVERY_SOURCE_FACTORY
    if factory_path:
        return import_string(factory_path)()
    return CompositeDiscoverySource((
        TedSource(
            timeout_seconds=settings.TED_DISCOVERY_TIMEOUT_SECONDS,
            max_response_bytes=settings.TED_DISCOVERY_MAX_RESPONSE_BYTES,
        ),
        ContractsFinderSource(
            timeout_seconds=settings.CONTRACTS_FINDER_DISCOVERY_TIMEOUT_SECONDS,
            max_response_bytes=settings.CONTRACTS_FINDER_DISCOVERY_MAX_RESPONSE_BYTES,
        ),
    ))


def _item_hash(item) -> str:
    canonical = "\n".join((
        item.source_code, item.external_id, item.source_url, item.title.strip(),
    ))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_label(source_code: str, *, is_demo: bool) -> str:
    labels = DEMO_SOURCE_LABELS if is_demo else SOURCE_LABELS
    return labels.get(
        source_code,
        "Demo / Fake 采购样本" if is_demo else "官方公开采购公告",
    )
