"""Pre-publish tracking-link helpers."""

from __future__ import annotations

from apps.tracking.services import create_short_link, create_tracking_link


class PrePublishTrackingUnavailable(RuntimeError):
    pass


SHORT_LINK_BASE_URL = "https://sinfogear.com/s"


def build_short_link_url(short_link) -> str:
    return f"{SHORT_LINK_BASE_URL}/{short_link.code}"


def prepare_pre_publish_short_link(*, platform_content, actor):
    master = platform_content.master_content
    brief = master.brief
    product_link = brief.product_links.first()
    if product_link is None:
        raise PrePublishTrackingUnavailable("brief has no linked product.")
    destination = (
        (platform_content.payload or {}).get("landing_page_url")
        or brief.landing_page_url
        or "https://sinfogear.com"
    )
    tracking_link = create_tracking_link(
        organization=platform_content.organization,
        destination=destination,
        utm_source="organic",
        utm_medium=platform_content.platform.code.lower(),
        utm_campaign=f"content-{master.id}",
        campaign=brief.campaign,
        platform=platform_content.platform,
        product=product_link.product,
        published_post=None,
        idempotency_key=f"pre-publish:{platform_content.id}",
        actor=actor,
    )
    return create_short_link(
        organization=platform_content.organization,
        tracking_link=tracking_link,
        idempotency_key=f"pre-publish-short:{platform_content.id}",
        actor=actor,
    )
