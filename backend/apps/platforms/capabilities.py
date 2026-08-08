from uuid import UUID

from .codes import AccountCapability
from .models import SocialAccount

CONNECTOR_CAPABILITIES: dict[str, frozenset[AccountCapability]] = {}


def resolve_account_capabilities(account_id: UUID) -> set[AccountCapability]:
    """Return capabilities available through every layer of an account connection."""
    account = SocialAccount.objects.select_related("credential").get(id=account_id)
    if account.credential is None:
        return set()
    platform_capabilities = set(
        account.platform.capability_definitions.values_list("code", flat=True)
    )
    connector_capabilities = CONNECTOR_CAPABILITIES.get(account.platform.code, frozenset())
    effective_codes = platform_capabilities & set(connector_capabilities) & set(account.credential.granted_scopes)
    return {AccountCapability(code) for code in effective_codes if code in AccountCapability._value2member_map_}
