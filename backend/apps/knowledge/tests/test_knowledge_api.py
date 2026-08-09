import uuid

import pytest
from rest_framework.test import APIClient

from apps.audit.models import ApprovalRecord, AuditLog
from apps.identity.models import Role
from apps.knowledge.models import KnowledgeAlias, KnowledgeEvidence, KnowledgeRelation

from .conftest import create_member_client, create_test_knowledge, make_concept


@pytest.mark.django_db
def test_anonymous_requests_are_denied() -> None:
    client = APIClient()
    for path in ("/api/v1/knowledge/concepts", "/api/v1/knowledge/relations", "/api/v1/knowledge/aliases"):
        assert client.get(path).status_code == 403


@pytest.mark.django_db
def test_operator_creates_only_organization_suggestions_and_cannot_approve(organizations, roles) -> None:
    own, _ = organizations
    _membership, client = create_member_client(organization=own, role=roles[Role.Code.OPERATOR], username="operator")
    response = client.post(
        "/api/v1/knowledge/concepts",
        {"concept_type": "PRODUCT_TYPE", "code": "CUSTOM_GEAR", "label_zh": "定制齿轮", "label_en": "Custom Gear"},
        format="json",
    )

    assert response.status_code == 201, response.json()
    assert response.json()["scope"] == "ORGANIZATION"
    assert response.json()["organization"] == str(own.id)
    assert response.json()["status"] == "SUGGESTED"
    assert client.post(f"/api/v1/knowledge/concepts/{response.json()['id']}/approve", {}, format="json").status_code == 403

    submitted = client.post(
        f"/api/v1/knowledge/concepts/{response.json()['id']}/submit-review", {}, format="json"
    )
    assert submitted.status_code == 200
    assert ApprovalRecord.objects.filter(object_id=response.json()["id"], action="SUBMIT").exists()


@pytest.mark.django_db
def test_ai_originated_relation_requires_uuid_and_remains_suggested(organizations, roles) -> None:
    own, _ = organizations
    _membership, client = create_member_client(organization=own, role=roles[Role.Code.OPERATOR], username="operator-ai")
    subject = make_concept(code="CUSTOM", organization=own)
    object_ = make_concept(code="APP", concept_type="APPLICATION", organization=own)
    malformed = client.post(
        "/api/v1/knowledge/relations",
        {"subject_concept": str(subject.id), "predicate": "APPLIES_TO", "object_concept": str(object_.id), "suggested_by_ai_run_id": "not-a-uuid"},
        format="json",
    )
    run_id = uuid.uuid4()
    created = client.post(
        "/api/v1/knowledge/relations",
        {"subject_concept": str(subject.id), "predicate": "APPLIES_TO", "object_concept": str(object_.id), "suggested_by_ai_run_id": str(run_id)},
        format="json",
    )

    assert malformed.status_code == 400
    assert created.status_code == 201
    assert created.json()["suggested_by_ai_run_id"] == str(run_id)
    assert created.json()["status"] == "SUGGESTED"


@pytest.mark.django_db
def test_operator_relation_between_system_concepts_is_an_organization_suggestion(organizations, roles) -> None:
    own, _ = organizations
    _membership, client = create_member_client(organization=own, role=roles[Role.Code.OPERATOR], username="operator-overlay")
    subject = make_concept(code="SYSTEM_PRODUCT")
    object_ = make_concept(code="SYSTEM_APPLICATION", concept_type="APPLICATION")

    response = client.post(
        "/api/v1/knowledge/relations",
        {"subject_concept": str(subject.id), "predicate": "APPLIES_TO", "object_concept": str(object_.id)},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["organization"] == str(own.id)
    assert response.json()["status"] == "SUGGESTED"


@pytest.mark.django_db
def test_reviewer_cannot_review_system_but_can_review_organization_knowledge(organizations, roles) -> None:
    own, _ = organizations
    _membership, client = create_member_client(organization=own, role=roles[Role.Code.REVIEWER], username="reviewer-knowledge")
    system = make_concept(code="SYSTEM_REVIEW", status="SUGGESTED")
    organization = make_concept(code="ORG_REVIEW", organization=own, status="SUGGESTED")

    assert client.post(f"/api/v1/knowledge/concepts/{system.id}/approve", {}, format="json").status_code == 403
    approved = client.post(f"/api/v1/knowledge/concepts/{organization.id}/approve", {}, format="json")
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"


@pytest.mark.django_db
def test_administrator_can_create_and_review_system_knowledge(organizations, roles) -> None:
    own, _ = organizations
    _membership, client = create_member_client(organization=own, role=roles[Role.Code.ADMINISTRATOR], username="admin-system")
    created = client.post(
        "/api/v1/knowledge/concepts",
        {"scope": "SYSTEM", "concept_type": "STANDARD", "code": "SYSTEM_STANDARD", "label_zh": "系统标准", "label_en": "System Standard"},
        format="json",
    )
    approved = client.post(f"/api/v1/knowledge/concepts/{created.json()['id']}/approve", {}, format="json")

    assert created.status_code == 201
    assert created.json()["organization"] is None
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"


@pytest.mark.django_db
def test_administrator_can_create_system_evidence(organizations, roles) -> None:
    own, _ = organizations
    _membership, client = create_member_client(organization=own, role=roles[Role.Code.ADMINISTRATOR], username="admin-evidence")

    response = client.post(
        "/api/v1/knowledge/evidence",
        {"scope": "SYSTEM", "evidence_type": "STANDARD_REFERENCE", "excerpt": "DIN reference"},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["organization"] is None


@pytest.mark.django_db
def test_read_only_sees_only_approved_visible_knowledge(organizations, roles) -> None:
    own, other = organizations
    approved = make_concept(code="APPROVED", organization=own)
    for status in ("SUGGESTED", "REJECTED", "DEPRECATED"):
        make_concept(code=status, organization=own, status=status)
    make_concept(code="FOREIGN", organization=other)
    _membership, client = create_member_client(organization=own, role=roles[Role.Code.READ_ONLY], username="reader")

    response = client.get("/api/v1/knowledge/concepts")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["results"]] == [str(approved.id)]
    assert client.post("/api/v1/knowledge/concepts", {}, format="json").status_code == 403


@pytest.mark.django_db
def test_other_organization_concept_relation_and_evidence_are_invisible(organizations, roles) -> None:
    own, other = organizations
    subject = make_concept(code="FOREIGN_GEAR", organization=other)
    target = make_concept(code="FOREIGN_APP", concept_type="APPLICATION", organization=other)
    relation = create_test_knowledge(
        KnowledgeRelation,
        organization=other, subject_concept=subject, predicate="APPLIES_TO", object_concept=target, status="APPROVED"
    )
    evidence = create_test_knowledge(
        KnowledgeEvidence,
        organization=other, evidence_type="HUMAN_ENTRY", excerpt="secret", status="APPROVED"
    )
    _membership, client = create_member_client(organization=own, role=roles[Role.Code.ADMINISTRATOR], username="admin-own")

    assert client.get(f"/api/v1/knowledge/concepts/{subject.id}").status_code == 404
    assert relation.id not in {uuid.UUID(item["id"]) for item in client.get("/api/v1/knowledge/relations").json()["results"]}
    assert evidence.id not in {uuid.UUID(item["id"]) for item in client.get("/api/v1/knowledge/evidence").json()["results"]}


@pytest.mark.django_db
def test_concept_evidence_links_accept_visible_and_reject_foreign_evidence(organizations, roles) -> None:
    own, other = organizations
    own_evidence = create_test_knowledge(
        KnowledgeEvidence,
        organization=own, evidence_type="HUMAN_ENTRY", excerpt="own", status="APPROVED"
    )
    foreign_evidence = create_test_knowledge(
        KnowledgeEvidence,
        organization=other, evidence_type="HUMAN_ENTRY", excerpt="foreign", status="APPROVED"
    )
    _membership, client = create_member_client(organization=own, role=roles[Role.Code.OPERATOR], username="operator-evidence")
    payload = {
        "concept_type": "PRODUCT_TYPE", "code": "EVIDENCED", "label_zh": "证据", "label_en": "Evidenced",
    }

    accepted = client.post(
        "/api/v1/knowledge/concepts", {**payload, "evidence": [str(own_evidence.id)]}, format="json"
    )
    rejected = client.post(
        "/api/v1/knowledge/concepts", {**payload, "code": "FOREIGN_EVIDENCE", "evidence": [str(foreign_evidence.id)]}, format="json"
    )

    assert accepted.status_code == 201
    assert accepted.json()["evidence"] == [str(own_evidence.id)]
    assert rejected.status_code == 400
    assert "evidence" in rejected.json()["errors"]


@pytest.mark.django_db
def test_reject_api_requires_comment_and_creates_matching_audit(organizations, roles) -> None:
    own, _ = organizations
    membership, client = create_member_client(organization=own, role=roles[Role.Code.REVIEWER], username="reviewer-reject")
    concept = make_concept(code="REJECT_API", organization=own, status="SUGGESTED")

    assert client.post(f"/api/v1/knowledge/concepts/{concept.id}/reject", {"comment": " "}, format="json").status_code == 400
    rejected = client.post(
        f"/api/v1/knowledge/concepts/{concept.id}/reject", {"comment": "Duplicate concept"}, format="json"
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert ApprovalRecord.objects.filter(object_id=concept.id, actor=membership.user, action="REJECT").exists()
    assert AuditLog.objects.filter(object_id=concept.id, actor=membership.user, action="REJECT").exists()


@pytest.mark.django_db
def test_resolve_api_returns_disambiguation_contract(organizations, roles) -> None:
    own, _ = organizations
    _membership, client = create_member_client(organization=own, role=roles[Role.Code.READ_ONLY], username="reader-resolve")
    response = client.post("/api/v1/knowledge/resolve", {"text": "unknown", "language": "en"}, format="json")

    assert response.status_code == 200
    assert response.json() == {"ambiguous": False, "selected": None, "candidates": []}


@pytest.mark.django_db
def test_builtin_role_upsert_adds_knowledge_permissions_to_existing_installations() -> None:
    stale, _ = Role.objects.update_or_create(
        code=Role.Code.OPERATOR,
        defaults={"name": "Operator", "permissions": ["memberships.read"]},
    )

    updated = Role.objects.create_operator()

    assert updated.id == stale.id
    assert "knowledge.create" in updated.permissions
    assert "knowledge.read" in updated.permissions


@pytest.mark.django_db
def test_openapi_documents_task_five_paths_envelopes_and_action_statuses() -> None:
    schema = APIClient().get("/api/v1/schema").json()
    required = {
        "/api/v1/knowledge/concepts",
        "/api/v1/knowledge/concepts/{concept_id}",
        "/api/v1/knowledge/concepts/{concept_id}/submit-review",
        "/api/v1/knowledge/concepts/{concept_id}/approve",
        "/api/v1/knowledge/concepts/{concept_id}/reject",
        "/api/v1/knowledge/concepts/{concept_id}/deprecate",
        "/api/v1/knowledge/relations",
        "/api/v1/knowledge/aliases",
        "/api/v1/knowledge/evidence",
        "/api/v1/knowledge/resolve",
    }
    assert required <= set(schema["paths"])
    assert schema["paths"]["/api/v1/knowledge/concepts"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("KnowledgeConceptList")
    assert "201" in schema["paths"]["/api/v1/knowledge/concepts"]["post"]["responses"]
    reject_responses = schema["paths"]["/api/v1/knowledge/concepts/{concept_id}/reject"]["post"]["responses"]
    assert {"200", "400", "403", "404"} <= set(reject_responses)
    relation_approve = schema["paths"]["/api/v1/knowledge/relations/{relation_id}/approve"]["post"]
    assert relation_approve["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("KnowledgeRelation")


@pytest.mark.django_db
def test_alias_approval_conflict_is_client_error_without_version_or_audit(organizations, roles) -> None:
    own, _ = organizations
    first_concept = make_concept(code="ALIAS_FIRST", organization=own)
    second_concept = make_concept(code="ALIAS_SECOND", organization=own)
    first = KnowledgeAlias.objects.create(
        organization=own, concept=first_concept, language="en", alias="same term", status="SUGGESTED"
    )
    second = KnowledgeAlias.objects.create(
        organization=own, concept=second_concept, language="en", alias="  SAME   TERM ", status="SUGGESTED"
    )
    _membership, client = create_member_client(
        organization=own, role=roles[Role.Code.REVIEWER], username="reviewer-alias-conflict"
    )
    assert client.post(f"/api/v1/knowledge/aliases/{first.id}/approve", {}, format="json").status_code == 200

    client.raise_request_exception = False
    response = client.post(f"/api/v1/knowledge/aliases/{second.id}/approve", {}, format="json")

    second.refresh_from_db()
    assert response.status_code == 400
    assert response.json() == {
        "errors": {"alias": ["An approved alias with this scope, language, and normalized value already exists."]},
        "code": "http_400",
        "message": "The request contains invalid fields.",
        "recovery_action": "Correct the request and try again.",
    }
    assert second.status == "SUGGESTED"
    assert second.version == 1
    assert not ApprovalRecord.objects.filter(object_id=second.id).exists()
    assert not AuditLog.objects.filter(object_id=second.id).exists()


@pytest.mark.django_db
def test_runtime_validation_error_matches_documented_schema(organizations, roles) -> None:
    own, _ = organizations
    _membership, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="operator-error-contract"
    )

    response = client.post(
        "/api/v1/knowledge/concepts",
        {"concept_type": "NOT_A_TYPE", "code": "BAD", "label_zh": "坏", "label_en": "Bad"},
        format="json",
    )
    schema = APIClient().get("/api/v1/schema").json()

    assert response.status_code == 400
    assert set(response.json()) == {"errors", "code", "message", "recovery_action"}
    assert isinstance(response.json()["errors"]["concept_type"], list)
    documented = schema["paths"]["/api/v1/knowledge/concepts"]["post"]["responses"]["400"]
    refs = {
        item["$ref"].rsplit("/", 1)[-1]
        for item in documented["content"]["application/json"]["schema"]["allOf"]
    }
    assert refs == {"ApiError", "KnowledgeValidationError"}


@pytest.mark.django_db
@pytest.mark.parametrize("resource", ["concepts", "relations"])
def test_knowledge_lists_prefetch_evidence_with_bounded_queries(
    organizations, roles, django_assert_num_queries, resource
) -> None:
    own, _ = organizations
    evidence = create_test_knowledge(
        KnowledgeEvidence, organization=own, evidence_type="HUMAN_ENTRY", excerpt="shared", status="APPROVED"
    )
    products = [make_concept(code=f"QUERY_{index}", organization=own) for index in range(4)]
    for product in products:
        product.evidence.add(evidence)
    if resource == "relations":
        application = make_concept(code="QUERY_APP", concept_type="APPLICATION", organization=own)
        for product in products:
            relation = create_test_knowledge(
                KnowledgeRelation, organization=own, subject_concept=product, predicate="APPLIES_TO",
                object_concept=application, status="APPROVED",
            )
            relation.evidence.add(evidence)
    _membership, client = create_member_client(
        organization=own, role=roles[Role.Code.ADMINISTRATOR], username=f"query-{resource}"
    )

    with django_assert_num_queries(5):
        response = client.get(f"/api/v1/knowledge/{resource}")

    assert response.status_code == 200
    assert len(response.json()["results"]) >= 4
