import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.ai.models import PromptVersion
from apps.ai.services import PromptVersionService
from apps.identity.models import Membership, Role
from apps.jobs.models import Job
from apps.leads.models import LeadCandidate
from apps.leads.schemas import LEAD_ANALYSIS_OUTPUT_SCHEMA
from apps.leads.services import LeadService
from apps.sources.models import SourceEvidence, evidence_service_writes


pytestmark = pytest.mark.django_db


def _client(organization, role, username):
    member = get_user_model().objects.create_user(username=username)
    Membership.objects.create(user=member, organization=organization, role=role)
    client = APIClient()
    client.force_authenticate(member)
    return member, client


def _operator(organization, username="lead-api-operator"):
    return _client(organization, Role.objects.create_operator(), username)


def _reviewer(organization):
    return _client(organization, Role.objects.create_reviewer(), "lead-api-reviewer")


def _analyzed(candidate, evidence, ai_run, insight_payload):
    LeadService.begin_analysis(
        organization=candidate.organization,
        candidate=candidate,
        expected_version=candidate.version,
    )
    LeadService.record_insight(
        organization=candidate.organization,
        candidate=candidate,
        ai_run=ai_run,
        evidence=[evidence],
        payload=insight_payload(),
    )
    candidate.refresh_from_db()


def test_create_list_and_detail_candidate_are_evidence_first(
    organization, evidence, other_source_pair
):
    _user, client = _operator(organization)
    response = client.post(
        "/api/v1/lead-candidates",
        {
            "company_name": "ABC Packaging GmbH",
            "company_domain": "https://abc-packaging.example/",
            "country_hint": "DE",
            "evidence_ids": [str(evidence.id)],
        },
        format="json",
    )

    assert response.status_code == 201
    candidate_id = response.json()["id"]
    listing = client.get("/api/v1/lead-candidates?status=DISCOVERED&platform=MANUAL")
    detail = client.get(f"/api/v1/lead-candidates/{candidate_id}")
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()["results"]] == [candidate_id]
    assert detail.status_code == 200
    assert detail.json()["company"] == {
        "name": "ABC Packaging GmbH",
        "domain": "abc-packaging.example",
        "country_hint": "DE",
    }
    assert detail.json()["evidence"][0]["original_text"] == evidence.original_text
    assert str(other_source_pair[1].id) not in str(detail.json())


def test_candidate_create_rejects_cross_org_evidence(organization, other_source_pair):
    _user, client = _operator(organization)
    response = client.post(
        "/api/v1/lead-candidates",
        {
            "company_name": "Unsafe",
            "evidence_ids": [str(other_source_pair[1].id)],
        },
        format="json",
    )
    assert response.status_code == 404
    assert "lead-other" not in str(response.json())
    assert other_source_pair[1].original_text not in str(response.json())
    assert LeadCandidate.objects.filter(organization=organization).count() == 0


def test_candidate_create_keeps_malformed_same_org_evidence_as_400(
    organization,
    evidence,
):
    _user, client = _operator(organization)
    response = client.post(
        "/api/v1/lead-candidates",
        {
            "company_name": "Malformed",
            "evidence_ids": [str(evidence.id), str(evidence.id)],
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "http_400"


def test_repeated_filters_are_rejected(organization):
    _user, client = _operator(organization)
    response = client.get("/api/v1/lead-candidates?status=DISCOVERED&status=ANALYZED")
    assert response.status_code == 400
    assert response.json()["code"] == "http_400"


def test_malformed_candidate_cursor_is_recoverable(organization):
    _user, client = _operator(organization)
    response = client.get("/api/v1/lead-candidates?cursor=not-a-valid-cursor")
    assert response.status_code == 400
    assert response.json()["code"] == "http_400"


def test_cross_org_candidate_detail_is_404(candidate, other_organization):
    _user, client = _operator(other_organization)
    response = client.get(f"/api/v1/lead-candidates/{candidate.id}")
    assert response.status_code == 404
    assert candidate.company_name not in str(response.json())


def test_analyze_is_idempotent_and_schedules_after_commit(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    del approved_requirement, approved_capability
    user, client = _operator(candidate.organization)
    prompt = PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="lead-api-analysis",
        provider="fake",
        model="fake-v1",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    dispatched = []
    monkeypatch.setattr(
        "apps.leads.tasks.execute_lead_analysis.delay",
        lambda job_id, prompt_id: dispatched.append((job_id, prompt_id)),
    )
    payload = {
        "expected_version": candidate.version,
        "evidence_ids": [str(evidence.id)],
        "idempotency_key": "analyze-api-1",
    }
    with django_capture_on_commit_callbacks(execute=True):
        first = client.post(
            f"/api/v1/lead-candidates/{candidate.id}/analyze", payload, format="json"
        )
    with django_capture_on_commit_callbacks(execute=True):
        second = client.post(
            f"/api/v1/lead-candidates/{candidate.id}/analyze", payload, format="json"
        )

    assert first.status_code == second.status_code == 202
    assert second.json()["job_id"] == first.json()["job_id"]
    assert first.json()["status"] == Job.Status.QUEUED
    assert dispatched == [(first.json()["job_id"], str(prompt.id))]
    assert Job.objects.filter(type=Job.Type.LEAD_ANALYZE).count() == 1


def test_own_candidate_analyze_hides_foreign_evidence_as_404(
    candidate,
    other_source_pair,
):
    user, client = _operator(candidate.organization)
    PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="lead-api-foreign-evidence",
        provider="fake",
        model="fake-v1",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    foreign_evidence = other_source_pair[1]

    response = client.post(
        f"/api/v1/lead-candidates/{candidate.id}/analyze",
        {
            "expected_version": candidate.version,
            "evidence_ids": [str(foreign_evidence.id)],
            "idempotency_key": "foreign-evidence-hidden",
        },
        format="json",
    )

    assert response.status_code == 404
    body = str(response.json())
    assert "lead-other" not in body
    assert foreign_evidence.original_text not in body
    assert not Job.objects.filter(type=Job.Type.LEAD_ANALYZE).exists()


def test_own_candidate_analyze_keeps_same_org_unlinked_evidence_as_400(
    candidate,
    second_source_pair,
):
    user, client = _operator(candidate.organization)
    PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="lead-api-unlinked-evidence",
        provider="fake",
        model="fake-v1",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )

    response = client.post(
        f"/api/v1/lead-candidates/{candidate.id}/analyze",
        {
            "expected_version": candidate.version,
            "evidence_ids": [str(second_source_pair[1].id)],
            "idempotency_key": "same-org-unlinked-evidence",
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "http_400"
    assert not Job.objects.filter(type=Job.Type.LEAD_ANALYZE).exists()


def test_analyze_same_key_different_request_conflicts(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    del approved_requirement, approved_capability
    user, client = _operator(candidate.organization)
    PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="lead-api-analysis-conflict",
        provider="fake",
        model="fake-v1",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    monkeypatch.setattr("apps.leads.tasks.execute_lead_analysis.delay", lambda *_: None)
    first_payload = {
        "expected_version": candidate.version,
        "evidence_ids": [str(evidence.id)],
        "idempotency_key": "analyze-conflict",
    }
    with django_capture_on_commit_callbacks(execute=True):
        assert (
            client.post(
                f"/api/v1/lead-candidates/{candidate.id}/analyze",
                first_payload,
                format="json",
            ).status_code
            == 202
        )
    changed = dict(first_payload, expected_version=candidate.version + 99)
    response = client.post(
        f"/api/v1/lead-candidates/{candidate.id}/analyze", changed, format="json"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_conflict"


def test_analyze_rejects_incompatible_published_prompt_without_orphaning_lease(
    candidate, evidence, monkeypatch
):
    user, client = _operator(candidate.organization)
    PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="lead-api-bad-schema",
        provider="fake",
        model="fake-v1",
        template="{input_json}",
        output_schema={"type": "string"},
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    monkeypatch.setattr("apps.leads.tasks.execute_lead_analysis.delay", lambda *_: None)

    response = client.post(
        f"/api/v1/lead-candidates/{candidate.id}/analyze",
        {
            "expected_version": candidate.version,
            "evidence_ids": [str(evidence.id)],
            "idempotency_key": "bad-prompt-schema",
        },
        format="json",
    )

    assert response.status_code == 409
    candidate.refresh_from_db()
    assert candidate.status == LeadCandidate.Status.DISCOVERED
    assert candidate.analysis_lease_token is None
    assert not Job.objects.filter(type=Job.Type.LEAD_ANALYZE).exists()


def test_analyze_rejects_redacted_evidence_without_job_or_lease(
    candidate, evidence, monkeypatch
):
    user, client = _operator(candidate.organization)
    PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="lead-api-redacted-evidence",
        provider="fake",
        model="fake-v1",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    with evidence_service_writes():
        evidence.availability = SourceEvidence.Availability.REDACTED_BY_RETENTION
        evidence.original_text = ""
        evidence.save(update_fields=["availability", "original_text", "updated_at"])
    monkeypatch.setattr("apps.leads.tasks.execute_lead_analysis.delay", lambda *_: None)

    response = client.post(
        f"/api/v1/lead-candidates/{candidate.id}/analyze",
        {
            "expected_version": candidate.version,
            "evidence_ids": [str(evidence.id)],
            "idempotency_key": "redacted-evidence",
        },
        format="json",
    )

    assert response.status_code == 400
    candidate.refresh_from_db()
    assert candidate.status == LeadCandidate.Status.DISCOVERED
    assert candidate.analysis_lease_token is None
    assert not Job.objects.filter(type=Job.Type.LEAD_ANALYZE).exists()


def test_operator_cannot_inject_model_or_request_enhanced_analysis(candidate, evidence):
    _user, client = _operator(candidate.organization)
    base = {
        "expected_version": candidate.version,
        "evidence_ids": [str(evidence.id)],
        "idempotency_key": "routing-injection",
    }
    model = client.post(
        f"/api/v1/lead-candidates/{candidate.id}/analyze",
        {**base, "model": "deepseek-v4-pro"}, format="json",
    )
    enhanced = client.post(
        f"/api/v1/lead-candidates/{candidate.id}/analyze",
        {**base, "enhanced_analysis": True}, format="json",
    )
    assert model.status_code == enhanced.status_code == 400


def test_deepseek_schedule_routes_persisted_conflicting_requirements_to_pro(
    candidate, evidence, approved_requirement, approved_capability,
    monkeypatch, django_capture_on_commit_callbacks,
):
    del approved_requirement, approved_capability
    from apps.ai.models import AIExecutionIntent, AIProviderConfiguration

    user, client = _operator(candidate.organization)
    # Configuration is trusted persisted server state; the operator cannot alter it.
    AIProviderConfiguration.objects.create(
        organization=candidate.organization,
        connection_state="CONNECTED",
        key_suffix="safe",
    )
    PromptVersionService.create(
        purpose="LEAD_ANALYZE", code="lead-deepseek-routing", provider="deepseek",
        model="deepseek-v4-flash", template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED, created_by=user,
    )
    # Persisted evidence contains two incompatible quantities for the same need.
    from apps.sources.models import evidence_service_writes
    with evidence_service_writes():
        evidence.original_text = "Need 200 pcs helical gears, correction: need 500 pcs helical gears."
        evidence.save(update_fields=["original_text", "updated_at"])
    monkeypatch.setattr("apps.leads.tasks.execute_lead_analysis.delay", lambda *_: None)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            f"/api/v1/lead-candidates/{candidate.id}/analyze",
            {
                "expected_version": candidate.version,
                "evidence_ids": [str(evidence.id)],
                "idempotency_key": "trusted-conflicting-requirements",
            },
            format="json",
        )

    assert response.status_code == 202
    intent = AIExecutionIntent.objects.get(job_id=response.json()["job_id"])
    assert intent.model == "deepseek-v4-pro"
    assert intent.job.input_snapshot["routing_signals"] == {
        "codes": ["CONFLICTING_QUANTITIES"],
        "policy_version": 1,
    }
    from apps.leads.orchestration import execute_lead_analysis_job
    from integrations.ai.providers import ProviderResult, provider_registry

    class InvalidButReachedProvider:
        def generate(self, *, prompt, schema, execution):
            return ProviderResult(output={}, metadata={})

    provider_registry.register("deepseek", InvalidButReachedProvider(), replace=True)
    run = execute_lead_analysis_job(intent.job_id)
    assert run.error["code"] == "invalid_provider_output"


def test_deepseek_schedule_routes_ordinary_persisted_evidence_to_flash(
    candidate, evidence, approved_requirement, approved_capability,
    monkeypatch, django_capture_on_commit_callbacks,
):
    del approved_requirement, approved_capability
    from apps.ai.models import AIExecutionIntent, AIProviderConfiguration

    user, client = _operator(candidate.organization, username="lead-flash-operator")
    AIProviderConfiguration.objects.create(
        organization=candidate.organization,
        connection_state="CONNECTED",
        key_suffix="safe",
    )
    PromptVersionService.create(
        purpose="LEAD_ANALYZE", code="lead-deepseek-flash", provider="deepseek",
        model="deepseek-v4-flash", template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED, created_by=user,
    )
    monkeypatch.setattr("apps.leads.tasks.execute_lead_analysis.delay", lambda *_: None)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            f"/api/v1/lead-candidates/{candidate.id}/analyze",
            {
                "expected_version": candidate.version,
                "evidence_ids": [str(evidence.id)],
                "idempotency_key": "trusted-routine-evidence",
            }, format="json",
        )

    assert response.status_code == 202
    intent = AIExecutionIntent.objects.get(job_id=response.json()["job_id"])
    assert (intent.model, intent.thinking_enabled) == ("deepseek-v4-flash", False)
    assert intent.job.input_snapshot["routing_signals"]["codes"] == []


def test_reviewer_correction_api_returns_append_only_versions(
    candidate, evidence, ai_run, insight_payload
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    _user, client = _reviewer(candidate.organization)
    response = client.post(
        "/api/v1/lead-reviews",
        {
            "candidate_id": str(candidate.id),
            "action": "CORRECT",
            "expected_version": candidate.version,
            "correction": {
                "company_name": "ABC Packaging GmbH",
                "dimension_overrides": {"company_fit": 22},
            },
            "reason": "Public company page confirms the name.",
            "idempotency_key": "review-api-correct",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["candidate_status"] == "REVIEWED"
    assert response.json()["insight_version"] == 2


def test_insight_history_is_scoped(
    candidate, other_organization, evidence, ai_run, insight_payload
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    _own_user, own_client = _operator(candidate.organization)
    _other_user, other_client = _operator(other_organization, "lead-api-other-operator")
    own = own_client.get(f"/api/v1/lead-insights?candidate_id={candidate.id}")
    other = other_client.get(f"/api/v1/lead-insights?candidate_id={candidate.id}")
    assert own.status_code == other.status_code == 200
    assert len(own.json()["results"]) == 1
    assert other.json()["results"] == []


def test_detail_history_has_bounded_queries_and_safe_ai_metadata(
    candidate,
    evidence,
    ai_run,
    insight_payload,
    django_assert_max_num_queries,
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    _user, client = _operator(candidate.organization)
    with django_assert_max_num_queries(8):
        response = client.get(f"/api/v1/lead-candidates/{candidate.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_insight"]["ai_audit"] == {
        "ai_run_id": str(ai_run.id),
        "status": "SUCCEEDED",
        "prompt_code": ai_run.prompt_version.code,
        "prompt_version": ai_run.prompt_version.version,
        "model": ai_run.model,
    }
    assert "template" not in str(body).lower()
    assert "provider_metadata" not in str(body).lower()


@pytest.mark.parametrize(
    ("role_factory", "expected_actions"),
    [
        (Role.objects.create_read_only, []),
        (Role.objects.create_operator, ["ANALYZE"]),
        (
            Role.objects.create_reviewer,
            ["CONFIRM", "CORRECT", "DISMISS", "REQUEST_MORE_EVIDENCE"],
        ),
        (
            Role.objects.create_administrator,
            ["ANALYZE", "CONFIRM", "CORRECT", "DISMISS", "REQUEST_MORE_EVIDENCE"],
        ),
    ],
)
def test_detail_permitted_actions_follow_exact_membership_permissions(
    candidate,
    evidence,
    ai_run,
    insight_payload,
    role_factory,
    expected_actions,
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    role = role_factory()
    _user, client = _client(
        candidate.organization,
        role,
        f"actions-{role.code.lower()}",
    )
    response = client.get(f"/api/v1/lead-candidates/{candidate.id}")
    assert response.status_code == 200
    assert response.json()["permitted_actions"] == expected_actions
