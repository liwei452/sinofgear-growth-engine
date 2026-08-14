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


class TikTokAuthorizationAdapter:
    TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
    CREATOR_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"

    def __init__(
        self, *, transport, client_key: str, client_secret: str,
        client_audited: bool,
    ):
        self.transport = transport
        self.client_key = client_key
        self.client_secret = client_secret
        self.client_audited = client_audited

    def complete(self, request: AuthorizationCompletion):
        issued_at = datetime.now(UTC)
        try:
            exchanged = self.transport.request(
                "POST", self.TOKEN_URL,
                headers={"Content-Type": "application/json"},
                json={
                    "client_key": self.client_key, "client_secret": self.client_secret,
                    "code": request.code, "grant_type": "authorization_code",
                    "redirect_uri": request.redirect_uri,
                    "code_verifier_reference": request.pkce_reference,
                }, timeout_seconds=20,
            )
            if not 200 <= exchanged.status_code < 300:
                raise normalized_failure(exchanged.status_code, during_exchange=True)
            access_token = exchanged.json_body.get("access_token")
            open_id = exchanged.json_body.get("open_id")
            if not all(isinstance(value, str) and value for value in (access_token, open_id)):
                raise ProviderAuthorizationError("AUTHORIZATION_REJECTED")
            expires_in = exchanged.json_body.get("expires_in")
            expires_at = issued_at + timedelta(seconds=expires_in) if isinstance(expires_in, int) else None
            primary = OAuthTokenSet(
                access_token=access_token,
                refresh_token=str(exchanged.json_body.get("refresh_token", "")),
                expires_at=expires_at,
            )
            creator = self.transport.request(
                "POST", self.CREATOR_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                }, json={}, timeout_seconds=20,
            )
            if not 200 <= creator.status_code < 300:
                raise normalized_failure(creator.status_code)
        except TimeoutError as error:
            raise ProviderAuthorizationError("PROVIDER_UNAVAILABLE") from error
        error_code = creator.json_body.get("error", {}).get("code")
        data = creator.json_body.get("data", {})
        if error_code not in {None, "ok"} or not isinstance(data, dict):
            raise ProviderAuthorizationError("INSUFFICIENT_CAPABILITY")
        privacy_options = data.get("privacy_level_options", [])
        if "SELF_ONLY" not in privacy_options:
            raise ProviderAuthorizationError("INSUFFICIENT_CAPABILITY")
        name = data.get("creator_nickname") or data.get("creator_username")
        if not isinstance(name, str) or not name:
            raise ProviderAuthorizationError("NO_MANAGEABLE_ACCOUNT")
        candidate_id = stable_candidate_id("TIKTOK", open_id)
        publication_mode = (
            "PUBLIC"
            if self.client_audited and "PUBLIC_TO_EVERYONE" in privacy_options
            else "PRIVATE_ONLY"
        )
        account = ManagedPublishingAccount(
            candidate_id=candidate_id,
            external_id=open_id,
            display_name=name,
            channel="TIKTOK",
            capabilities=("PUBLISH",),
            publication_mode=publication_mode,
            discovered_at=issued_at,
        )
        bundle = ProviderCredentialBundle(primary, {candidate_id: primary}, issued_at)
        return bundle, [account], ("PUBLISH",)

