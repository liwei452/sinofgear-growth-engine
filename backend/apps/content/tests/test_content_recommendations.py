import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Product
from apps.content.models import ContentRecommendation, ContentRecommendationOption
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService


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
