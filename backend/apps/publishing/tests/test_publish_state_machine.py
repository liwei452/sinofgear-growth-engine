from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.content.models import content_writes
from apps.publishing.models import PublishTask
from apps.publishing.services import PublishingConflict, create_publish_task
from apps.platforms.models import ConnectorCredential, Platform, SocialAccount


def test_unapproved_content_cannot_be_scheduled(publishing_context):
    context = publishing_context
    content = context["content"]
    with content_writes():
        type(content).objects.filter(pk=content.pk).update(status="IN_REVIEW")

    with pytest.raises(PublishingConflict, match="APPROVED"):
        create_publish_task(
            content=content,
            account=context["account"],
            idempotency_key="unapproved",
            actor=context["actor"],
        )


def test_schedule_requires_aware_bounded_time(publishing_context):
    context = publishing_context
    with pytest.raises(PublishingConflict, match="timezone-aware"):
        create_publish_task(
            content=context["content"],
            account=context["account"],
            idempotency_key="naive",
            scheduled_at=timezone.now().replace(tzinfo=None) + timedelta(hours=1),
            timezone_name="Europe/Berlin",
            actor=context["actor"],
        )


def test_account_must_be_active_same_platform_and_api_automatic(publishing_context):
    context = publishing_context
    account = context["account"]
    account.status = SocialAccount.Status.INACTIVE
    account.save(update_fields=["status", "updated_at"])
    with pytest.raises(PublishingConflict, match="ACTIVE"):
        create_publish_task(
            content=context["content"], account=account,
            idempotency_key="inactive", actor=context["actor"],
        )

    other_platform = Platform.objects.create(code="OTHER", name="Other")
    credential = ConnectorCredential.objects.create(
        organization=context["organization"], platform=other_platform,
        secret_reference="vault://other", granted_scopes=["PUBLISH"],
    )
    other_account = SocialAccount.objects.create(
        organization=context["organization"], platform=other_platform,
        credential=credential, external_id="other", display_name="Other",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
    )
    with pytest.raises(PublishingConflict, match="platform"):
        create_publish_task(
            content=context["content"], account=other_account,
            idempotency_key="mismatch", actor=context["actor"],
        )


def test_expired_connector_credential_cannot_create_task(publishing_context):
    context = publishing_context
    credential = context["account"].credential
    credential.expires_at = timezone.now() - timedelta(seconds=1)
    credential.save(update_fields=["expires_at", "updated_at"])

    with pytest.raises(PublishingConflict, match="expired"):
        create_publish_task(
            content=context["content"], account=context["account"],
            idempotency_key="expired-credential", actor=context["actor"],
        )


def test_manual_mode_and_missing_capability_return_controlled_conflicts(
    publishing_context,
):
    context = publishing_context
    account = context["account"]
    account.publish_mode = SocialAccount.PublishMode.MANUAL
    account.save(update_fields=["publish_mode", "updated_at"])
    with pytest.raises(PublishingConflict, match="publish mode"):
        create_publish_task(
            content=context["content"], account=account,
            idempotency_key="manual-mode", actor=context["actor"],
        )

    account.publish_mode = SocialAccount.PublishMode.API_AUTO
    account.credential.granted_scopes = []
    account.credential.save(update_fields=["granted_scopes", "updated_at"])
    account.save(update_fields=["publish_mode", "updated_at"])
    with pytest.raises(PublishingConflict, match="capability"):
        create_publish_task(
            content=context["content"], account=account,
            idempotency_key="no-capability", actor=context["actor"],
        )


def test_publish_task_rejects_direct_mutation_and_delete(publishing_context):
    context = publishing_context
    task = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="protected", scheduled_at=timezone.now() + timedelta(hours=1),
        actor=context["actor"],
    )
    task.status = PublishTask.Status.SUCCEEDED

    with pytest.raises(ValidationError):
        task.save()
    with pytest.raises(ValidationError):
        PublishTask._base_manager.filter(pk=task.pk).update(status="SUCCEEDED")
    with pytest.raises(ValidationError):
        PublishTask.objects.bulk_update([task], ["status"])
    with pytest.raises(ValidationError):
        task.delete()
