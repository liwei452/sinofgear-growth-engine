import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.sources.models import (
    IngestionBatch,
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
)
from apps.sources.services import normalize_source_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.COM:443", "https://example.com/"),
        ("http://BÜCHER.example:80/a?b=2&a=1#frag", "http://xn--bcher-kva.example/a?b=2&a=1"),
        ("https://example.com:8443/path#frag", "https://example.com:8443/path"),
    ],
)
def test_normalize_source_url_is_canonical_and_idempotent(raw, expected):
    normalized = normalize_source_url(raw)
    assert normalized == expected
    assert normalize_source_url(normalized) == expected


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "https://user:secret@example.com/path",
        "https:///missing-host",
        "not a url",
    ],
)
def test_normalize_source_url_rejects_unsupported_or_unsafe_urls(url):
    with pytest.raises(ValidationError):
        normalize_source_url(url)


@pytest.mark.django_db
def test_monitoring_target_requires_locator_and_normalizes_url(organization, user):
    invalid = MonitoringTarget(
        organization=organization,
        target_type=MonitoringTarget.TargetType.KEYWORD,
        collection_mode=MonitoringTarget.CollectionMode.PASTE,
        platform="MANUAL",
        label="Missing locator",
        created_by=user,
    )
    with pytest.raises(ValidationError):
        invalid.full_clean()

    target = MonitoringTarget.objects.create(
        organization=organization,
        target_type=MonitoringTarget.TargetType.ACCOUNT,
        collection_mode=MonitoringTarget.CollectionMode.OFFICIAL_API,
        platform="LINKEDIN",
        normalized_url="HTTPS://Example.COM:443/company/gears#about",
        label="Public company page",
        created_by=user,
    )
    assert target.normalized_url == "https://example.com/company/gears"


@pytest.mark.django_db
def test_source_content_conditional_unique_constraints(organization, user):
    base = dict(
        organization=organization,
        platform="MANUAL",
        canonical_url="https://example.com/post/1",
        content_hash="b" * 64,
        created_by=user,
    )
    SourceContent.objects.create(external_id="external-1", **base)
    with pytest.raises(IntegrityError), transaction.atomic():
        SourceContent.objects.create(
            external_id="external-1",
            canonical_url="https://example.com/post/changed",
            content_hash="c" * 64,
            **{key: value for key, value in base.items() if key not in {"canonical_url", "content_hash"}},
        )

    SourceContent.objects.create(external_id="", **{**base, "canonical_url": "https://example.com/post/2"})
    with pytest.raises(IntegrityError), transaction.atomic():
        SourceContent.objects.create(external_id="", **{**base, "canonical_url": "https://example.com/post/2"})
    distinct_url = SourceContent.objects.create(
        external_id="", **{**base, "canonical_url": "https://example.com/post/3"}
    )
    assert distinct_url.external_id == ""


@pytest.mark.django_db
def test_source_queryset_writes_cannot_bypass_url_or_organization_validation(
    content, other_organization
):
    SourceContent.objects.filter(pk=content.pk).update(
        canonical_url="HTTPS://Example.COM:443/updated#fragment"
    )
    content.refresh_from_db()
    assert content.canonical_url == "https://example.com/updated"

    with pytest.raises(ValidationError):
        SourceContent.objects.filter(pk=content.pk).update(organization=other_organization)


@pytest.mark.django_db
def test_ingestion_batch_never_persists_credentials_or_raw_headers(organization):
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.API,
        idempotency_key="sanitized-reference",
        input_reference={
            "public_source_id": "page-42",
            "credential": "private",
            "cookie": "session=private",
            "raw_headers": {"X-Internal": "private"},
            "nested": {"Authorization": "Bearer private", "page": 2},
        },
    )
    assert batch.input_reference == {
        "public_source_id": "page-42",
        "nested": {"page": 2},
    }


def test_domain_enums_match_the_approved_contract():
    assert set(MonitoringTarget.CollectionMode.values) == {
        "MANUAL_URL", "SCREENSHOT", "FILE_IMPORT", "PASTE", "OFFICIAL_API"
    }
    assert set(IngestionBatch.SourceType.values) == {
        "API", "URL", "SCREENSHOT", "CSV", "JSON", "PASTE"
    }
    assert set(IngestionBatch.Status.values) == {
        "QUEUED", "RUNNING", "PARTIAL_SUCCESS", "SUCCEEDED", "FAILED", "CANCELLED"
    }
    assert set(SourceSignal.SignalType.values) == {
        "COMMENT", "POST_AUTHOR", "CHANNEL_OWNER", "PROFILE_MATCH", "MENTION", "HASHTAG_MATCH"
    }
    assert set(SourceEvidence.RetentionClass.values) == {
        "TRANSIENT_30D", "CONFIRMED", "HANDOFF_PROTECTED"
    }
