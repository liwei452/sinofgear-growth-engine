import json
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from apps.assets.models import AssetProductLink, MaterialAsset, ProductEvidenceFact
from apps.ai.models import AIRun, PromptVersion
from apps.ai.orchestration import execute_generation_job
from apps.ai.services import PromptVersionService
from apps.content.models import MasterContent
from apps.content.payloads import CONTENT_OUTPUT_SCHEMA_V2
from apps.content.services import finalize_master_result
from apps.campaigns.models import Campaign, ContentBriefConceptLink
from apps.campaigns.services import (
    build_content_generation_input,
    create_content_brief,
    mark_content_brief_ready,
    revise_content_brief,
)
from apps.campaigns.generation_schema import generation_input_errors
from apps.catalog.models import Product
from apps.knowledge.models import (
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeGraphLock,
    KnowledgeRelation,
)
from apps.knowledge.guards import _test_fixture_writes
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.platforms.models import Platform
from integrations.ai.providers import provider_registry

from .conftest import (
    make_asset,
    make_concept,
    make_platform,
    make_product,
    valid_brief_values,
)


def make_ready_brief(organization, user):
    product = make_product(organization)
    platform = make_platform()
    concept = make_concept(
        organization, concept_type="INDUSTRY", code="PRECISION_ENGINEERING"
    )
    asset = make_asset(organization, user)
    AssetProductLink.objects.create(
        organization=organization, asset=asset, product=product
    )
    campaign = Campaign.objects.create(organization=organization, name="Launch")
    brief = create_content_brief(
        organization=organization,
        campaign=campaign,
        creator=user,
        values=valid_brief_values(),
        product_ids=[product.id],
        asset_ids=[asset.id],
        platform_ids=[platform.id],
        concept_links=[{"role": "TARGET_INDUSTRY", "concept_id": concept.id}],
    )
    return (
        mark_content_brief_ready(brief.id, reviewer=user),
        campaign,
        product,
        asset,
        platform,
        concept,
    )


class WrongLanguageContentProvider:
    def generate(self, *, prompt, schema):
        del prompt, schema
        return {
            "schema_version": 2,
            "language": "de",
            "title": "Wrong language",
            "body": "Wrong language master body",
            "cta": "Kontakt",
            "landing_page_url": "https://example.com/gears",
            "concept_codes": ["PRECISION_ENGINEERING"],
            "evidence_fact_ids": [],
            "platform_variants": [{
                "platform_code": "LINKEDIN",
                "language": "de",
                "title": "LinkedIn wrong language",
                "body": "LinkedIn wrong language body",
                "cta": "Kontakt",
                "landing_page_url": "https://example.com/gears",
                "hashtags": ["#PrecisionGears"],
                "evidence_fact_ids": [],
            }],
        }


@pytest.mark.django_db
def test_generation_rejects_schema_valid_output_in_the_wrong_publication_language(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    ready, *_ = make_ready_brief(own, campaign_user)
    snapshot = build_content_generation_input(ready.id).to_dict()
    prompt = PromptVersionService.create(
        purpose="CONTENT_GENERATE",
        code="target-language-v2",
        provider="wrong-language-content",
        model="test-v1",
        template="Generate reviewed multichannel content.",
        output_schema=CONTENT_OUTPUT_SCHEMA_V2,
        status=PromptVersion.Status.PUBLISHED,
    )
    provider_registry.register(
        "wrong-language-content", WrongLanguageContentProvider(), replace=True
    )
    job = JobService.create(
        organization=own,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=snapshot,
    )

    run = execute_generation_job(
        job.id,
        prompt_version_id=prompt.id,
        provider_code="wrong-language-content",
        result_writer=finalize_master_result,
    )

    job.refresh_from_db()
    assert run.status == AIRun.Status.FAILED
    assert job.status == Job.Status.FAILED
    assert not MasterContent.objects.filter(generation_job=job).exists()


@pytest.mark.django_db
def test_revision_is_new_draft_and_preserves_ready_source(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    ready, _, product, asset, platform, concept = make_ready_brief(own, campaign_user)

    revision = revise_content_brief(ready.id, creator=campaign_user)
    ready.refresh_from_db()

    assert ready.status == "READY"
    assert revision.status == "DRAFT"
    assert revision.previous_version_id == ready.id
    assert revision.version == ready.version + 1
    assert set(revision.product_links.values_list("product_id", flat=True)) == {product.id}
    assert set(revision.asset_links.values_list("asset_id", flat=True)) == {asset.id}
    assert set(revision.platform_links.values_list("platform_id", flat=True)) == {platform.id}
    assert set(revision.concept_links.values_list("concept_id", flat=True)) == {concept.id}


@pytest.mark.django_db
def test_generation_input_is_complete_frozen_and_json_serializable(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    ready, campaign, product, asset, platform, concept = make_ready_brief(
        own, campaign_user
    )

    snapshot = build_content_generation_input(ready.id)
    before = snapshot.to_dict()

    Product.objects.filter(pk=product.id).update(name_en="Changed later")
    MaterialAsset.objects.filter(pk=asset.id).update(tags=["changed"])
    Platform.objects.filter(pk=platform.id).update(name="Changed later")
    KnowledgeConcept.objects.filter(pk=concept.id).update(label_en="Changed later")

    assert snapshot.organization_id == own.id
    assert snapshot.brief_id == ready.id
    assert snapshot.campaign_id == campaign.id
    assert snapshot.products[0].name_en == "Precision gear"
    assert snapshot.assets[0].checksum == "a" * 64
    assert snapshot.assets[0].product_ids == (product.id,)
    assert snapshot.target_platforms[0].capability_codes == ("PUBLISH",)
    assert {item.concept_id for item in snapshot.ontology_snapshot.concept_versions} == {
        concept.id
    }
    assert snapshot.to_dict() == before
    assert before["schema_version"] == "1.0"
    assert generation_input_errors(before) == []
    assert "storage_key" not in before["assets"][0]
    json.dumps(before)


@pytest.mark.django_db
def test_generation_input_includes_only_human_verified_product_facts(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    ready, _, product, asset, _, _ = make_ready_brief(own, campaign_user)
    understanding_job = JobService.create(
        organization=own,
        job_type=Job.Type.ASSET_UNDERSTAND,
        input_snapshot={"asset_id": str(asset.id), "product_id": str(product.id)},
    )
    common = dict(
        organization=own, product=product, asset=asset, job=understanding_job,
        category="PROCESS", confidence="0.9000", source_page=1,
        provider_label="Fake Provider · 本地演示", is_demo=True,
    )
    verified = ProductEvidenceFact.objects.create(
        **common, field_name="process", value="Gear grinding",
        source_excerpt="Process: Gear grinding", review_status="VERIFIED",
        reviewed_by=campaign_user, reviewed_at=ready.reviewed_at,
    )
    ProductEvidenceFact.objects.create(
        **common, field_name="material", value="Invented steel",
        source_excerpt="Material: Invented steel", review_status="REJECTED",
        reviewed_by=campaign_user, reviewed_at=ready.reviewed_at,
    )

    snapshot = build_content_generation_input(ready.id).to_dict()

    assert snapshot["verified_product_facts"] == [{
        "fact_id": str(verified.id), "product_id": str(product.id),
        "field_name": "process", "value": "Gear grinding", "category": "PROCESS",
        "source_asset_id": str(asset.id), "source_page": 1,
        "source_filename": asset.original_filename,
        "source_excerpt": "Process: Gear grinding", "is_demo": True,
    }]
    assert generation_input_errors(snapshot) == []


@pytest.mark.django_db
def test_ready_brief_without_assets_builds_valid_input_and_runs_deterministically(
    campaign_organizations, campaign_user
):
    organization, _ = campaign_organizations
    product = make_product(organization)
    platform = make_platform()
    concept = make_concept(
        organization, concept_type="INDUSTRY", code="NO_ASSET_INDUSTRY"
    )
    campaign = Campaign.objects.create(organization=organization, name="No asset")
    brief = create_content_brief(
        organization=organization,
        campaign=campaign,
        creator=campaign_user,
        values=valid_brief_values(),
        product_ids=[product.id],
        asset_ids=[],
        platform_ids=[platform.id],
        concept_links=[{"role": "TARGET_INDUSTRY", "concept_id": concept.id}],
    )
    ready = mark_content_brief_ready(brief.id, reviewer=campaign_user)
    snapshot = build_content_generation_input(ready.id).to_dict()
    prompt = PromptVersionService.create(
        purpose="CONTENT_GENERATE",
        code="no-asset-content",
        provider="fake",
        model="fake-v1",
        template="{product_name}|{target_country}|{target_platform}|{cta}|{concept_codes}",
        output_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "cta": {"type": "string"},
                "concept_codes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "body", "cta", "concept_codes"],
            "additionalProperties": False,
        },
        status=PromptVersion.Status.PUBLISHED,
    )
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=snapshot,
    )

    first = execute_generation_job(
        job.id, prompt_version_id=prompt.id, result_writer=finalize_master_result
    )
    duplicate = execute_generation_job(
        job.id, prompt_version_id=prompt.id, result_writer=finalize_master_result
    )

    assert snapshot["assets"] == []
    assert generation_input_errors(snapshot) == []
    assert first.status == AIRun.Status.SUCCEEDED
    assert duplicate.pk == first.pk
    assert duplicate.output_json == first.output_json
    job.refresh_from_db()
    master = MasterContent.objects.get(generation_job=job)
    assert master.status == MasterContent.Status.DRAFT
    assert master.ai_run == first
    assert job.result_reference == {
        "type": "master_content", "id": str(master.id), "version": 1,
    }


@pytest.mark.django_db
def test_generation_input_fails_closed_for_draft_or_corrupted_live_reference(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    draft_campaign = Campaign.objects.create(organization=own, name="Draft")
    draft = create_content_brief(
        organization=own,
        campaign=draft_campaign,
        creator=campaign_user,
        values=valid_brief_values(),
        product_ids=[],
        asset_ids=[],
        platform_ids=[],
        concept_links=[],
    )
    with pytest.raises(ValidationError, match="READY"):
        build_content_generation_input(draft.id)

    ready, _, _, _, _, concept = make_ready_brief(own, campaign_user)
    with _test_fixture_writes():
        KnowledgeConcept.objects.filter(pk=concept.id).update(status="DEPRECATED")

    with pytest.raises(ValidationError, match="approved"):
        build_content_generation_input(ready.id)


@pytest.mark.django_db
def test_ready_relation_rows_cannot_be_mutated_or_deleted(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    ready, _, _, _, _, _ = make_ready_brief(own, campaign_user)
    link = ContentBriefConceptLink.objects.get(brief=ready)

    with pytest.raises(ValidationError, match="immutable"):
        ContentBriefConceptLink.objects.filter(pk=link.pk).update(role="APPLICATION")
    with pytest.raises(Exception):
        ContentBriefConceptLink.objects.filter(pk=link.pk).delete()


@pytest.mark.django_db
def test_generation_snapshot_locks_expanded_ontology_rows_and_evidence_associations(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    ready, _, _, _, _, root = make_ready_brief(own, campaign_user)
    target = make_concept(
        own, concept_type="PURCHASE_INTENT", code="LOCKED_EXPANSION"
    )
    with _test_fixture_writes():
        relation = KnowledgeRelation.objects.create(
            organization=own,
            subject_concept=root,
            predicate="INDICATES_PURCHASE_INTENT",
            object_concept=target,
            status="APPROVED",
        )
        evidence = KnowledgeEvidence.objects.create(
            organization=own,
            evidence_type="HUMAN_ENTRY",
            excerpt="Locked evidence",
            status="APPROVED",
        )
    root.evidence.add(evidence)
    relation.evidence.add(evidence)
    concept_through = KnowledgeConcept.evidence.through
    relation_through = KnowledgeRelation.evidence.through

    managers = [
        KnowledgeGraphLock.objects,
        KnowledgeConcept.objects,
        KnowledgeRelation.objects,
        KnowledgeEvidence.objects,
        concept_through.objects,
        relation_through.objects,
    ]
    patches = [
        patch.object(manager, "select_for_update", wraps=manager.select_for_update)
        for manager in managers
    ]
    mocks = [item.start() for item in patches]
    try:
        snapshot = build_content_generation_input(ready.id)
    finally:
        for item in reversed(patches):
            item.stop()

    assert {item.concept_id for item in snapshot.ontology_snapshot.concept_versions} >= {
        root.id,
        target.id,
    }
    assert all(mock.called for mock in mocks)
