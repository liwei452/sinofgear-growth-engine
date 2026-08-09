from uuid import UUID

from django.conf import settings
from django.utils import timezone

from .codes import AccountCapability
from .models import SocialAccount

CONNECTOR_CAPABILITIES: dict[str, frozenset[AccountCapability]] = {
    code: frozenset(AccountCapability(value) for value in values)
    for code, values in settings.PLATFORM_CONNECTOR_CAPABILITIES.items()
}


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
    credential = account.credential
    if (
        account.status != SocialAccount.Status.ACTIVE
        or credential is None
        or credential.organization_id != account.organization_id
        or credential.platform_id != account.platform_id
        or not credential.secret_reference
        or (credential.expires_at is not None and credential.expires_at <= timezone.now())
    ):
        return set()
    platform_capabilities = set(
        account.platform.capability_definitions.values_list("code", flat=True)
    )
    connector_capabilities = CONNECTOR_CAPABILITIES.get(account.platform.code, frozenset())
    effective_codes = (
        platform_capabilities
        & {capability.value for capability in connector_capabilities if isinstance(capability, AccountCapability)}
        & _valid_granted_scopes(credential.granted_scopes)
    )
    if account.publish_mode != SocialAccount.PublishMode.API_AUTO:
        effective_codes.discard(AccountCapability.PUBLISH.value)
    return {AccountCapability(code) for code in effective_codes if code in AccountCapability._value2member_map_}
