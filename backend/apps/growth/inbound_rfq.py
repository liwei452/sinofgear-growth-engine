import hashlib

from django.conf import settings
from django.db import transaction

from apps.identity.models import Organization

from .models import (
    Contact,
    DiscoveryCandidate,
    FollowUp,
    InboundLead,
    IntentSignal,
    TargetAccount,
)
from .taxonomy import classify_need


@transaction.atomic
def record_inbound_rfq(*, organization, **payload) -> dict:
    company_name = str(payload.get("company_name", "")).strip() or "Unknown company"
    email = str(payload.get("email", "")).strip()
    contact_name = str(payload.get("contact_name", "")).strip() or "Website inquiry"
    country = str(payload.get("country", "")).strip() or "Unknown"
    industry = str(payload.get("industry", "")).strip()
    product_interest = str(payload.get("product_interest", "")).strip()
    message = str(payload.get("message", "")).strip()
    landing_page = str(payload.get("landing_page", "")).strip()
    file_names = list(payload.get("file_names") or [])
    need = classify_need(f"{message} {product_interest}")

    source_identity = f"website-rfq:{email or company_name.casefold()}"
    account, account_created = TargetAccount.objects.get_or_create(
        organization=organization,
        source_identity=source_identity,
        defaults={
            "name": company_name,
            "country": country,
            "industry": industry,
        },
    )
    Contact.objects.get_or_create(
        organization=organization,
        account=account,
        full_name=contact_name,
        defaults={"verification_status": "UNVERIFIED"},
    )
    source_url = (
        landing_page
        if landing_page.startswith(("http://", "https://"))
        else "https://sinfogear.com/contact"
    )
    content_hash = hashlib.sha256(
        f"website-rfq:{email or company_name.casefold()}:{message}".encode("utf-8")
    ).hexdigest()
    IntentSignal.objects.get_or_create(
        organization=organization,
        content_hash=content_hash,
        defaults={
            "account": account,
            "signal_type": "INBOUND_RFQ",
            "source_label": "网站询盘",
            "source_url": source_url,
            "evidence_text": message or product_interest or "网站询盘",
            "confidence": 70,
            "collection_method": "WEBSITE_RFQ",
            "evidence_envelope": {
                "need_slug": need,
                "product_interest": product_interest,
                "contact_name": contact_name,
                "email": email,
                "landing_page": landing_page,
                "file_names": file_names,
            },
        },
    )
    FollowUp.objects.get_or_create(
        organization=organization,
        account=account,
        defaults={"stage": FollowUp.Stage.RFQ},
    )
    InboundLead.objects.get_or_create(
        organization=organization,
        account=account,
        defaults={"source_label": "网站 RFQ"},
    )
    return {
        "account_id": str(account.id),
        "need_slug": need,
        "created_account": account_created,
    }


def resolve_website_organization(lead_id: str = ""):
    if lead_id:
        candidate = DiscoveryCandidate.objects.filter(id=lead_id).first()
        if candidate:
            return candidate.organization
    slug = getattr(settings, "LEAD_WEBSITE_ORGANIZATION_SLUG", "")
    if slug:
        return Organization.objects.filter(slug=slug).first()
    return None
