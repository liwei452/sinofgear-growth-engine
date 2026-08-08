from uuid import UUID

from .codes import AccountCapability
from .models import SocialAccount

CONNECTOR_CAPABILITIES: dict[str, frozenset[AccountCapability]] = {}


def _valid_granted_scopes(value: object) -> set[str]:
    """Return no scopes when legacy persisted data is malformed or unrecognized."""
    if not isinstance(value, list) or any(not isinstance(scope, str) for scope in value):
        return set()
    if any(scope not in AccountCapability._value2member_map_ for scope in value):
        return set()
    return set(value)


def resolve_account_capabilities(account_id: UUID) -> set[AccountCapability]:
    """Return capabilities available through every layer of an account connection."""
    account = SocialAccount.objects.select_related("credential").get(id=account_id)
    if account.credential is None:
        return set()
    platform_capabilities = set(
        account.platform.capability_definitions.values_list("code", flat=True)
    )
    connector_capabilities = CONNECTOR_CAPABILITIES.get(account.platform.code, frozenset())
    effective_codes = platform_capabilities & set(connector_capabilities) & _valid_granted_scopes(account.credential.granted_scopes)
    return {AccountCapability(code) for code in effective_codes if code in AccountCapability._value2member_map_}
