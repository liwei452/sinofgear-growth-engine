from enum import StrEnum
from uuid import UUID

from .models import SocialAccount


class AccountCapability(StrEnum):
    PUBLISH = "PUBLISH"
    METRICS_READ = "METRICS_READ"
    COMMENT_READ = "COMMENT_READ"
    PUBLIC_SEARCH = "PUBLIC_SEARCH"
    MEDIA_UPLOAD = "MEDIA_UPLOAD"
    WEBHOOK = "WEBHOOK"


def resolve_account_capabilities(account_id: UUID) -> set[AccountCapability]:
    """Return capabilities available through every layer of an account connection."""
    account = SocialAccount.objects.select_related("credential").get(id=account_id)
    if account.credential is None:
        return set()
    platform_capabilities = set(
        account.platform.capability_definitions.values_list("code", flat=True)
    )
    effective_codes = (
        platform_capabilities
        & set(account.credential.implementation_capabilities)
        & set(account.credential.granted_scopes)
    )
    return {AccountCapability(code) for code in effective_codes if code in AccountCapability._value2member_map_}

