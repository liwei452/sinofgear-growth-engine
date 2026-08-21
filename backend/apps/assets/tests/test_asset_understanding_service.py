from io import BytesIO

import pytest
from django.db import connection
from django.test import override_settings
from django.contrib.auth import get_user_model
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject

from apps.assets.models import ProductEvidenceFact
from apps.assets.services import upload_asset
from apps.assets.understanding import review_fact, start_understanding
from apps.ai.models import AIRun, PromptVersion
from apps.ai.prompt_catalog import PromptCatalogEntryMissing
from apps.ai.services import PromptVersionService
from apps.assets.ai_extraction import FACT_RESULT_SCHEMA
from apps.ai.provider_config import ProductAIRuntime
from apps.jobs.models import Job

from .conftest import make_product, png_bytes
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


def labeled_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = StreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 72 720 Td "
        b"(Product: Custom helical gear) Tj 0 -18 Td "
        b"(Process: Gear grinding) Tj 0 -18 Td "
        b"(Accuracy: DIN 6) Tj 0 -18 Td "
        b"(Lead time: 4-6 weeks) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _upload(organization, creator, content: bytes, *, mime: str, kind: str, filename: str):
    upload = ChunkOnlyUpload([content])
    upload.name = filename
    upload.content_type = mime
    return upload_asset(
        organization=organization,
        creator=creator,
        upload=upload,
        asset_type=kind,
    )


@pytest.mark.django_db
def test_pdf_understanding_persists_literal_evidence_and_high_risk_facts(organizations) -> None:
    own, _ = organizations
    actor = get_user_model().objects.create_user(username="understand-pdf")
    asset = _upload(
        own, actor, labeled_pdf(), mime="application/pdf", kind="DOCUMENT", filename="facts.pdf"
    )
    product = make_product(own, name="Imported gear")

    result = start_understanding(asset=asset, product=product, actor=actor)

    assert result.job.status == Job.Status.SUCCEEDED
    assert result.provider_label == "Fake Provider · 本地演示"
    assert result.is_partial is False
    facts = {fact.field_name: fact for fact in result.facts}
    assert facts["process"].value == "Gear grinding"
    assert facts["process"].source_page == 1
    assert facts["process"].source_excerpt == "Process: Gear grinding"
    assert facts["accuracy"].risk_level == ProductEvidenceFact.RiskLevel.HIGH
    assert facts["lead_time"].risk_level == ProductEvidenceFact.RiskLevel.HIGH
    assert all(fact.ai_run_id for fact in result.facts)
    run = AIRun.objects.get(job=result.job)
    assert run.prompt_version.code == "asset-understand-evidence-v1"
    assert run.prompt_version.provider == "system"
    assert run.prompt_version.model == "provider-agnostic"


@pytest.mark.django_db
def test_image_understanding_is_partial_and_does_not_invent_visual_facts(organizations) -> None:
    own, _ = organizations
    actor = get_user_model().objects.create_user(username="understand-image")
    asset = _upload(
        own, actor, png_bytes(b"not-a-product-claim"), mime="image/png", kind="IMAGE", filename="gear.png"
    )
    product = make_product(own, name="Image gear")

    result = start_understanding(asset=asset, product=product, actor=actor)

    assert result.job.status == Job.Status.SUCCEEDED
    assert result.is_partial is True
    assert result.facts == ()
    assert result.warnings == ("真实 OCR/图片理解尚未配置，未生成候选事实。",)


class DeepSeekFactProvider:
    def __init__(self):
        self.calls = 0

    def generate(self, *, prompt: str, schema: dict) -> dict:
        assert connection.in_atomic_block is False
        self.calls += 1
        assert "UNTRUSTED DOCUMENT EVIDENCE" in prompt
        assert schema["required"] == ["facts"]
        return {
            "facts": [
                {
                    "field_name": "process",
                    "value": "Gear grinding",
                    "confidence": 0.96,
                    "source_page": 1,
                    "source_excerpt": "Process: Gear grinding",
                }
            ]
        }


def _deepseek_runtime(provider) -> ProductAIRuntime:
    return ProductAIRuntime(
        mode="CONFIGURED_AI",
        provider_label="DeepSeek 官方 API",
        provider_code="deepseek",
        model="deepseek-chat",
        configured=True,
        real_requests_enabled=True,
        provider=provider,
    )


@pytest.mark.django_db(transaction=True)
@override_settings(PRODUCT_AI_PROVIDER="deepseek", PRODUCT_AI_MODEL="deepseek-chat")
def test_deepseek_pdf_understanding_persists_real_evidence_without_secret(
    organizations, monkeypatch,
) -> None:
    own, _ = organizations
    actor = get_user_model().objects.create_user(username="understand-real-pdf")
    asset = _upload(
        own, actor, labeled_pdf(), mime="application/pdf", kind="DOCUMENT", filename="real.pdf"
    )
    product = make_product(own, name="Real extraction gear")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-never-persist")
    monkeypatch.setattr(
        "apps.assets.understanding.resolve_product_ai",
        lambda org: _deepseek_runtime(DeepSeekFactProvider()),
    )

    result = start_understanding(
        asset=asset, product=product, actor=actor, external_text_consent=True
    )

    assert result.job.status == Job.Status.SUCCEEDED
    assert result.provider_label == "DeepSeek 官方 API"
    assert result.facts[0].value == "Gear grinding"
    assert result.facts[0].source_excerpt == "Process: Gear grinding"
    assert result.facts[0].is_demo is False
    run = AIRun.objects.get(job=result.job)
    assert run.provider == "deepseek"
    assert run.model == "deepseek-chat"
    assert run.prompt_version.code == "asset-understand-evidence-v1"
    assert run.prompt_version.provider == "system"
    assert run.prompt_version.model == "provider-agnostic"
    persisted = str(result.job.input_snapshot) + str(run.input_snapshot) + str(run.output_json)
    assert "secret-never-persist" not in persisted


@pytest.mark.django_db(transaction=True)
@override_settings(PRODUCT_AI_PROVIDER="deepseek", PRODUCT_AI_MODEL="deepseek-chat")
def test_missing_asset_prompt_fails_before_provider_call(organizations, monkeypatch) -> None:
    own, _ = organizations
    actor = get_user_model().objects.create_user(username="understand-missing-prompt")
    asset = _upload(
        own, actor, labeled_pdf(), mime="application/pdf", kind="DOCUMENT", filename="missing.pdf"
    )
    product = make_product(own, name="Missing prompt gear")
    provider = DeepSeekFactProvider()
    monkeypatch.setattr(
        "apps.assets.understanding.resolve_product_ai",
        lambda org: _deepseek_runtime(provider),
    )
    monkeypatch.setattr(
        "apps.assets.understanding.resolve_published_prompt",
        lambda **kwargs: (_ for _ in ()).throw(
            PromptCatalogEntryMissing(
                purpose="ASSET_UNDERSTAND", prompt_code="asset-understand-evidence-v1"
            )
        ),
    )
    before = PromptVersion.objects.count()

    with pytest.raises(PromptCatalogEntryMissing):
        start_understanding(
            asset=asset,
            product=product,
            actor=actor,
            external_text_consent=True,
        )

    assert provider.calls == 0
    assert PromptVersion.objects.count() == before


@pytest.mark.django_db
@override_settings(PRODUCT_AI_PROVIDER="deepseek", PRODUCT_AI_MODEL="deepseek-chat")
def test_deepseek_mode_without_key_never_falls_back_to_fake(organizations, monkeypatch) -> None:
    own, _ = organizations
    actor = get_user_model().objects.create_user(username="understand-no-key")
    asset = _upload(
        own, actor, labeled_pdf(), mime="application/pdf", kind="DOCUMENT", filename="no-key.pdf"
    )
    product = make_product(own, name="No key gear")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(ValueError, match="DeepSeek API key"):
        start_understanding(asset=asset, product=product, actor=actor)

    assert not Job.objects.filter(type=Job.Type.ASSET_UNDERSTAND).exists()


@pytest.mark.django_db
@override_settings(PRODUCT_AI_PROVIDER="deepseek", PRODUCT_AI_MODEL="deepseek-chat")
def test_deepseek_mode_requires_explicit_text_consent(organizations, monkeypatch) -> None:
    own, _ = organizations
    actor = get_user_model().objects.create_user(username="understand-no-consent")
    asset = _upload(
        own, actor, labeled_pdf(), mime="application/pdf", kind="DOCUMENT", filename="consent.pdf"
    )
    product = make_product(own, name="Consent gear")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-never-persist")

    with pytest.raises(ValueError, match="Confirm that bounded PDF text"):
        start_understanding(asset=asset, product=product, actor=actor)

    assert not Job.objects.filter(type=Job.Type.ASSET_UNDERSTAND).exists()


@pytest.mark.django_db
def test_real_provider_job_does_not_reuse_fake_understanding(organizations, monkeypatch) -> None:
    own, _ = organizations
    actor = get_user_model().objects.create_user(username="understand-provider-split")
    asset = _upload(
        own, actor, labeled_pdf(), mime="application/pdf", kind="DOCUMENT", filename="split.pdf"
    )
    product = make_product(own, name="Split gear")
    fake_result = start_understanding(asset=asset, product=product, actor=actor)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-never-persist")
    monkeypatch.setattr(
        "apps.assets.understanding.resolve_product_ai",
        lambda org: _deepseek_runtime(DeepSeekFactProvider()),
    )

    with override_settings(PRODUCT_AI_PROVIDER="deepseek", PRODUCT_AI_MODEL="deepseek-chat"):
        real_result = start_understanding(
            asset=asset, product=product, actor=actor, external_text_consent=True
        )

    assert real_result.job.id != fake_result.job.id
    assert real_result.provider_label == "DeepSeek 官方 API"


@pytest.mark.django_db(transaction=True)
@override_settings(PRODUCT_AI_PROVIDER="deepseek", PRODUCT_AI_MODEL="deepseek-chat")
def test_repeated_real_understanding_is_idempotent(organizations, monkeypatch) -> None:
    own, _ = organizations
    actor = get_user_model().objects.create_user(username="understand-real-repeat")
    asset = _upload(
        own, actor, labeled_pdf(), mime="application/pdf", kind="DOCUMENT", filename="repeat.pdf"
    )
    product = make_product(own, name="Repeat gear")
    provider = DeepSeekFactProvider()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-never-persist")
    monkeypatch.setattr(
        "apps.assets.understanding.resolve_product_ai",
        lambda org: _deepseek_runtime(provider),
    )

    first = start_understanding(
        asset=asset, product=product, actor=actor, external_text_consent=True
    )
    second = start_understanding(
        asset=asset, product=product, actor=actor, external_text_consent=True
    )

    assert second.job.id == first.job.id
    assert provider.calls == 1
    assert PromptVersion.objects.filter(
        purpose="ASSET_UNDERSTAND",
        code="asset-understand-evidence-v1",
    ).count() == 1


@pytest.mark.django_db
def test_approved_fact_becomes_verified_without_mutating_product(organizations) -> None:
    own, _ = organizations
    actor = get_user_model().objects.create_user(username="review-fact")
    asset = _upload(
        own, actor, labeled_pdf(), mime="application/pdf", kind="DOCUMENT", filename="review.pdf"
    )
    product = make_product(own, name="Review gear")
    original_accuracy = product.accuracy_grade
    result = start_understanding(asset=asset, product=product, actor=actor)

    reviewed = review_fact(
        fact=result.facts[0], decision="APPROVE", actor=actor, note="Compared with source page."
    )

    assert reviewed.review_status == ProductEvidenceFact.ReviewStatus.VERIFIED
    assert reviewed.reviewed_by == actor
    product.refresh_from_db()
    assert product.accuracy_grade == original_accuracy
