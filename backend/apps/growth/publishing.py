import hashlib
import json
from uuid import UUID

from django.db import transaction

from apps.platforms.models import SocialAccount
from integrations.platforms.manual_fake import simulate_publish

from .models import ChannelPackage, GrowthPublishBatch, GrowthPublishItem


class PublishBatchConflict(RuntimeError):
    pass


class PublishPackageSelectionInvalid(RuntimeError):
    pass


def _validate_idempotency_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or not (value := value.strip())
        or len(value) > 128
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise PublishBatchConflict("A valid Idempotency-Key is required.")
    return value


def _normalize_package_ids(values) -> tuple[UUID, ...]:
    try:
        normalized = tuple(sorted({UUID(str(value)) for value in values}, key=str))
    except (TypeError, ValueError, AttributeError) as exc:
        raise PublishPackageSelectionInvalid("Package selection is invalid.") from exc
    if not normalized:
        raise PublishPackageSelectionInvalid("At least one package is required.")
    return normalized


def _request_fingerprint(package_ids: tuple[UUID, ...]) -> str:
    raw = json.dumps([str(value) for value in package_ids], separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _account_for_package(package: ChannelPackage):
    accounts = list(SocialAccount.objects.filter(
        organization=package.organization,
        platform__code=package.channel,
        status=SocialAccount.Status.ACTIVE,
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connector_metadata__fixture="phase-a-e2e",
    ).order_by("id")[:2])
    return accounts[0] if len(accounts) == 1 else None


def _refresh_batch_status(batch: GrowthPublishBatch) -> GrowthPublishBatch:
    statuses = list(batch.items.values_list("status", flat=True))
    if any(status == GrowthPublishItem.Status.RUNNING for status in statuses):
        status = GrowthPublishBatch.Status.RUNNING
    elif any(status == GrowthPublishItem.Status.QUEUED for status in statuses):
        status = GrowthPublishBatch.Status.QUEUED
    else:
        succeeded = statuses.count(GrowthPublishItem.Status.SUCCEEDED)
        failed = statuses.count(GrowthPublishItem.Status.FAILED)
        if succeeded == len(statuses) and statuses:
            status = GrowthPublishBatch.Status.SUCCEEDED
        elif succeeded:
            status = GrowthPublishBatch.Status.PARTIAL_SUCCESS
        elif failed:
            status = GrowthPublishBatch.Status.FAILED
        else:
            status = GrowthPublishBatch.Status.CONFIGURATION_REQUIRED
    if batch.status != status:
        batch.status = status
        batch.save(update_fields=["status", "updated_at"])
    return batch


def _execute_item(item_id) -> None:
    with transaction.atomic():
        item = GrowthPublishItem.objects.select_for_update().select_related(
            "channel_package", "social_account",
        ).get(pk=item_id)
        if item.status not in {GrowthPublishItem.Status.QUEUED, GrowthPublishItem.Status.FAILED}:
            return
        item.status = GrowthPublishItem.Status.RUNNING
        item.attempt_number += 1
        item.last_error = None
        item.save(update_fields=["status", "attempt_number", "last_error", "updated_at"])

        metadata = item.social_account.connector_metadata
        outcome = metadata.get("mock_outcome", "provider_error") if isinstance(metadata, dict) else "provider_error"
        receipt = simulate_publish(
            channel=item.channel,
            payload=item.payload_snapshot,
            item_id=str(item.id),
            attempt_number=item.attempt_number,
            outcome=outcome,
            is_demo=item.channel_package.is_demo,
        )
        if receipt.succeeded:
            item.status = GrowthPublishItem.Status.SUCCEEDED
            item.external_post_id = receipt.external_id
            item.external_post_url = receipt.external_url
        else:
            item.status = GrowthPublishItem.Status.FAILED
            item.last_error = {
                "code": receipt.error_code,
                "message": receipt.error_message,
            }
        item.save(update_fields=[
            "status", "external_post_id", "external_post_url", "last_error", "updated_at",
        ])


def create_publish_batch(
    *, organization, actor, package_ids, idempotency_key: str,
) -> GrowthPublishBatch:
    key = _validate_idempotency_key(idempotency_key)
    normalized_ids = _normalize_package_ids(package_ids)
    fingerprint = _request_fingerprint(normalized_ids)

    with transaction.atomic():
        existing = GrowthPublishBatch.objects.select_for_update().filter(
            organization=organization, idempotency_key=key,
        ).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise PublishBatchConflict("Idempotency-Key already has a different request.")
            return existing

        packages = list(ChannelPackage.objects.select_for_update().filter(
            organization=organization, id__in=normalized_ids,
        ).order_by("channel", "id"))
        if len(packages) != len(normalized_ids):
            raise PublishPackageSelectionInvalid("Package selection is invalid.")

        batch = GrowthPublishBatch.objects.create(
            organization=organization,
            created_by=actor,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            status=GrowthPublishBatch.Status.QUEUED,
            is_demo=all(package.is_demo for package in packages),
        )
        queued_ids = []
        for package in packages:
            account = _account_for_package(package) if package.status == "APPROVED" else None
            if package.status != "APPROVED":
                item_status = GrowthPublishItem.Status.SKIPPED
                last_error = {
                    "code": "CONTENT_NOT_APPROVED",
                    "message": "请先人工批准该渠道内容。",
                }
            elif account is None:
                item_status = GrowthPublishItem.Status.SKIPPED
                last_error = {
                    "code": "ACCOUNT_NOT_CONNECTED",
                    "message": "连接账号后可发布。",
                }
            else:
                item_status = GrowthPublishItem.Status.QUEUED
                last_error = None
            item = GrowthPublishItem.objects.create(
                organization=organization,
                batch=batch,
                channel_package=package,
                social_account=account,
                channel=package.channel,
                payload_snapshot=json.loads(json.dumps(package.payload)),
                status=item_status,
                last_error=last_error,
            )
            if item_status == GrowthPublishItem.Status.QUEUED:
                queued_ids.append(item.id)

    for item_id in queued_ids:
        _execute_item(item_id)
    batch.refresh_from_db()
    return _refresh_batch_status(batch)


def retry_failed_items(*, batch: GrowthPublishBatch, actor) -> GrowthPublishBatch:
    del actor
    failed_ids = list(batch.items.filter(
        status=GrowthPublishItem.Status.FAILED,
    ).values_list("id", flat=True))
    for item_id in failed_ids:
        _execute_item(item_id)
    batch.refresh_from_db()
    return _refresh_batch_status(batch)
