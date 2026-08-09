import ipaddress
import hashlib
import json
import re
import secrets
from datetime import datetime
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.campaigns.models import ContentBriefProduct
from apps.catalog.models import Product
from apps.content.models import PlatformContent
from apps.publishing.models import PublishAttempt, PublishTask

from .models import ClickEvent, ShortLink, TrackingLink, click_purges, click_writes, tracking_writes
from .privacy import (
    classify_device, daily_network_hash, extract_network_context, normalize_referrer_host,
)


MAX_SLUG_LENGTH = 128
MAX_DESTINATION_LENGTH = 2048
UTM_NAMES = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


class TrackingConflict(ValueError):
    pass


def normalize_slug(value: str) -> str:
    if not isinstance(value, str) or any(character in value for character in "/\\"):
        raise ValidationError("Slug must be text without path separators.")
    value = unicodedata.normalize("NFKC", value).strip().lower()
    pieces: list[str] = []
    pending_separator = False
    for character in value:
        if character.isalnum():
            if pending_separator and pieces:
                pieces.append("-")
            pieces.append(character)
            pending_separator = False
        elif character.isspace() or character in "-_.":
            pending_separator = True
        else:
            pending_separator = True
    slug = "".join(pieces).strip("-")
    if not slug or len(slug) > MAX_SLUG_LENGTH:
        raise ValidationError(f"Slug must contain 1-{MAX_SLUG_LENGTH} normalized characters.")
    return slug


def _canonical_host(hostname: str | None) -> str:
    if not hostname:
        raise ValidationError("Destination must include a host.")
    hostname = hostname.rstrip(".").lower()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            raise ValidationError("Destination host is not public.")
        try:
            ascii_host = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValidationError("Destination host is invalid.") from exc
        labels = ascii_host.split(".")
        if len(labels) < 2 or len(ascii_host) > 253 or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or re.fullmatch(r"[a-z0-9-]+", label) is None
            for label in labels
        ):
            raise ValidationError("Destination host is invalid.")
        return ascii_host
    if not address.is_global:
        raise ValidationError("Destination host is not public.")
    return f"[{address.compressed}]" if address.version == 6 else address.compressed


def _utm_value(name: str, value: str | None, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not (value := unicodedata.normalize("NFKC", value).strip()):
        raise ValidationError({name: "UTM value must not be blank."})
    try:
        return normalize_slug(value)
    except ValidationError as exc:
        raise ValidationError({name: exc.messages}) from exc


def build_canonical_url(
    destination: str,
    *,
    source: str,
    medium: str,
    campaign: str,
    content: str | None = None,
    term: str | None = None,
) -> str:
    if (
        not isinstance(destination, str)
        or not destination
        or len(destination) > MAX_DESTINATION_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in destination)
    ):
        raise ValidationError("Destination is invalid or too long.")
    try:
        parsed = urlsplit(destination)
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("Destination URL is invalid.") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValidationError("Destination must use HTTP or HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("Destination credentials are not allowed.")
    host = _canonical_host(parsed.hostname)
    if port is not None and not 1 <= port <= 65535:
        raise ValidationError("Destination port is invalid.")
    netloc = host if port is None else f"{host}:{port}"
    try:
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=False, max_num_fields=100)
    except ValueError as exc:
        raise ValidationError("Destination query is too large.") from exc
    if any(name.lower() in UTM_NAMES for name, _value in query):
        raise ValidationError("Destination must not already contain UTM parameters.")
    query = sorted(query, key=lambda item: (item[0], item[1]))
    utm = [
        ("utm_source", _utm_value("source", source, required=True)),
        ("utm_medium", _utm_value("medium", medium, required=True)),
        ("utm_campaign", _utm_value("campaign", campaign, required=True)),
    ]
    optional = (
        ("utm_content", _utm_value("content", content, required=False)),
        ("utm_term", _utm_value("term", term, required=False)),
    )
    query.extend((name, value) for name, value in (*utm, *optional) if value is not None)
    result = urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path or "/", urlencode(query, doseq=True), parsed.fragment)
    )
    if len(result) > MAX_DESTINATION_LENGTH:
        raise ValidationError("Canonical URL is too long.")
    return result


def validate_idempotency_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or not (value := value.strip())
        or len(value) > 128
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise TrackingConflict("Idempotency-Key must be 1-128 visible ASCII characters.")
    return value


def _tracking_fingerprint(values: dict[str, object]) -> str:
    raw = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _tracking_consistent(link: TrackingLink) -> bool:
    try:
        post = link.published_post
        content = post.platform_content
        brief = content.master_content.brief
        canonical = build_canonical_url(
            link.destination,
            source=link.utm_source,
            medium=link.utm_medium,
            campaign=link.utm_campaign,
            content=link.utm_content or None,
            term=link.utm_term or None,
        )
        return (
            link.organization_id == post.organization_id == content.organization_id
            and link.organization_id == link.campaign.organization_id == link.product.organization_id
            and link.platform_id == content.platform_id == post.task.platform_id
            and link.campaign_id == brief.campaign_id
            and link.product.status == Product.Status.ACTIVE
            and post.task_id == post.attempt.task_id
            and post.task.platform_content_id == post.platform_content_id
            and post.task.social_account_id == post.social_account_id
            and post.task.status == PublishTask.Status.SUCCEEDED
            and post.attempt.status == PublishAttempt.Status.SUCCEEDED
            and not PlatformContent.objects.filter(previous_version_id=content.id).exists()
            and ContentBriefProduct.objects.filter(
                organization_id=link.organization_id,
                brief_id=brief.id,
                product_id=link.product_id,
            ).exists()
            and link.full_url == canonical
        )
    except (AttributeError, ObjectDoesNotExist, ValidationError):
        return False


@transaction.atomic
def create_tracking_link(
    *, organization, destination, utm_source, utm_medium, utm_campaign,
    campaign, platform, product, published_post, idempotency_key,
    utm_content=None, utm_term=None, actor=None,
):
    key = validate_idempotency_key(idempotency_key)
    source = _utm_value("utm_source", utm_source, required=True)
    medium = _utm_value("utm_medium", utm_medium, required=True)
    campaign_value = _utm_value("utm_campaign", utm_campaign, required=True)
    content_value = _utm_value("utm_content", utm_content, required=False) or ""
    term_value = _utm_value("utm_term", utm_term, required=False) or ""
    full_url = build_canonical_url(
        destination, source=source, medium=medium, campaign=campaign_value,
        content=content_value or None, term=term_value or None,
    )
    payload = {
        "destination": destination,
        "full_url": full_url,
        "utm_source": source,
        "utm_medium": medium,
        "utm_campaign": campaign_value,
        "utm_content": content_value,
        "utm_term": term_value,
        "campaign_id": str(campaign.id),
        "platform_id": str(platform.id),
        "product_id": str(product.id),
        "published_post_id": str(published_post.id),
    }
    fingerprint = _tracking_fingerprint(payload)
    existing = TrackingLink.objects.filter(organization=organization, idempotency_key=key).first()
    if existing:
        if existing.request_fingerprint != fingerprint or not _tracking_consistent(existing):
            raise TrackingConflict("Idempotency-Key already has a different or inconsistent request.")
        return existing
    try:
        locked_post = type(published_post).objects.select_for_update().select_related(
            "platform_content__master_content__brief__campaign", "task", "attempt",
            "social_account",
        ).get(pk=published_post.pk)
        locked_campaign = type(campaign).objects.select_for_update().get(pk=campaign.pk)
        locked_product = type(product).objects.select_for_update().get(pk=product.pk)
        locked_platform = type(platform).objects.get(pk=platform.pk)
    except (ObjectDoesNotExist, ValueError) as exc:
        raise TrackingConflict("Tracking references are invalid.") from exc
    candidate = TrackingLink(
        organization=organization, campaign=locked_campaign, platform=locked_platform,
        product=locked_product,
        published_post=locked_post, idempotency_key=key, request_fingerprint=fingerprint,
        created_by=actor, destination=destination, full_url=full_url, utm_source=source,
        utm_medium=medium, utm_campaign=campaign_value, utm_content=content_value,
        utm_term=term_value,
    )
    if not _tracking_consistent(candidate):
        raise TrackingConflict("Tracking references do not describe one current organization fact.")
    try:
        with transaction.atomic(), tracking_writes():
            candidate.save(force_insert=True)
    except IntegrityError:
        existing = TrackingLink.objects.filter(organization=organization, idempotency_key=key).first()
        if existing is None or existing.request_fingerprint != fingerprint or not _tracking_consistent(existing):
            raise TrackingConflict("Idempotency-Key collision has a different request.") from None
        return existing
    return candidate


def generate_short_code() -> str:
    return f"s_{secrets.token_urlsafe(9).rstrip('=')}"


def _short_consistent(short_link: ShortLink) -> bool:
    try:
        return (
            short_link.organization_id == short_link.tracking_link.organization_id
            and _tracking_consistent(short_link.tracking_link)
            and re.fullmatch(r"[A-Za-z0-9_-]{10,32}", short_link.code) is not None
        )
    except ObjectDoesNotExist:
        return False


@transaction.atomic
def create_short_link(*, organization, tracking_link, idempotency_key, actor=None):
    key = validate_idempotency_key(idempotency_key)
    fingerprint = _tracking_fingerprint({"tracking_link_id": str(tracking_link.id)})
    existing = ShortLink.objects.filter(organization=organization, idempotency_key=key).select_related(
        "tracking_link__published_post__platform_content__master_content__brief",
        "tracking_link__campaign", "tracking_link__product",
    ).first()
    if existing:
        if existing.request_fingerprint != fingerprint or not _short_consistent(existing):
            raise TrackingConflict("Idempotency-Key already has a different or inconsistent request.")
        return existing
    try:
        locked = TrackingLink.objects.select_for_update().select_related(
            "published_post__platform_content__master_content__brief", "published_post__task",
            "campaign", "product",
        ).get(pk=tracking_link.pk, organization=organization)
    except TrackingLink.DoesNotExist as exc:
        raise TrackingConflict("Tracking link is not visible to this organization.") from exc
    if not _tracking_consistent(locked):
        raise TrackingConflict("Tracking link is inconsistent.")
    for _attempt in range(8):
        candidate = ShortLink(
            organization=organization,
            tracking_link=locked,
            code=generate_short_code(),
            status=ShortLink.Status.ACTIVE,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            created_by=actor,
        )
        try:
            with transaction.atomic(), tracking_writes():
                candidate.save(force_insert=True)
            return candidate
        except IntegrityError:
            existing = ShortLink.objects.filter(organization=organization, idempotency_key=key).select_related(
                "tracking_link__published_post__platform_content__master_content__brief",
                "tracking_link__campaign", "tracking_link__product",
            ).first()
            if existing:
                if existing.request_fingerprint == fingerprint and _short_consistent(existing):
                    return existing
                raise TrackingConflict("Idempotency-Key collision has a different request.") from None
    raise TrackingConflict("Unable to allocate a short-link code; retry with the same key.")


@transaction.atomic
def set_short_link_status(short_link: ShortLink, *, status: str) -> ShortLink:
    if status not in ShortLink.Status.values:
        raise TrackingConflict("Short-link status is invalid.")
    try:
        locked = ShortLink.objects.select_for_update().get(pk=short_link.pk)
    except ShortLink.DoesNotExist as exc:
        raise TrackingConflict("Short link does not exist.") from exc
    with tracking_writes():
        locked.status = status
        locked.save(update_fields=["status", "updated_at"])
    return locked


def resolve_active_short_link(code: str) -> ShortLink | None:
    if not isinstance(code, str) or re.fullmatch(r"[A-Za-z0-9_-]{10,32}", code) is None:
        return None
    short_link = ShortLink.objects.filter(code=code, status=ShortLink.Status.ACTIVE).select_related(
        "tracking_link__published_post__platform_content__master_content__brief",
        "tracking_link__published_post__task", "tracking_link__campaign",
        "tracking_link__platform", "tracking_link__product",
    ).first()
    return short_link if short_link is not None and _short_consistent(short_link) else None


@transaction.atomic
def record_click_event(*, short_link: ShortLink, meta: dict[str, object], occurred_at=None) -> ClickEvent:
    occurred_at = occurred_at or timezone.now()
    if timezone.is_naive(occurred_at):
        raise TrackingConflict("Click timestamp must include a timezone.")
    locked = ShortLink.objects.select_for_update().select_related(
        "tracking_link__published_post__platform_content__master_content__brief",
        "tracking_link__published_post__task", "tracking_link__campaign",
        "tracking_link__platform", "tracking_link__product",
    ).filter(pk=short_link.pk, status=ShortLink.Status.ACTIVE).first()
    if locked is None or not _short_consistent(locked):
        raise TrackingConflict("Short link is not active and consistent.")
    address, country = extract_network_context(meta)
    occurred_date = timezone.localdate(occurred_at)
    with click_writes():
        return ClickEvent.objects.create(
            organization_id=locked.organization_id,
            tracking_link=locked.tracking_link,
            short_link=locked,
            campaign_id=locked.tracking_link.campaign_id,
            platform_id=locked.tracking_link.platform_id,
            product_id=locked.tracking_link.product_id,
            occurred_at=occurred_at,
            occurred_date=occurred_date,
            country=country,
            device=classify_device(meta.get("HTTP_USER_AGENT")),
            referrer_host=normalize_referrer_host(meta.get("HTTP_REFERER")),
            network_hash=daily_network_hash(address, occurred_date),
            hash_version=settings.TRACKING_HASH_VERSION,
        )


@transaction.atomic
def purge_click_events(*, membership, before: datetime) -> int:
    from apps.identity.permissions import PermissionCode
    from apps.identity.services import require_permission

    require_permission(membership=membership, permission=PermissionCode.TRACKING_MANAGE)
    if timezone.is_naive(before):
        raise TrackingConflict("Retention cutoff must include a timezone.")
    with click_purges():
        deleted, _detail = ClickEvent.objects.filter(
            organization=membership.organization, occurred_at__lt=before
        ).delete()
    return deleted
