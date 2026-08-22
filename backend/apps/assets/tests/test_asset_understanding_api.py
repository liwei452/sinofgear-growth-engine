import pytest
from django.test import override_settings

from apps.ai.models import PromptVersion
from apps.ai.services import PromptVersionService
from apps.assets.ai_extraction import FACT_RESULT_SCHEMA
from apps.assets.services import upload_asset

from .conftest import create_member_client, make_product, mp4_bytes
from .test_asset_understanding_service import _upload, labeled_pdf
from .test_asset_upload import ChunkOnlyUpload


@pytest.fixture(autouse=True)
def asset_prompt_contract():
    if not PromptVersion.objects.filter(
        purpose="ASSET_UNDERSTAND", code="asset-understand-evidence-v1"
    ).exists():
        PromptVersionService.create(
            purpose="ASSET_UNDERSTAND",
            code="asset-understand-evidence-v1",
            provider="system",
            model="provider-agnostic",
            template="Extract only literal product facts with exact page and excerpt evidence.",
            output_schema=FACT_RESULT_SCHEMA,
            status=PromptVersion.Status.PUBLISHED,
        )


@pytest.mark.django_db(transaction=True)
def test_understanding_api_starts_lists_and_reviews_a_fact(organizations, roles) -> None:
    own, _ = organizations
    membership, client = create_member_client(
        organization=own, role=roles["ADMINISTRATOR"], username="understand-api"
    )
    asset = _upload(
        own,
        membership.user,
        labeled_pdf(),
        mime="application/pdf",
        kind="DOCUMENT",
        filename="api-facts.pdf",
    )
    product = make_product(own, name="API gear")

    started = client.post(
        f"/api/v1/assets/{asset.id}/understanding",
        {"product_id": str(product.id)},
        format="json",
    )

    assert started.status_code == 200
    assert started.json()["provider_label"] == "Fake Provider · 本地演示"
    completed = client.get(f"/api/v1/assets/{asset.id}/understanding")
    assert completed.json()["job"]["status"] == "SUCCEEDED"
    fact = next(item for item in completed.json()["facts"] if item["field_name"] == "accuracy")
    reviewed = client.post(
        f"/api/v1/assets/facts/{fact['id']}/review",
        {"decision": "APPROVE", "note": "Source checked"},
        format="json",
    )
    refreshed = client.get(f"/api/v1/assets/{asset.id}/understanding")

    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "VERIFIED"
    assert next(item for item in refreshed.json()["facts"] if item["id"] == fact["id"])[
        "review_status"
    ] == "VERIFIED"


@pytest.mark.django_db(transaction=True)
def test_understanding_api_hides_cross_org_products_and_facts(organizations, roles) -> None:
    own, other = organizations
    own_membership, own_client = create_member_client(
        organization=own, role=roles["ADMINISTRATOR"], username="understand-own"
    )
    _, other_client = create_member_client(
        organization=other, role=roles["ADMINISTRATOR"], username="understand-other"
    )
    asset = _upload(
        own,
        own_membership.user,
        labeled_pdf(),
        mime="application/pdf",
        kind="DOCUMENT",
        filename="private.pdf",
    )
    own_product = make_product(own, name="Own product")
    foreign_product = make_product(other, name="Foreign product")

    foreign_start = own_client.post(
        f"/api/v1/assets/{asset.id}/understanding",
        {"product_id": str(foreign_product.id)},
        format="json",
    )
    started = own_client.post(
        f"/api/v1/assets/{asset.id}/understanding",
        {"product_id": str(own_product.id)},
        format="json",
    )
    assert started.status_code == 200
    completed = own_client.get(f"/api/v1/assets/{asset.id}/understanding")
    fact_id = completed.json()["facts"][0]["id"]

    assert foreign_start.status_code == 404
    assert other_client.get(f"/api/v1/assets/{asset.id}/understanding").status_code == 404
    assert other_client.post(
        f"/api/v1/assets/facts/{fact_id}/review",
        {"decision": "APPROVE"},
        format="json",
    ).status_code == 404


@pytest.mark.django_db
def test_understanding_api_rejects_video_without_creating_a_job(organizations, roles) -> None:
    own, _ = organizations
    membership, client = create_member_client(
        organization=own, role=roles["ADMINISTRATOR"], username="understand-video"
    )
    upload = ChunkOnlyUpload([mp4_bytes(b"video")])
    upload.name = "video.mp4"
    upload.content_type = "video/mp4"
    asset = upload_asset(
        organization=own,
        creator=membership.user,
        upload=upload,
        asset_type="VIDEO",
    )
    product = make_product(own, name="Video product")

    response = client.post(
        f"/api/v1/assets/{asset.id}/understanding",
        {"product_id": str(product.id)},
        format="json",
    )

    assert response.status_code == 400
    assert "PDF" in str(response.json())


@pytest.mark.django_db
@override_settings(PRODUCT_AI_PROVIDER="deepseek", PRODUCT_AI_MODEL="deepseek-chat")
def test_understanding_api_requires_explicit_consent_before_deepseek(
    organizations, roles, monkeypatch,
) -> None:
    own, _ = organizations
    membership, client = create_member_client(
        organization=own, role=roles["ADMINISTRATOR"], username="understand-consent-api"
    )
    asset = _upload(
        own,
        membership.user,
        labeled_pdf(),
        mime="application/pdf",
        kind="DOCUMENT",
        filename="consent-api.pdf",
    )
    product = make_product(own, name="Consent API gear")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-never-persist")

    response = client.post(
        f"/api/v1/assets/{asset.id}/understanding",
        {"product_id": str(product.id), "external_text_consent": False},
        format="json",
    )

    assert response.status_code == 400
    assert "Confirm that bounded PDF text" in str(response.json())
