import hashlib
import hmac
import ipaddress
import re
from datetime import date
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class PrivacyError(ValueError):
    pass


INSECURE_SECRETS = {
    "development-only-tracking-secret",
    "change-me",
    "tracking-secret",
}


def validate_tracking_configuration() -> None:
    secret = getattr(settings, "TRACKING_HASH_SECRET", "")
    version = getattr(settings, "TRACKING_HASH_VERSION", "")
    if not isinstance(secret, str) or len(secret.encode()) < 32 or secret.lower() in INSECURE_SECRETS:
        raise ImproperlyConfigured(
            "TRACKING_HASH_SECRET must be a dedicated unpredictable secret of at least 32 bytes."
        )
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", version):
        raise ImproperlyConfigured("TRACKING_HASH_VERSION must be a bounded stable identifier.")
    _trusted_networks()


def _trusted_networks():
    networks = []
    for raw in getattr(settings, "TRACKING_TRUSTED_PROXY_CIDRS", []):
        try:
            networks.append(ipaddress.ip_network(raw, strict=True))
        except (TypeError, ValueError) as exc:
            raise ImproperlyConfigured("TRACKING_TRUSTED_PROXY_CIDRS contains an invalid CIDR.") from exc
    return networks


def _single_ip(value: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if not isinstance(value, str) or not value.strip() or "," in value:
        raise PrivacyError("Client network metadata is invalid.")
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise PrivacyError("Client network metadata is invalid.") from exc


def extract_network_context(meta: dict[str, object]) -> tuple[str, str]:
    peer = _single_ip(meta.get("REMOTE_ADDR"))
    trusted = any(peer.version == network.version and peer in network for network in _trusted_networks())
    if not trusted:
        return peer.compressed, ""
    client = _single_ip(meta.get("HTTP_X_FORWARDED_FOR"))
    country = meta.get("HTTP_X_COUNTRY_CODE", "")
    if country in {None, ""}:
        normalized_country = ""
    elif isinstance(country, str) and re.fullmatch(r"[A-Za-z]{2}", country.strip()):
        normalized_country = country.strip().upper()
    else:
        raise PrivacyError("Country metadata is invalid.")
    return client.compressed, normalized_country


def _coarse_prefix(address: str) -> str:
    parsed = _single_ip(address)
    prefix = 24 if parsed.version == 4 else 56
    return ipaddress.ip_network(f"{parsed.compressed}/{prefix}", strict=False).with_prefixlen


def daily_network_hash(address: str, occurred_date: date) -> str:
    validate_tracking_configuration()
    secret = settings.TRACKING_HASH_SECRET.encode()
    version = settings.TRACKING_HASH_VERSION
    message = f"{version}|{occurred_date.isoformat()}|{_coarse_prefix(address)}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def classify_device(user_agent: object) -> str:
    if not isinstance(user_agent, str) or not user_agent:
        return "other"
    lowered = user_agent[:1024].lower()
    if any(token in lowered for token in ("bot", "crawler", "spider", "slurp")):
        return "bot"
    if any(token in lowered for token in ("ipad", "tablet", "kindle")):
        return "tablet"
    if any(token in lowered for token in ("mobile", "iphone", "android")):
        return "mobile"
    if any(token in lowered for token in ("windows", "macintosh", "x11", "linux")):
        return "desktop"
    return "other"


def normalize_referrer_host(referrer: object) -> str:
    if not isinstance(referrer, str) or not referrer or len(referrer) > 2048:
        return ""
    try:
        parsed = urlsplit(referrer)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return ""
        host = parsed.hostname.rstrip(".").lower().encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return ""
    return host if len(host) <= 253 else ""
