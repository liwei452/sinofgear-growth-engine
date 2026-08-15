import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Product
from apps.ai.models import PromptVersion
from apps.ai.services import PromptVersionService
from apps.content.models import ContentRecommendation, ContentRecommendationOption
from apps.content.recommendations import (
    ContentRecommendationError,
    RECOMMENDATION_SCHEMA,
    build_recommendation_input,
    validate_recommendation_output,
)
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.content.tasks import generate_content_recommendations_job


def _product(organization, name):
    return Product.objects.create(
        organization=organization,
        name_en=name,
        module_min="1.0000",
        module_max="2.0000",
        tooth_count_min=10,
        tooth_count_max=40,
        pressure_angle="20.000",
        manufacturing_capabilities=["hobbing"],
        inspection_capabilities=["CMM"],
        moq=1,
        status=Product.Status.ACTIVE,
    )


@pytest.fixture
def recommendation_context(db):
    organization = Organization.objects.create(name="Recommendation Org", slug="recommendation-org")
    actor = get_user_model().objects.create_user(username="recommendation-actor", password="x")
    product = _product(organization, "Precision gear")
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_RECOMMEND,
        input_snapshot={"product_ids": [str(product.id)]},
        idempotency_key="recommendation:v1",
        created_by=actor,
    )
    recommendation = ContentRecommendation.objects.create(
        organization=organization,
        job=job,
        input_snapshot=job.input_snapshot,
        provider_mode=ContentRecommendation.ProviderMode.FAKE_OFFLINE,
        status=ContentRecommendation.Status.QUEUED,
        created_by=actor,
    )
    return organization, actor, product, recommendation


@pytest.mark.django_db
def test_content_recommendation_job_type_is_available():
    assert Job.Type.CONTENT_RECOMMEND == "CONTENT_RECOMMEND"


def test_recommendation_option_rejects_cross_organization_product(recommendation_context):
    organization, _, _, recommendation = recommendation_context
    foreign = Organization.objects.create(name="Foreign Org", slug="foreign-recommendation-org")
    foreign_product = _product(foreign, "Foreign gear")
    option = ContentRecommendationOption(
        organization=organization,
        recommendation=recommendation,
        position=1,
        product=foreign_product,
        market_code="ID",
        language="id",
        customer_profile="Industrial distributor",
        channel_codes=["LINKEDIN"],
        theme="Verified gear manufacturing",
        rationale="Matches the selected market and verified process facts.",
        evidence=[],
        missing_information=[],
    )

    with pytest.raises(ValidationError, match="organization"):
        option.full_clean()


def test_recommendation_option_positions_are_unique(recommendation_context):
    organization, _, product, recommendation = recommendation_context
    values = dict(
        organization=organization,
        recommendation=recommendation,
        position=1,
        product=product,
        market_code="ID",
        language="id",
        customer_profile="Industrial distributor",
        channel_codes=["LINKEDIN"],
        theme="Verified gear manufacturing",
        rationale="Matches the selected market and verified process facts.",
        evidence=[],
        missing_information=[],
    )
    ContentRecommendationOption.objects.create(**values)

    with pytest.raises(IntegrityError), transaction.atomic():
        ContentRecommendationOption.objects.create(**values)


def _recommendation_payload(product_id, fact_ids):
    return {
        "options": [
            {
                "product_id": str(product_id),
                "market_code": market,
                "language": language,
                "customer_profile": profile,
                "channel_codes": ["LINKEDIN"],
                "theme": theme,
                "rationale": rationale,
                "fact_ids": [str(fact_id) for fact_id in fact_ids],
                "missing_information": [],
            }
            for market, language, profile, theme, rationale in (
                ("ID", "id", "Industrial distributor", "Process reliability", "Verified process fit."),
                ("ZA", "en", "Mining equipment maker", "Custom gear supply", "Verified product fit."),
                ("VN", "vi", "Machinery manufacturer", "Precision component", "Verified application fit."),
            )
        ]
    }


def test_recommendation_output_rejects_unknown_fact(recommendation_context):
    _, _, product, _ = recommendation_context
    allowed = {
        "product_ids": [str(product.id)],
        "fact_ids": ["11111111-1111-4111-8111-111111111111"],
        "market_codes": ["ID", "ZA", "VN"],
        "channel_codes": ["LINKEDIN"],
        "languages": ["id", "en", "vi"],
    }
    payload = _recommendation_payload(
        product.id, ["22222222-2222-4222-8222-222222222222"]
    )

    with pytest.raises(ContentRecommendationError, match="fact"):
        validate_recommendation_output(payload, allowed)


def test_recommendation_output_normalizes_exactly_three_options(recommendation_context):
    _, _, product, _ = recommendation_context
    fact_id = "11111111-1111-4111-8111-111111111111"
    allowed = {
        "product_ids": [str(product.id)],
        "fact_ids": [fact_id],
        "market_codes": ["ID", "ZA", "VN"],
        "channel_codes": ["LINKEDIN"],
        "languages": ["id", "en", "vi"],
    }

    result = validate_recommendation_output(
        _recommendation_payload(product.id, [fact_id]), allowed
    )

    assert [option["position"] for option in result] == [1, 2, 3]
    assert result[0]["market_code"] == "ID"
    assert result[0]["evidence"] == [{"fact_id": fact_id}]


def test_recommendation_input_reports_missing_verified_facts(recommendation_context):
    organization, _, _, _ = recommendation_context

    with pytest.raises(ContentRecommendationError, match="verified product facts"):
        build_recommendation_input(organization.id)


def test_fake_recommendation_job_persists_three_options(recommendation_context):
    organization, actor, product, _ = recommendation_context
    fact_id = "11111111-1111-4111-8111-111111111111"
    snapshot = {
        "organization_id": str(organization.id),
        "products": [{"id": str(product.id), "name": product.name_en}],
        "facts": [{"id": fact_id, "product_id": str(product.id), "field": "process", "value": "hobbing"}],
        "markets": [
            {"code": "ID", "label": "Indonesia"},
            {"code": "ZA", "label": "South Africa"},
            {"code": "VN", "label": "Vietnam"},
        ],
        "channels": ["LINKEDIN"],
        "languages": ["en", "id", "vi"],
    }
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_RECOMMEND,
        input_snapshot=snapshot,
        idempotency_key="recommendation:execution:v1",
        created_by=actor,
    )
    recommendation = ContentRecommendation.objects.create(
        organization=organization,
        job=job,
        input_snapshot=snapshot,
        provider_mode=ContentRecommendation.ProviderMode.FAKE_OFFLINE,
        created_by=actor,
    )
    prompt = PromptVersionService.create(
        purpose="CONTENT_RECOMMEND",
        code="content-recommend-test",
        provider="fake",
        model="fake-v1",
        template="Recommend three evidence-backed directions.",
        output_schema=RECOMMENDATION_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
    )

    result = generate_content_recommendations_job(str(job.id), str(prompt.id))
    run = job.ai_runs.get()

    recommendation.refresh_from_db()
    job.refresh_from_db()
    assert run.status == run.Status.SUCCEEDED, run.error
    assert result["status"] == run.Status.SUCCEEDED
    assert recommendation.status == ContentRecommendation.Status.READY
    assert recommendation.options.count() == 3
    assert job.result_reference == {
        "type": "content_recommendation",
        "id": str(recommendation.id),
    }
