from datetime import UTC, datetime, timedelta

from .authorization import (
    AuthorizationCompletion,
    ManagedPublishingAccount,
    ProviderAuthorizationError,
    ProviderCredentialBundle,
    normalized_failure,
    stable_candidate_id,
)
from .provider_config import YOUTUBE_UPLOAD_SCOPE
from .token_store import OAuthTokenSet


class YouTubeAuthorizationAdapter:
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true"

    def __init__(self, *, transport, client_id: str, client_secret: str):
        self.transport = transport
        self.client_id = client_id
        self.client_secret = client_secret

    def complete(self, request: AuthorizationCompletion):
        issued_at = datetime.now(UTC)
        try:
            exchanged = self.transport.request(
                "POST",
                self.TOKEN_URL,
                headers={"Content-Type": "application/json"},
                json={
                    "code": request.code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": request.redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout_seconds=20,
            )
            if not 200 <= exchanged.status_code < 300:
                raise normalized_failure(exchanged.status_code, during_exchange=True)
            access_token = exchanged.json_body.get("access_token")
            scopes = tuple(str(exchanged.json_body.get("scope", "")).split())
            if (
                not isinstance(access_token, str)
                or not access_token
                or YOUTUBE_UPLOAD_SCOPE not in scopes
            ):
                raise ProviderAuthorizationError("INSUFFICIENT_CAPABILITY")
            expires_in = exchanged.json_body.get("expires_in")
            expires_at = (
                issued_at + timedelta(seconds=expires_in)
                if isinstance(expires_in, int)
                else None
            )
            primary = OAuthTokenSet(
                access_token=access_token,
                refresh_token=str(exchanged.json_body.get("refresh_token", "")),
                expires_at=expires_at,
                token_type=str(exchanged.json_body.get("token_type", "Bearer")),
                provider_scopes=scopes,
            )
            discovered = self.transport.request(
                "GET",
                self.CHANNELS_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json=None,
                timeout_seconds=20,
            )
            if not 200 <= discovered.status_code < 300:
                raise normalized_failure(discovered.status_code)
            accounts = []
            candidate_tokens = {}
            for item in discovered.json_body.get("items", []):
                external_id = item.get("id") if isinstance(item, dict) else None
                snippet = item.get("snippet", {}) if isinstance(item, dict) else {}
                title = snippet.get("title") if isinstance(snippet, dict) else None
                if not all(isinstance(value, str) and value for value in (external_id, title)):
                    continue
                candidate_id = stable_candidate_id("YOUTUBE", external_id)
                accounts.append(ManagedPublishingAccount(
                    candidate_id=candidate_id,
                    external_id=external_id,
                    display_name=title,
                    channel="YOUTUBE",
                    capabilities=("PUBLISH", "METRICS_READ"),
                    publication_mode="PUBLIC",
                    discovered_at=issued_at,
                ))
                candidate_tokens[candidate_id] = primary
            if not accounts:
                raise ProviderAuthorizationError("INSUFFICIENT_CAPABILITY")
            return (
                ProviderCredentialBundle(primary, candidate_tokens, issued_at),
                accounts,
                ("PUBLISH", "METRICS_READ"),
            )
        except ProviderAuthorizationError:
            raise
        except TimeoutError as error:
            raise ProviderAuthorizationError("PROVIDER_UNAVAILABLE") from error
        except Exception as error:
            raise ProviderAuthorizationError("AUTHORIZATION_REJECTED") from error
