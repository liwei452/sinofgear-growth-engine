import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.common.tenant_tasks import TenantTaskError
from apps.growth.email_verification_services import request_email_verification
from apps.growth.models import EmailVerificationRun
from apps.growth.tasks import run_email_verification
from apps.identity.models import Organization


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("organization_id", [None, "", " ", 1, True, [], {}, "bad-uuid"])
def test_task_rejects_untrusted_organization_identifiers(organization_id):
    with pytest.raises(TenantTaskError, match="organization_id"):
        run_email_verification(organization_id, str(uuid.uuid4()))


@pytest.mark.parametrize("run_id", [None, "", " ", 1, True, [], {}, "bad-uuid"])
def test_task_rejects_untrusted_run_identifiers(run_id):
    organization = Organization.objects.create(name=f"Task {uuid.uuid4()}", slug=f"task-{uuid.uuid4()}")
    with pytest.raises(TenantTaskError, match="verification_id"):
        run_email_verification(str(organization.id), run_id)


def test_task_cannot_execute_another_tenants_run():
    own = Organization.objects.create(name="Task Own", slug="task-own")
    other = Organization.objects.create(name="Task Other", slug="task-other")
    run, _ = request_email_verification(
        organization_id=other.id,
        email="buyer@example.com",
        idempotency_key="task-cross-tenant",
        dispatch=False,
    )

    with pytest.raises(ValidationError, match="unavailable"):
        run_email_verification(str(own.id), str(run.id))


def test_dispatch_occurs_once_after_commit_and_not_after_rollback(monkeypatch):
    organization = Organization.objects.create(name="Dispatch", slug="email-dispatch")
    calls = []
    monkeypatch.setattr(run_email_verification, "delay", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(RuntimeError):
        with transaction.atomic():
            request_email_verification(
                organization_id=organization.id,
                email="rollback@example.com",
                idempotency_key="rollback-dispatch",
            )
            raise RuntimeError("rollback")
    assert calls == []

    with transaction.atomic():
        run, created = request_email_verification(
            organization_id=organization.id,
            email="commit@example.com",
            idempotency_key="commit-dispatch",
        )
        assert created is True
        assert calls == []

    assert calls == [((str(organization.id), str(run.id)), {})]
    assert EmailVerificationRun.objects.filter(id=run.id).exists()
