import hashlib
import ipaddress
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.assets.models import MaterialAsset

from .models import SourceEvidence, SourceSignal, evidence_service_writes


def normalize_source_url(url: str) -> str:
    if not isinstance(url, str) or not url:
        raise ValidationError("Source URL must be a non-empty HTTP(S) URL.")
    if any(ord(character) <= 32 for character in url):
        raise ValidationError("Source URL must not contain whitespace or control characters.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ValidationError("Source URL is invalid.") from error
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValidationError("Source URL must use HTTP or HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("Source URL must not contain credentials.")
    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("Source URL must include a host.")
    try:
        try:
            normalized_host = f"[{ipaddress.IPv6Address(hostname).compressed.lower()}]"
        except ipaddress.AddressValueError:
            normalized_host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValidationError("Source URL host is invalid.") from error
    if not normalized_host:
        raise ValidationError("Source URL host is invalid.")
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = normalized_host if port is None or default_port else f"{normalized_host}:{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


def evidence_fingerprint(*, original_text: str, source_url: str, platform: str) -> str:
    canonical = "\n".join(
        (
            platform.strip().upper(),
            normalize_source_url(source_url),
            " ".join(original_text.split()),
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EvidenceService:
    _EVIDENCE_TYPES = {
        SourceEvidence.CollectionMethod.API: SourceEvidence.EvidenceType.PUBLIC_METADATA,
        SourceEvidence.CollectionMethod.URL: SourceEvidence.EvidenceType.PUBLIC_TEXT,
        SourceEvidence.CollectionMethod.PASTE: SourceEvidence.EvidenceType.PUBLIC_TEXT,
        SourceEvidence.CollectionMethod.SCREENSHOT: SourceEvidence.EvidenceType.SCREENSHOT,
        SourceEvidence.CollectionMethod.CSV: SourceEvidence.EvidenceType.IMPORT_ROW,
        SourceEvidence.CollectionMethod.JSON: SourceEvidence.EvidenceType.IMPORT_ROW,
    }

    @staticmethod
    @transaction.atomic
    def create(
        *,
        organization,
        signal,
        original_text,
        source_url,
        platform,
        collection_method,
        public_published_at,
        created_by,
        screenshot_asset=None,
        import_asset=None,
        evidence_type=None,
        language="",
    ):
        signal_id = getattr(signal, "pk", None)
        try:
            signal = SourceSignal.objects.select_for_update().filter(
                pk=signal_id, organization=organization
            ).first()
        except (TypeError, ValueError) as error:
            raise ValidationError(
                {"signal": "Source signal is unavailable for this organization."}
            ) from error
        if signal is None:
            raise ValidationError(
                {"signal": "Source signal is unavailable for this organization."}
            )
        screenshot_asset = EvidenceService._locked_asset(
            screenshot_asset, "screenshot_asset", organization
        )
        import_asset = EvidenceService._locked_asset(
            import_asset, "import_asset", organization
        )
        normalized_url = normalize_source_url(source_url)
        fingerprint = evidence_fingerprint(
            original_text=original_text,
            source_url=normalized_url,
            platform=platform,
        )
        method = str(collection_method).strip().upper()
        if method not in SourceEvidence.CollectionMethod.values:
            raise ValidationError({"collection_method": "Unsupported evidence collection method."})
        if evidence_type is not None and evidence_type not in SourceEvidence.EvidenceType.values:
            raise ValidationError({"evidence_type": "Unsupported evidence type."})
        resolved_evidence_type = evidence_type or EvidenceService._EVIDENCE_TYPES.get(method)
        if resolved_evidence_type is None:
            raise ValidationError({"collection_method": "Unsupported evidence collection method."})
        with evidence_service_writes():
            evidence, _ = SourceEvidence.objects.get_or_create(
                organization=organization,
                content_hash=fingerprint,
                defaults={
                    "source_signal": signal,
                    "evidence_type": resolved_evidence_type,
                    "original_text": original_text,
                    "source_url": normalized_url,
                    "platform": platform,
                    "collection_method": method,
                    "public_published_at": public_published_at,
                    "created_by": created_by,
                    "screenshot_asset": screenshot_asset,
                    "import_asset": import_asset,
                    "language": language,
                    "retention_class": SourceEvidence.RetentionClass.TRANSIENT_30D,
                },
            )
        return evidence

    @staticmethod
    def _locked_asset(asset, field_name, organization):
        if asset is None:
            return None
        try:
            locked = MaterialAsset.objects.select_for_update().filter(
                pk=getattr(asset, "pk", None), organization=organization
            ).first()
        except (TypeError, ValueError) as error:
            raise ValidationError(
                {field_name: "Evidence asset is unavailable for this organization."}
            ) from error
        if locked is None:
            raise ValidationError(
                {field_name: "Evidence asset is unavailable for this organization."}
            )
        return locked


create = EvidenceService.create
