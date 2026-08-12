from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.director.models import DirectorDecision, DirectorProposal
from apps.director.selectors import cockpit_snapshot
from apps.identity.models import Membership, Organization, Role
from apps.identity.permissions import PermissionCode
from apps.jobs.models import Job, job_service_writes


def _member(*, slug="acme", permissions=()):
    organization = Organization.objects.create(name=slug.title(), slug=slug)
    role = Role.objects.create(
        code=f"ROLE_{slug}_{Role.objects.count()}",
        name="Test role",
        permissions=[str(permission) for permission in permissions],
    )
    user = get_user_model().objects.create_user(username=f"user-{slug}")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client, user, organization


def _proposal(organization, *, priority=50, expires_at=None, title="待决定事项"):
    return DirectorProposal.objects.create(
        organization=organization,
        proposal_type=DirectorProposal.ProposalType.CONTENT_APPROVAL,
        title_zh=title,
        summary_zh="来自已确认的产品资料",
        reason_snapshot={"secret": "must-not-leak"},
        action_reference={"kind": "internal", "id": "must-not-leak"},
        priority=priority,
        expires_at=expires_at,
    )


@pytest.mark.django_db
def test_cockpit_requires_authentication():
    response = APIClient().get("/api/v1/director/cockpit")
    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_cockpit_requires_director_read():
    client, _, _ = _member(permissions=[])
    assert client.get("/api/v1/director/cockpit").status_code == 403


@pytest.mark.django_db
def test_cockpit_returns_top_three_pending_proposals_without_internal_fields():
    client, _, organization = _member(
        permissions=[PermissionCode.DIRECTOR_READ, PermissionCode.DIRECTOR_DECIDE]
    )
    for priority in [10, 80, 30, 100]:
        _proposal(organization, priority=priority, title=f"事项 {priority}")
    other = Organization.objects.create(name="Other", slug="other")
    _proposal(other, priority=99, title="其他公司的事项")

    response = client.get("/api/v1/director/cockpit")

    assert response.status_code == 200
    body = response.json()
    assert [item["priority"] for item in body["decisions"]] == [100, 80, 30]
    assert all(item["actions"] == ["APPROVE", "REQUEST_ADJUSTMENT", "REJECT"] for item in body["decisions"])
    serialized = str(body)
    assert "must-not-leak" not in serialized
    assert "reason_snapshot" not in serialized
    assert "action_reference" not in serialized
    assert "其他公司的事项" not in serialized
    assert body["generated_at"]


@pytest.mark.django_db
def test_read_only_cockpit_omits_decision_actions_and_unpermitted_panels():
    client, _, organization = _member(permissions=[PermissionCode.DIRECTOR_READ])
    _proposal(organization)
    with job_service_writes():
        Job.objects.create(
            organization=organization,
            type=Job.Type.CONTENT_GENERATE,
            status=Job.Status.RUNNING,
            progress=42,
            input_snapshot={"provider_error": "must-not-leak"},
            idempotency_key="job-1",
        )

    body = client.get("/api/v1/director/cockpit").json()

    assert body["decisions"][0]["actions"] == []
    assert body["active_work"] == []
    assert body["recent_outcomes"] == []


@pytest.mark.django_db
def test_cockpit_returns_at_most_five_priority_ordered_active_jobs():
    client, _, organization = _member(
        permissions=[PermissionCode.DIRECTOR_READ, PermissionCode.JOBS_READ]
    )
    with job_service_writes():
        for index, status in enumerate(
            [Job.Status.QUEUED, Job.Status.RUNNING, Job.Status.RETRY_QUEUED] * 2
        ):
            Job.objects.create(
                organization=organization,
                type=Job.Type.CONTENT_GENERATE,
                status=status,
                progress=index * 10,
                input_snapshot={},
                idempotency_key=f"job-{index}",
            )

    body = client.get("/api/v1/director/cockpit").json()

    assert len(body["active_work"]) == 5
    assert set(body["active_work"][0]) == {
        "job_id", "label", "status", "progress", "progress_is_determinate"
    }
    assert all("error" not in item for item in body["active_work"])


@pytest.mark.django_db
def test_cockpit_selector_query_count_does_not_grow_with_items(django_assert_num_queries):
    _, _, organization = _member(
        permissions=[PermissionCode.DIRECTOR_READ, PermissionCode.JOBS_READ]
    )
    for priority in range(5):
        _proposal(organization, priority=priority + 1, title=f"事项 {priority}")
    with job_service_writes():
        for index in range(6):
            Job.objects.create(
                organization=organization,
                type=Job.Type.CONTENT_GENERATE,
                status=Job.Status.RUNNING,
                progress=index,
                input_snapshot={},
                idempotency_key=f"query-job-{index}",
            )

    with django_assert_num_queries(2):
        snapshot = cockpit_snapshot(
            organization=organization,
            permissions=[PermissionCode.DIRECTOR_READ, PermissionCode.JOBS_READ],
            now=timezone.now(),
        )

    assert len(snapshot["decisions"]) == 3
    assert len(snapshot["active_work"]) == 5


@pytest.mark.django_db
def test_empty_cockpit_is_truthful():
    client, _, _ = _member(permissions=[PermissionCode.DIRECTOR_READ])
    body = client.get("/api/v1/director/cockpit").json()
    assert body["decisions"] == []
    assert body["active_work"] == []
    assert body["recent_outcomes"] == []


@pytest.mark.django_db
def test_decision_requires_director_decide():
    client, _, organization = _member(permissions=[PermissionCode.DIRECTOR_READ])
    proposal = _proposal(organization)
    response = client.post(
        f"/api/v1/director/proposals/{proposal.id}/decisions",
        {"action": "APPROVE", "expected_version": 1, "comment": ""},
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_decision_approves_and_returns_public_proposal():
    client, user, organization = _member(
        permissions=[PermissionCode.DIRECTOR_READ, PermissionCode.DIRECTOR_DECIDE]
    )
    proposal = _proposal(organization)
    response = client.post(
        f"/api/v1/director/proposals/{proposal.id}/decisions",
        {"action": "APPROVE", "expected_version": 1, "comment": ""},
        format="json",
    )
    assert response.status_code == 200
    assert response.json() == {"id": str(proposal.id), "status": "APPROVED", "version": 2}
    assert DirectorDecision.objects.get(proposal=proposal).actor == user


@pytest.mark.django_db
def test_decision_rejects_unknown_fields_and_invalid_action():
    client, _, organization = _member(
        permissions=[PermissionCode.DIRECTOR_READ, PermissionCode.DIRECTOR_DECIDE]
    )
    proposal = _proposal(organization)
    unknown = client.post(
        f"/api/v1/director/proposals/{proposal.id}/decisions",
        {"action": "APPROVE", "expected_version": 1, "comment": "", "extra": True},
        format="json",
    )
    invalid = client.post(
        f"/api/v1/director/proposals/{proposal.id}/decisions",
        {"action": "DELETE", "expected_version": 1, "comment": ""},
        format="json",
    )
    assert unknown.status_code == 400
    assert unknown.json()["errors"]["extra"] == ["Unknown field."]
    assert invalid.status_code == 400


@pytest.mark.django_db
def test_decision_conceals_cross_organization_proposal():
    client, _, _ = _member(
        slug="first",
        permissions=[PermissionCode.DIRECTOR_READ, PermissionCode.DIRECTOR_DECIDE],
    )
    other = Organization.objects.create(name="Second", slug="second")
    proposal = _proposal(other)
    response = client.post(
        f"/api/v1/director/proposals/{proposal.id}/decisions",
        {"action": "APPROVE", "expected_version": 1, "comment": ""},
        format="json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"action": "APPROVE", "expected_version": 2, "comment": ""}, "director_version_conflict"),
        ({"action": "REJECT", "expected_version": 1, "comment": ""}, "director_comment_required"),
    ],
)
def test_decision_returns_stable_recoverable_error_codes(payload, code):
    client, _, organization = _member(
        permissions=[PermissionCode.DIRECTOR_READ, PermissionCode.DIRECTOR_DECIDE]
    )
    proposal = _proposal(organization)
    response = client.post(
        f"/api/v1/director/proposals/{proposal.id}/decisions", payload, format="json"
    )
    assert response.status_code == 409
    assert response.json()["code"] == code


@pytest.mark.django_db
def test_expired_and_duplicate_decisions_have_stable_codes():
    client, _, organization = _member(
        permissions=[PermissionCode.DIRECTOR_READ, PermissionCode.DIRECTOR_DECIDE]
    )
    expired = _proposal(organization, expires_at=timezone.now() - timedelta(seconds=1))
    expired_response = client.post(
        f"/api/v1/director/proposals/{expired.id}/decisions",
        {"action": "APPROVE", "expected_version": 1, "comment": ""}, format="json"
    )
    assert expired_response.status_code == 409
    assert expired_response.json()["code"] == "director_expired"

    proposal = _proposal(organization, title="另一个")
    url = f"/api/v1/director/proposals/{proposal.id}/decisions"
    payload = {"action": "APPROVE", "expected_version": 1, "comment": ""}
    assert client.post(url, payload, format="json").status_code == 200
    duplicate = client.post(url, payload, format="json")
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "director_version_conflict"

    state_conflict = client.post(
        url,
        {"action": "APPROVE", "expected_version": 2, "comment": ""},
        format="json",
    )
    assert state_conflict.status_code == 409
    assert state_conflict.json()["code"] == "director_state_conflict"
