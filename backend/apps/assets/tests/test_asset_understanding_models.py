from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.assets.models import ProductEvidenceFact
from apps.assets.services import upload_asset
from apps.jobs.models import Job
from apps.jobs.services import JobService
from integrations.storage.memory_storage import MemoryObjectStorage

from .conftest import make_product, png_bytes
from .test_asset_upload import ChunkOnlyUpload


def _asset(organization, username: str):
    creator = get_user_model().objects.create_user(username=username)
    return upload_asset(
        organization=organization,
        creator=creator,
        upload=ChunkOnlyUpload([png_bytes(username.encode())]),
        asset_type="IMAGE",
        storage=MemoryObjectStorage(),
    )


@pytest.mark.django_db
def test_asset_understanding_job_type_and_fact_defaults_are_auditable(organizations) -> None:
    own, _ = organizations
    asset = _asset(own, "fact-defaults")
    product = make_product(own, name="Helical gear")
    job = JobService.create(
        organization=own,
        job_type=Job.Type.ASSET_UNDERSTAND,
        input_snapshot={"asset_id": str(asset.id), "product_id": str(product.id)},
    )

    fact = ProductEvidenceFact.objects.create(
        organization=own,
        product=product,
        asset=asset,
        job=job,
        category=ProductEvidenceFact.Category.PROCESS,
        field_name="process",
        value="Gear grinding",
        confidence=Decimal("0.9200"),
        source_page=1,
        source_region=[0.1, 0.2, 0.7, 0.1],
        source_excerpt="Process: Gear grinding",
        provider_label="Fake Provider · 本地演示",
    )

    assert fact.review_status == ProductEvidenceFact.ReviewStatus.SUGGESTED
    assert fact.risk_level == ProductEvidenceFact.RiskLevel.STANDARD
    assert fact.is_demo is True


@pytest.mark.django_db
def test_fact_rejects_cross_organization_references(organizations) -> None:
    own, other = organizations
    asset = _asset(own, "fact-cross-org")
    foreign_product = make_product(other, name="Foreign gear")
    job = JobService.create(
        organization=own,
        job_type=Job.Type.ASSET_UNDERSTAND,
        input_snapshot={"asset_id": str(asset.id)},
    )

    with pytest.raises(ValidationError):
        ProductEvidenceFact.objects.create(
            organization=own,
            product=foreign_product,
            asset=asset,
            job=job,
            category="PRODUCT",
            field_name="product_name",
            value="Foreign gear",
            confidence=Decimal("0.8000"),
            source_excerpt="Product: Foreign gear",
            provider_label="Fake Provider · 本地演示",
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("confidence", "region"),
    [(Decimal("1.1000"), None), (Decimal("0.5000"), [0, 0, 1.1, 1])],
)
def test_fact_rejects_unbounded_confidence_or_region(
    organizations, confidence, region
) -> None:
    own, _ = organizations
    asset = _asset(own, f"fact-bounds-{confidence}-{region}")
    product = make_product(own, name="Bounded gear")
    job = JobService.create(
        organization=own,
        job_type=Job.Type.ASSET_UNDERSTAND,
        input_snapshot={"asset_id": str(asset.id)},
    )

    with pytest.raises(ValidationError):
        ProductEvidenceFact.objects.create(
            organization=own,
            product=product,
            asset=asset,
            job=job,
            category="SPECIFICATION",
            field_name="accuracy",
            value="DIN 6",
            confidence=confidence,
            source_region=region,
            source_excerpt="Accuracy: DIN 6",
            provider_label="Fake Provider · 本地演示",
        )
