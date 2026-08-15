import re
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

from .market_pilots import matched_gear_terms


WEBSITE_TIMEOUT_SECONDS = 15
WEBSITE_MAX_BYTES = 1_000_000
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s()-]{6,}\d")


class WebsiteTransport(Protocol):
    def fetch_html(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> str: ...


class UrllibWebsiteTransport:
    def fetch_html(self, url, *, timeout_seconds, max_bytes) -> str:
        if not _robots_allow(url):
            raise ValueError("robots.txt disallows this page")
        request = Request(
            url,
            headers={"User-Agent": "SinofGearBot/1.0 (+public-discovery)"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(max_bytes + 1)
        except HTTPError as error:
            raise ValueError(f"website returned HTTP {error.code}") from error
        except (TimeoutError, URLError) as error:
            raise ValueError("website is unreachable") from error
        if len(body) > max_bytes:
            raise ValueError("website is too large")
        return body.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class WebsiteFacts:
    title: str
    emails: tuple[str, ...]
    phones: tuple[str, ...]
    contact_links: tuple[str, ...]
    gear_terms: tuple[str, ...]
    text_excerpt: str


def extract_website_facts(html: str, base_url: str) -> WebsiteFacts:
    text = _strip_tags(html)
    title = _extract_title(html)
    emails = tuple(dict.fromkeys(email.lower() for email in EMAIL_RE.findall(text)))
    phones = tuple(dict.fromkeys(phone.strip() for phone in PHONE_RE.findall(text)))[:10]
    contact_links = tuple(dict.fromkeys(
        _absolute_link(base_url, match)
        for match in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
        if _looks_like_contact(match)
    ))[:20]
    gear_terms = tuple(matched_gear_terms(text))
    return WebsiteFacts(
        title=title,
        emails=emails[:20],
        phones=phones,
        contact_links=contact_links,
        gear_terms=gear_terms,
        text_excerpt=_clean_text(text)[:1500],
    )


def build_website_transport():
    factory_path = getattr(settings, "GROWTH_WEBSITE_TRANSPORT_FACTORY", "")
    if factory_path:
        return import_string(factory_path)()
    return UrllibWebsiteTransport()


def prepare_website_enrichment(candidate, *, transport=None):
    from .enrichment import CandidateReviewRequired
    from .models import CandidateEnrichmentSnapshot, DiscoveryCandidate

    if candidate.status != DiscoveryCandidate.Status.ACCEPTED:
        raise CandidateReviewRequired("Candidate must be accepted before website enrichment.")
    if not candidate.website:
        raise ValueError("Candidate has no website to enrich from.")
    fetcher = transport or UrllibWebsiteTransport()
    html = fetcher.fetch_html(
        candidate.website,
        timeout_seconds=WEBSITE_TIMEOUT_SECONDS,
        max_bytes=WEBSITE_MAX_BYTES,
    )
    facts = extract_website_facts(html, candidate.website)
    public_contact_paths = (
        [{"kind": "email", "value": email} for email in facts.emails]
        + [{"kind": "phone", "value": phone} for phone in facts.phones]
        + [{"kind": "link", "value": link} for link in facts.contact_links]
    )
    uncertainties = (
        []
        if public_contact_paths
        else ["官网已读取，但未发现公开邮箱或明显联系方式。"]
    )
    defaults = {
        "mode": "WEBSITE_PUBLIC",
        "facts": [
            {"field": "title", "value": facts.title, "source": "公司官网"},
            {"field": "gear_terms", "value": list(facts.gear_terms), "source": "公司官网"},
            {"field": "text_excerpt", "value": facts.text_excerpt, "source": "公司官网"},
        ],
        "public_contact_paths": public_contact_paths,
        "uncertainties": uncertainties,
        "evidence_envelope": {
            "source_owner": "公司公开官网",
            "source_url": candidate.website,
            "license_contract": "PUBLIC_WEB_FAIR_USE_EXCERPT",
            "access_method": "PUBLIC_WEB_READ",
            "network_access": True,
            "source_cost_micros": 0,
            "review_status": "PENDING_REVIEW",
            "observed_at": timezone.now().isoformat(),
        },
    }
    snapshot, created = CandidateEnrichmentSnapshot.objects.get_or_create(
        organization=candidate.organization,
        candidate=candidate,
        defaults=defaults,
    )
    if not created:
        for field, value in defaults.items():
            setattr(snapshot, field, value)
        snapshot.save(update_fields=[*defaults.keys(), "updated_at"])
    return snapshot, created


def _robots_allow(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception:
        return True
    return parser.can_fetch("SinofGearBot/1.0", url)


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    return _clean_text(_strip_tags(match.group(1))) if match else ""


def _looks_like_contact(href: str) -> bool:
    lowered = href.casefold()
    return any(token in lowered for token in ("contact", "about", "email", "mailto"))


def _absolute_link(base_url: str, href: str) -> str:
    return urljoin(base_url, href)
