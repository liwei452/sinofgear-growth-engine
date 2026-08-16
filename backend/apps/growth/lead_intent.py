from django.db import transaction

from .models import DiscoveryCandidate, LeadWebsiteVisit


VISIT_SIGNALS = (
    ("/reverse-engineering-gears", "reverse_engineering", 10),
    ("/replacement-gears", "replacement_page", 8),
    ("/quality", "quality_page", 5),
    ("/industries/", "industry_landing", 5),
    ("/products/", "product_page", 5),
)
EMAIL_CLICK_POINTS = 5
RETURN_VISIT_POINTS = 8
MULTI_PRODUCT_POINTS = 5


def intent_score_from_visits(paths, *, email_clicked=False, sessions=1) -> tuple[int, dict]:
    breakdown = {
        "email_click": 0,
        "page_signals": 0,
        "return_visit": 0,
        "multi_product": 0,
    }
    if email_clicked:
        breakdown["email_click"] = EMAIL_CLICK_POINTS
    for path in paths:
        for prefix, _signal, points in VISIT_SIGNALS:
            if path.startswith(prefix):
                breakdown["page_signals"] += points
                break
    if sessions >= 2:
        breakdown["return_visit"] = RETURN_VISIT_POINTS
    product_paths = {path for path in paths if path.startswith("/products/")}
    if len(product_paths) >= 2:
        breakdown["multi_product"] = MULTI_PRODUCT_POINTS
    return sum(breakdown.values()), breakdown


@transaction.atomic
def record_lead_visit(
    *,
    lead_id,
    path,
    utm_source="",
    utm_campaign="",
    session_id="",
):
    candidate = DiscoveryCandidate.objects.filter(id=lead_id).first()
    if candidate is None:
        return None
    organization = candidate.organization
    LeadWebsiteVisit.objects.create(
        organization=organization,
        candidate=candidate,
        path=path,
        utm_source=utm_source,
        utm_campaign=utm_campaign,
        session_id=session_id,
    )
    visits = list(
        LeadWebsiteVisit.objects.filter(candidate=candidate).values_list("path", flat=True)
    )
    sessions = (
        LeadWebsiteVisit.objects.filter(candidate=candidate)
        .exclude(session_id="")
        .values("session_id")
        .distinct()
        .count()
    ) or 1
    score, breakdown = intent_score_from_visits(visits, sessions=sessions)
    candidate.intent_score = score
    candidate.intent_breakdown = breakdown
    candidate.save(update_fields=["intent_score", "intent_breakdown", "updated_at"])
    return candidate
