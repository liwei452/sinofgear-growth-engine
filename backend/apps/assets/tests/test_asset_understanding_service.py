from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject

from apps.assets.models import ProductEvidenceFact
from apps.assets.services import upload_asset
from apps.assets.understanding import review_fact, start_understanding
from apps.jobs.models import Job

from .conftest import make_product, png_bytes
from .test_asset_upload import ChunkOnlyUpload


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
