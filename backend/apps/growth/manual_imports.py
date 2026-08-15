import hashlib
import ipaddress
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.identity.models import Organization

from .models import IntentSignal, TargetAccount


MANUAL_SCORE_BREAKDOWN = {
    "icp_fit": 15,
    "intent_strength": 15,
    "recency": 12,
    "role_relevance": 3,
    "evidence_coverage": 10,
    "risk_penalty": 5,
}
MANUAL_UNCERTAINTIES = [
    "公司身份仍需人工核实",
    "采购范围与时间仍需人工确认",
]


def validate_manual_source_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "https":
        raise ValidationError("公开来源必须使用 HTTPS。")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("公开来源不能包含用户名或密码。")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValidationError("公开来源必须包含有效主机名。")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ValidationError("来源必须是公开网络地址。")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValidationError("来源必须是公开网络地址。")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValidationError("公开来源端口无效。") from error
    normalized_host = f"[{hostname}]" if address and address.version == 6 else hostname
    netloc = f"{normalized_host}:{port}" if port is not None else normalized_host
    return urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))


def import_manual_opportunity(
    *, organization: Organization, data: Mapping[str, str],
) -> tuple[TargetAccount, IntentSignal, bool]:
    company_name = data["company_name"].strip()
    country = data["country"].strip()
    industry = data.get("industry", "").strip()
    source_label = data["source_label"].strip()
    source_url = validate_manual_source_url(data["source_url"])
    evidence_text = data["evidence_text"].strip()
    fingerprint = hashlib.sha256(
        f"{source_url}\n{evidence_text}".encode("utf-8"),
    ).hexdigest()

    with transaction.atomic():
        locked_organization = Organization.objects.select_for_update().get(pk=organization.pk)
        existing = IntentSignal.objects.select_related("account").filter(
            organization=locked_organization,
            content_hash=fingerprint,
        ).first()
        if existing is not None:
            return existing.account, existing, False

        account = TargetAccount.objects.filter(
            organization=locked_organization,
            name__iexact=company_name,
        ).first()
        if account is None:
            account = TargetAccount.objects.create(
                organization=locked_organization,
                name=company_name,
                country=country,
                industry=industry,
                is_demo=False,
            )
        elif account.is_demo:
            account.is_demo = False
            account.save(update_fields=["is_demo", "updated_at"])

        signal = IntentSignal(
            organization=locked_organization,
            account=account,
            signal_type="MANUAL_EVIDENCE",
            source_label=source_label,
            source_url=source_url,
            evidence_text=evidence_text,
            confidence=50,
            is_demo=False,
            collection_method="MANUAL_URL",
            content_hash=fingerprint,
            score_breakdown=MANUAL_SCORE_BREAKDOWN,
            scoring_rule_version="manual-opportunity-v1",
            uncertainty_notes=MANUAL_UNCERTAINTIES,
            evidence_envelope={
                "field_value": evidence_text,
                "source_url": source_url,
                "source_excerpt": evidence_text,
                "confidence": 50,
                "observed_at": timezone.now().isoformat(),
                "source_cost_micros": 0,
                "license_contract": "USER_ASSERTED_PERMISSION",
                "usage_rights": "INTERNAL_DISCOVERY_WITH_SOURCE_LINK",
                "review_status": "PENDING_REVIEW",
                "queue": "MONITORING",
            },
        )
        signal.full_clean()
        signal.save()
        return account, signal, True
