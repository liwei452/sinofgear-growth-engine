from uuid import uuid4

import pytest

from integrations.platforms.base import ConnectorConfigurationRequired
from integrations.platforms.token_store import (
    DisabledTokenStore,
    OAuthTokenSet,
    TokenStoreContext,
)


def test_disabled_token_store_fails_closed_for_every_token_operation() -> None:
    store = DisabledTokenStore()
    context = TokenStoreContext(
        organization_id=uuid4(),
        actor_id=uuid4(),
        platform_code="FACEBOOK",
        attempt_id=uuid4(),
    )
    token_set = OAuthTokenSet(access_token="fixture-access", refresh_token="fixture-refresh")

    assert "fixture-access" not in repr(token_set)
    assert "fixture-refresh" not in repr(token_set)

    with pytest.raises(ConnectorConfigurationRequired):
        store.store(token_set, context)
    with pytest.raises(ConnectorConfigurationRequired):
        store.resolve("vault://fixture/account")
    with pytest.raises(ConnectorConfigurationRequired):
        store.bind("vault://fixture/account", "candidate-123")
    with pytest.raises(ConnectorConfigurationRequired):
        store.delete("vault://fixture/account")
