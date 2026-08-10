from copy import deepcopy

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.identity.models import Membership, Role
from apps.leads.models import LeadCandidate
from apps.leads.schemas import lead_analysis_errors
from apps.leads.services import build_analysis_snapshot


def _authorize(user, organization):
    role = Role.objects.create_operator()
    return Membership.objects.create(
        user=user,
        organization=organization,
        role=role,
    )


def _valid_output(*, snapshot, evidence_id):
    requirement = next(
        row
        for row in snapshot["ontology_snapshot"]["concept_versions"]
        if row["concept_type"] == "REQUIREMENT"
    )
    capability = next(
        row
        for row in snapshot["ontology_snapshot"]["concept_versions"]
        if row["concept_type"] == "CAPABILITY"
    )
    knowledge_evidence_id = snapshot["capability_bindings"][0][
        "knowledge_evidence_ids"
    ][0]
    return {
        "company_name": "ABC Packaging",
        "company_domain": "example.com",
        "country_hint": "DE",
        "need_summary_zh": "需要 200 件替换斜齿轮。",
        "need_summary_en": "Needs 200 replacement helical gears.",
        "dimensions": {
            "intent": 30,
            "company_fit": 20,
            "specificity": 20,
            "capability_fit": 15,
            "recency": 8,
        },
        "requirements": [
            {
                "type": requirement["code"],
                "value": "200",
                "unit": "pcs",
                "evidence_ids": [str(evidence_id)],
            }
        ],
        "capability_matches": [
            {
                "capability_code": capability["code"],
                "knowledge_evidence_ids": [knowledge_evidence_id],
                "source_evidence_ids": [str(evidence_id)],
            }
        ],
        "reasons": [
            {
                "text": "The buyer states a quantity and replacement need.",
                "evidence_ids": [str(evidence_id)],
            }
        ],
        "confidence": {
            "intent": 0.95,
            "company_fit": 0.8,
            "capability": 0.9,
        },
        "insufficient_evidence": False,
    }


@pytest.mark.django_db
def test_snapshot_contains_only_authorized_linked_evidence_and_approved_ontology(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    _authorize(user, candidate.organization)

    snapshot = build_analysis_snapshot(
        candidate=candidate,
        evidence_ids=[evidence.id],
        actor=user,
    )

    candidate.refresh_from_db()
    assert candidate.status == LeadCandidate.Status.ANALYZING
    assert snapshot["organization_id"] == str(candidate.organization_id)
    assert snapshot["candidate"] == {
        "company_name": "ABC Packaging",
        "company_domain": "example.com",
        "country_hint": "DE",
    }
    assert snapshot["evidence"][0]["original_text"] == evidence.original_text
    assert snapshot["evidence"][0]["content_hash"] == evidence.content_hash
    assert snapshot["evidence"][0]["source_content_author_public_name"] == ""
    assert all(
        row["status"] == "APPROVED"
        for collection in ("concept_versions", "relation_versions", "evidence_references")
        for row in snapshot["ontology_snapshot"][collection]
    )
    assert {row["code"] for row in snapshot["ontology_snapshot"]["concept_versions"]} >= {
        approved_requirement.code,
        approved_capability.code,
    }


@pytest.mark.django_db
def test_snapshot_requires_active_authorized_membership(candidate, evidence, user):
    with pytest.raises(PermissionDenied):
        build_analysis_snapshot(
            candidate=candidate,
            evidence_ids=[evidence.id],
            actor=user,
        )


@pytest.mark.django_db
def test_snapshot_rejects_unlinked_or_foreign_evidence(
    candidate,
    second_source_pair,
    other_source_pair,
    user,
):
    _authorize(user, candidate.organization)
    for invalid_evidence in (second_source_pair[1], other_source_pair[1]):
        with pytest.raises(ValidationError):
            build_analysis_snapshot(
                candidate=candidate,
                evidence_ids=[invalid_evidence.id],
                actor=user,
            )


@pytest.mark.django_db
def test_output_schema_and_frozen_references_are_strict(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    _authorize(user, candidate.organization)
    snapshot = build_analysis_snapshot(
        candidate=candidate,
        evidence_ids=[evidence.id],
        actor=user,
    )
    output = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    assert lead_analysis_errors(output, snapshot=snapshot) == []

    mutations = []
    extra = deepcopy(output)
    extra["unexpected"] = True
    mutations.append(extra)
    empty_reason = deepcopy(output)
    empty_reason["reasons"][0]["evidence_ids"] = []
    mutations.append(empty_reason)
    unknown_evidence = deepcopy(output)
    unknown_evidence["requirements"][0]["evidence_ids"] = ["00000000-0000-0000-0000-000000000001"]
    mutations.append(unknown_evidence)
    unknown_capability = deepcopy(output)
    unknown_capability["capability_matches"][0]["capability_code"] = "CAP_UNKNOWN"
    mutations.append(unknown_capability)
    unknown_knowledge_evidence = deepcopy(output)
    unknown_knowledge_evidence["capability_matches"][0]["knowledge_evidence_ids"] = [
        "00000000-0000-0000-0000-000000000002"
    ]
    mutations.append(unknown_knowledge_evidence)
    score_too_high = deepcopy(output)
    score_too_high["dimensions"]["intent"] = 31
    mutations.append(score_too_high)

    assert all(lead_analysis_errors(value, snapshot=snapshot) for value in mutations)

    missing_fact_snapshot = deepcopy(snapshot)
    missing_fact_snapshot["candidate"]["company_domain"] = ""
    assert lead_analysis_errors(output, snapshot=missing_fact_snapshot)
