import hashlib
import json
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.platforms.models import SocialAccount
from apps.publishing.models import PublishedPost, PublishTask
from apps.publishing.services import PublishingConflict, create_publish_task
from integrations.platforms.base import ConnectorConfigurationRequired, OfficialPublishRequest
from integrations.platforms.registry import ConnectorRegistry
from integrations.platforms.runtime import get_social_provider_runtime

from .models import ChannelPackage, GrowthPublishBatch, GrowthPublishItem


class PublishBatchConflict(RuntimeError):
    pass


class PublishPackageSelectionInvalid(RuntimeError):
    pass


def delegate_channel_package_to_publish_task(
    *,
    package: ChannelPackage,
    account: SocialAccount,
    actor,
    scheduled_at=None,
):
    if package.status != "APPROVED":
        raise PublishBatchConflict("Package must be approved before publishing.")
    content = package.source_platform_content
    if content is None:
        raise PublishBatchConflict("Package has no source platform content.")
    return create_publish_task(
        content=content,
        account=account,
        idempotency_key=f"batch-delegated:{package.id}",
        actor=actor,
        scheduled_at=scheduled_at,
    )


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
        publish_mode__in=[
            SocialAccount.PublishMode.API_AUTO,
            SocialAccount.PublishMode.API_CONFIRM,
        ],
    ).select_related("credential", "platform").order_by("id")[:2])
    return accounts[0] if len(accounts) == 1 else None


def get_connector_registry() -> ConnectorRegistry:
    return get_social_provider_runtime().connector_registry


def _preflight_error(account: SocialAccount, package: ChannelPackage) -> dict | None:
    metadata = account.connector_metadata if isinstance(account.connector_metadata, dict) else {}
    connection_kind = metadata.get("connection_kind")
    if not connection_kind and metadata.get("fixture") == "phase-a-e2e":
        connection_kind = "demo_fake"
    if connection_kind == "demo_fake":
        return {
            "code": "DEMO_ONLY_NO_EXTERNAL_PUBLISH",
            "message": "Demo/Fake connectors cannot create formal external posts.",
            "retryable": False,
            "retry_after_seconds": None,
        }
    if connection_kind != "official_oauth":
        return {
            "code": "CONFIGURATION_REQUIRED",
            "message": "请先通过官方授权连接平台账号。",
            "retryable": False,
            "retry_after_seconds": None,
        }
    if package.is_demo:
        return {
            "code": "CONNECTOR_MODE_MISMATCH",
            "message": "Demo / Fake 内容不能通过真实平台连接器发布。",
            "retryable": False,
            "retry_after_seconds": None,
        }
    credential = account.credential
    if credential is None or not credential.secret_reference:
        return {
            "code": "CONFIGURATION_REQUIRED",
            "message": "官方账号凭据尚未配置。",
            "retryable": False,
            "retry_after_seconds": None,
        }
    if credential.expires_at and credential.expires_at <= timezone.now():
        return {
            "code": "REAUTHORIZATION_REQUIRED",
            "message": "平台授权已过期，请重新连接账号。",
            "retryable": False,
            "retry_after_seconds": None,
        }
    return None


def _refresh_batch_status(batch: GrowthPublishBatch) -> GrowthPublishBatch:
    statuses = list(batch.items.values_list("status", flat=True))
    if any(status == GrowthPublishItem.Status.RUNNING for status in statuses):
        status = GrowthPublishBatch.Status.RUNNING
    elif any(
        status in {GrowthPublishItem.Status.QUEUED, GrowthPublishItem.Status.DELEGATED}
        for status in statuses
    ):
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


def _execute_item(item_id, *, organization_id) -> None:
    with transaction.atomic():
        item = GrowthPublishItem.objects.select_for_update().select_related(
            "batch", "channel_package", "social_account__credential",
            "social_account__platform",
        ).get(pk=item_id, organization_id=organization_id)
        if item.status not in {GrowthPublishItem.Status.QUEUED, GrowthPublishItem.Status.FAILED}:
            return
        item.status = GrowthPublishItem.Status.RUNNING
        item.attempt_number += 1
        item.last_error = None
        item.save(update_fields=["status", "attempt_number", "last_error", "updated_at"])

        account = item.social_account
        metadata = account.connector_metadata if isinstance(account.connector_metadata, dict) else {}
        connection_kind = metadata.get("connection_kind")
        if not connection_kind and metadata.get("fixture") == "phase-a-e2e":
            connection_kind = "demo_fake"
        if connection_kind == "demo_fake":
            item.status = GrowthPublishItem.Status.SKIPPED
            item.last_error = {
                "code": "DEMO_ONLY_NO_EXTERNAL_PUBLISH",
                "message": "Demo/Fake connectors cannot create formal external posts.",
                "retryable": False,
                "retry_after_seconds": None,
            }
            item.save(update_fields=["status", "last_error", "updated_at"])
            return
        else:
            try:
                connector = get_connector_registry().resolve(account)
                consent = item.payload_snapshot.get("consent", {})
                if not isinstance(consent, dict):
                    consent = {}
                receipt = connector.publish(OfficialPublishRequest(
                    channel=item.channel,
                    account_external_id=account.external_id,
                    credential_reference=account.credential.secret_reference,
                    payload=item.payload_snapshot,
                    idempotency_key=f"{item.batch.idempotency_key}:{item.channel}",
                    consent=consent,
                ))
                succeeded = receipt.succeeded
                external_id = receipt.external_id
                external_url = receipt.external_url
                error_code = receipt.error_code
                error_message = receipt.error_message
                retryable = receipt.retryable
                retry_after_seconds = receipt.retry_after_seconds
            except ConnectorConfigurationRequired as error:
                succeeded = False
                external_id = ""
                external_url = ""
                error_code = "CONFIGURATION_REQUIRED"
                error_message = str(error)
                retryable = False
                retry_after_seconds = None
        if succeeded:
            item.status = GrowthPublishItem.Status.SUCCEEDED
            item.external_post_id = external_id
            item.external_post_url = external_url
        else:
            item.status = GrowthPublishItem.Status.FAILED
            item.last_error = {
                "code": error_code,
                "message": error_message,
                "retryable": retryable,
                "retry_after_seconds": retry_after_seconds,
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

        packages = list(ChannelPackage.objects.select_for_update().select_related(
            "source_platform_content"
        ).filter(
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
            if account is not None:
                preflight_error = _preflight_error(account, package)
                if preflight_error is not None:
                    item_status = GrowthPublishItem.Status.SKIPPED
                    last_error = preflight_error
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
                if (
                    package.source_platform_content_id
                    and account is not None
                    and account.publish_mode == SocialAccount.PublishMode.API_AUTO
                ):
                    try:
                        task = create_publish_task(
                            content=package.source_platform_content,
                            account=account,
                            idempotency_key=f"batch-delegated:{package.id}",
                            actor=actor,
                        )
                    except PublishingConflict as error:
                        item.status = GrowthPublishItem.Status.FAILED
                        item.last_error = {
                            "code": "PUBLISH_CONFLICT",
                            "message": str(error),
                        }
                        item.save(update_fields=["status", "last_error", "updated_at"])
                    else:
                        item.status = GrowthPublishItem.Status.DELEGATED
                        item.publish_task = task
                        item.save(update_fields=["status", "publish_task", "updated_at"])
                else:
                    queued_ids.append(item.id)

    from .tasks import execute_growth_publish_item

    for item_id in queued_ids:
        execute_growth_publish_item.delay(str(batch.organization_id), str(item_id))
    batch.refresh_from_db()
    return _refresh_batch_status(batch)


def retry_failed_items(*, batch: GrowthPublishBatch, actor) -> GrowthPublishBatch:
    del actor
    from .tasks import execute_growth_publish_item

    failed_ids = list(batch.items.filter(
        status=GrowthPublishItem.Status.FAILED,
        last_error__retryable=True,
    ).values_list("id", flat=True))
    for item_id in failed_ids:
        execute_growth_publish_item.delay(str(batch.organization_id), str(item_id))
    batch.refresh_from_db()
    return _refresh_batch_status(batch)


@transaction.atomic
def sync_publish_item_from_task(*, task_id, organization_id):
    item = GrowthPublishItem.objects.select_for_update().filter(
        organization_id=organization_id,
        publish_task_id=task_id,
    ).first()
    if item is None:
        return None
    task = PublishTask.objects.filter(
        id=task_id,
        organization_id=organization_id,
    ).first()
    if task is None:
        return item
    if task.status == PublishTask.Status.SUCCEEDED:
        post = PublishedPost.objects.filter(task_id=task.id).first()
        item.status = GrowthPublishItem.Status.SUCCEEDED
        item.external_post_id = post.external_id if post else ""
        item.last_error = None
    elif task.status in {
        PublishTask.Status.SUBMITTED, PublishTask.Status.SUBMISSION_UNKNOWN,
        PublishTask.Status.NEEDS_ATTENTION,
    }:
        item.status = GrowthPublishItem.Status.DELEGATED
        item.last_error = task.last_error or None
    elif task.status == PublishTask.Status.FAILED:
        item.status = GrowthPublishItem.Status.FAILED
        item.last_error = task.last_error or {
            "code": "PUBLISH_FAILED",
            "message": "Publish failed.",
        }
    elif task.status == PublishTask.Status.CANCELED:
        item.status = GrowthPublishItem.Status.FAILED
        item.last_error = {
            "code": "PUBLISH_CANCELED",
            "message": "Publish was canceled.",
        }
    item.save(update_fields=["status", "external_post_id", "last_error", "updated_at"])
    batch = item.batch
    batch.refresh_from_db()
    _refresh_batch_status(batch)
    return item
