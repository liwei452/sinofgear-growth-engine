import itertools

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
from apps.ai.services import PromptVersionService
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import (
    KnowledgeConcept,
    KnowledgeConceptEvidence,
    KnowledgeEvidence,
    KnowledgeStatus,
)
from apps.sources.models import (
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
)
from apps.sources.services import EvidenceService


@pytest.fixture
def organization():
    return Organization.objects.create(name="Lead Own", slug="lead-own")


@pytest.fixture
def other_organization():
    return Organization.objects.create(name="Lead Other", slug="lead-other")


@pytest.fixture
def user():
    return get_user_model().objects.create_user(username="lead-user")


def _make_source(*, organization, user, marker):
    target = MonitoringTarget.objects.create(
        organization=organization,
        target_type=MonitoringTarget.TargetType.POST,
        collection_mode=MonitoringTarget.CollectionMode.PASTE,
        platform="MANUAL",
        normalized_url=f"https://example.com/posts/{marker}",
        label=f"Lead source {marker}",
        created_by=user,
    )
    content = SourceContent.objects.create(
        organization=organization,
        monitoring_target=target,
        platform="MANUAL",
        external_id=f"post-{marker}",
        canonical_url=f"https://example.com/posts/{marker}",
        original_text="We need replacement helical gears, 200 pcs.",
        content_hash=marker * 64,
        created_by=user,
    )
    signal = SourceSignal.objects.create(
        organization=organization,
        monitoring_target=target,
        source_content=content,
        signal_type=SourceSignal.SignalType.COMMENT,
        platform="MANUAL",
        external_id=f"comment-{marker}",
        created_by=user,
    )
    evidence = EvidenceService.create(
        organization=organization,
        signal=signal,
        original_text=content.original_text,
        source_url=content.canonical_url,
        platform="MANUAL",
        collection_method=SourceEvidence.CollectionMethod.PASTE,
        public_published_at=timezone.now(),
        created_by=user,
        language="en",
    )
    return signal, evidence


@pytest.fixture
def source_pair(organization, user):
    return _make_source(organization=organization, user=user, marker="a")


@pytest.fixture
def signal(source_pair):
    return source_pair[0]


@pytest.fixture
def evidence(source_pair):
    return source_pair[1]


@pytest.fixture
def second_source_pair(organization, user):
    return _make_source(organization=organization, user=user, marker="c")


@pytest.fixture
def other_source_pair(other_organization, user):
    return _make_source(organization=other_organization, user=user, marker="b")


@pytest.fixture
def ai_run_factory(user):
    counter = itertools.count(1)

    def factory(
        organization,
        *,
        job_type=Job.Type.LEAD_ANALYZE,
        purpose="LEAD_ANALYZE",
        input_snapshot=None,
    ):
        number = next(counter)
        job = JobService.create(
            organization=organization,
            job_type=job_type,
            input_snapshot=input_snapshot or {"candidate": number},
            idempotency_key=f"lead-analyze-{organization.id}-{number}",
            created_by=user,
        )
        prompt = PromptVersionService.create(
            purpose=purpose,
            code=f"lead-test-{number}",
            provider="fake",
            model="fake-v1",
            template="Analyze public evidence.",
            output_schema={"type": "object"},
            status=PromptVersion.Status.PUBLISHED,
            created_by=user,
        )
        with ai_audit_writes():
            return AIRun.objects.create(
                organization=organization,
                job=job,
                job_attempt=job.attempt,
                prompt_version=prompt,
                provider="fake",
                model="fake-v1",
                input_snapshot=job.input_snapshot,
                status=AIRun.Status.SUCCEEDED,
                output_json={},
                started_at=timezone.now(),
                finished_at=timezone.now(),
            )

    return factory


@pytest.fixture
def analysis_snapshot():
    def factory(*, candidate, evidence, ontology_snapshot):
        evidence_rows = [
            {"id": str(item.id), "content_hash": item.content_hash}
            for item in evidence
        ]
        return {
            "organization_id": str(candidate.organization_id),
            "lead_candidate_id": str(candidate.id),
            "evidence": evidence_rows,
            "ontology_snapshot": ontology_snapshot,
        }

    return factory


@pytest.fixture
def approved_requirement(organization, user):
    with _test_fixture_writes():
        return KnowledgeConcept.objects.create(
            scope=KnowledgeConcept.Scope.ORGANIZATION,
            organization=organization,
            concept_type=KnowledgeConcept.ConceptType.REQUIREMENT,
            code="REQ_QUANTITY",
            label_zh="数量",
            label_en="Quantity",
            status=KnowledgeStatus.APPROVED,
            created_by=user,
        )


@pytest.fixture
def approved_capability_evidence(user):
    with _test_fixture_writes():
        return KnowledgeEvidence.objects.create(
            organization=None,
            evidence_type=KnowledgeEvidence.EvidenceType.STANDARD_REFERENCE,
            source_url="https://example.com/capabilities/helical-grinding",
            excerpt="Verified helical gear grinding capability.",
            status=KnowledgeStatus.APPROVED,
            created_by=user,
        )


@pytest.fixture
def approved_capability(user, approved_capability_evidence):
    with _test_fixture_writes():
        capability = KnowledgeConcept.objects.create(
            scope=KnowledgeConcept.Scope.SYSTEM,
            organization=None,
            concept_type=KnowledgeConcept.ConceptType.CAPABILITY,
            code="CAP_HELICAL_GRINDING",
            label_zh="斜齿轮磨削",
            label_en="Helical gear grinding",
            status=KnowledgeStatus.APPROVED,
            created_by=user,
        )
    KnowledgeConceptEvidence.objects.create(
        knowledgeconcept=capability,
        knowledgeevidence=approved_capability_evidence,
    )
    return capability


@pytest.fixture
def candidate(organization, signal, user):
    from apps.leads.models import LeadCandidate

    return LeadCandidate.objects.create(
        organization=organization,
        source_signal=signal,
        company_name="ABC Packaging",
        company_domain="HTTPS://EXAMPLE.COM/",
        country_hint="DE",
        created_by=user,
    )


@pytest.fixture
def insight_payload(
    approved_requirement, approved_capability, approved_capability_evidence, evidence
):
    def factory(*, intent=25, company_fit=20, specificity=15, capability_fit=10, recency=8):
        return {
            "dimensions": {
                "intent": intent,
                "company_fit": company_fit,
                "specificity": specificity,
                "capability_fit": capability_fit,
                "recency": recency,
            },
            "gates": {
                "traceable_source": True,
                "explicit_need_or_company_match": True,
                "capability_evidence": True,
                "audited_run": True,
                "ontology_snapshot": True,
            },
            "explanation": {
                "reasons": [
                    {"text": "Explicit replacement need", "evidence_ids": [str(evidence.id)]}
                ]
            },
            "extracted_requirement_values": [
                {"type": "quantity", "value": "200", "unit": "pcs"}
            ],
            "confidence": {"evidence": "0.9500", "company_match": "0.8000", "ai": "0.9000"},
            "ontology_snapshot": {
                "organization_id": str(evidence.organization_id),
                "concept_versions": [
                    {
                        "concept_id": str(concept.id),
                        "code": concept.code,
                        "concept_type": concept.concept_type,
                        "label_zh": concept.label_zh,
                        "label_en": concept.label_en,
                        "version": concept.version,
                        "status": concept.status,
                    }
                    for concept in (approved_requirement, approved_capability)
                ],
                "relation_versions": [],
                "evidence_references": [
                    {
                        "evidence_id": str(approved_capability_evidence.id),
                        "evidence_type": approved_capability_evidence.evidence_type,
                        "source_object_type": approved_capability_evidence.source_object_type,
                        "source_object_id": None,
                        "source_url": approved_capability_evidence.source_url,
                        "excerpt": approved_capability_evidence.excerpt,
                        "captured_at": None,
                        "version": approved_capability_evidence.version,
                        "status": approved_capability_evidence.status,
                    }
                ],
                "generated_at": "2026-08-10T00:00:00+00:00",
            },
            "requirements": [
                {
                    "requirement_concept": approved_requirement,
                    "capability_concept": approved_capability,
                    "capability_knowledge_evidence": approved_capability_evidence,
                    "extracted_value": "200",
                    "unit": "pcs",
                    "evidence": evidence,
                }
            ],
        }

    return factory


@pytest.fixture
def ai_run(ai_run_factory, candidate, evidence, insight_payload, analysis_snapshot):
    payload = insight_payload()
    return ai_run_factory(
        candidate.organization,
        input_snapshot=analysis_snapshot(
            candidate=candidate,
            evidence=[evidence],
            ontology_snapshot=payload["ontology_snapshot"],
        ),
    )
