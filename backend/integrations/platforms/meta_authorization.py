from datetime import UTC, datetime, timedelta

from .authorization import (
    AuthorizationCompletion,
    ManagedPublishingAccount,
    ProviderAuthorizationError,
    ProviderCredentialBundle,
    normalized_failure,
    stable_candidate_id,
)
from .token_store import OAuthTokenSet


class MetaAuthorizationAdapter:
    def __init__(
        self, *, transport, client_id: str, client_secret: str,
        graph_base_url: str = "https://graph.facebook.com/v23.0",
    ):
        self.transport = transport
        self.client_id = client_id
        self.client_secret = client_secret
        self.graph_base_url = graph_base_url.rstrip("/")

    def complete(self, request: AuthorizationCompletion):
        issued_at = datetime.now(UTC)
        try:
            exchanged = self.transport.request(
                "POST",
                f"{self.graph_base_url}/oauth/access_token",
                headers={"Content-Type": "application/json"},
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": request.code,
                    "redirect_uri": request.redirect_uri,
                },
                timeout_seconds=20,
            )
            if not 200 <= exchanged.status_code < 300:
                raise normalized_failure(exchanged.status_code, during_exchange=True)
            user_token = exchanged.json_body.get("access_token")
            if not isinstance(user_token, str) or not user_token:
                raise ProviderAuthorizationError("AUTHORIZATION_REJECTED")
            expires_in = exchanged.json_body.get("expires_in")
            expires_at = issued_at + timedelta(seconds=expires_in) if isinstance(expires_in, int) else None
            primary = OAuthTokenSet(access_token=user_token, expires_at=expires_at)
            discovered = self.transport.request(
                "GET",
                f"{self.graph_base_url}/me/accounts?fields=id,name,access_token,tasks,instagram_business_account{{id,name}}",
                headers={"Authorization": f"Bearer {user_token}"},
                json=None,
                timeout_seconds=20,
            )
            if not 200 <= discovered.status_code < 300:
                raise normalized_failure(discovered.status_code)
        except TimeoutError as error:
            raise ProviderAuthorizationError("PROVIDER_UNAVAILABLE") from error

        accounts: list[ManagedPublishingAccount] = []
        candidate_tokens: dict[str, OAuthTokenSet] = {}
        data = discovered.json_body.get("data", [])
        for page in data if isinstance(data, list) else []:
            if not isinstance(page, dict) or "CREATE_CONTENT" not in page.get("tasks", []):
                continue
            page_id = page.get("id")
            page_name = page.get("name")
            page_token = page.get("access_token")
            if not all(isinstance(value, str) and value for value in (page_id, page_name, page_token)):
                continue
            capabilities = ("PUBLISH", "METRICS_READ") if "ANALYZE" in page.get("tasks", []) else ("PUBLISH",)
            page_candidate_id = stable_candidate_id("FACEBOOK", page_id)
            accounts.append(ManagedPublishingAccount(
                candidate_id=page_candidate_id,
                external_id=page_id,
                display_name=page_name,
                channel="FACEBOOK",
                capabilities=capabilities,
                publication_mode="PUBLIC",
                discovered_at=issued_at,
            ))
            page_oauth = OAuthTokenSet(access_token=page_token, expires_at=expires_at)
            candidate_tokens[page_candidate_id] = page_oauth
            instagram = page.get("instagram_business_account")
            if isinstance(instagram, dict):
                instagram_id = instagram.get("id")
                instagram_name = instagram.get("name") or f"{page_name} Instagram"
                if isinstance(instagram_id, str) and instagram_id and isinstance(instagram_name, str):
                    instagram_candidate_id = stable_candidate_id("INSTAGRAM", instagram_id)
                    accounts.append(ManagedPublishingAccount(
                        candidate_id=instagram_candidate_id,
                        external_id=instagram_id,
                        display_name=instagram_name,
                        channel="INSTAGRAM",
                        capabilities=capabilities,
                        publication_mode="PUBLIC",
                        discovered_at=issued_at,
                    ))
                    candidate_tokens[instagram_candidate_id] = page_oauth
        if not accounts:
            raise ProviderAuthorizationError("NO_MANAGEABLE_ACCOUNT")
        granted = tuple(code for code in ("PUBLISH", "METRICS_READ") if any(
            code in account.capabilities for account in accounts
        ))
        return ProviderCredentialBundle(primary, candidate_tokens, issued_at), accounts, granted

