from django.conf import settings
from django.db import transaction

from apps.identity.models import Organization

from .models import DiscoveryCandidate, InboundRfq
from .taxonomy import classify_need


@transaction.atomic
def record_inbound_rfq(*, organization, **payload) -> InboundRfq:
    need = classify_need(f"{payload.get('message', '')} {payload.get('product_interest', '')}")
    rfq = InboundRfq.objects.create(
        organization=organization,
        company_name=payload.get("company_name", ""),
        country=payload.get("country", ""),
        contact_name=payload.get("contact_name", ""),
        email=payload.get("email", ""),
        industry=payload.get("industry", ""),
        product_interest=payload.get("product_interest", ""),
        message=payload.get("message", ""),
        file_names=payload.get("file_names") or [],
        need_slug=need,
        landing_page=payload.get("landing_page", ""),
        lead_id=payload.get("lead_id", ""),
    )
    return rfq


def resolve_website_organization(lead_id: str = ""):
    if lead_id:
        candidate = DiscoveryCandidate.objects.filter(id=lead_id).first()
        if candidate:
            return candidate.organization
    slug = getattr(settings, "LEAD_WEBSITE_ORGANIZATION_SLUG", "")
    if slug:
        return Organization.objects.filter(slug=slug).first()
    return None
