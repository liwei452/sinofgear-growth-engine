import re
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


class LinkedInAuthorizationAdapter:
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    ACL_URL = "https://api.linkedin.com/rest/organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED"

    def __init__(self, *, transport, client_id: str, client_secret: str, api_version: str):
        if not re.fullmatch(r"\d{6}", api_version):
            raise ValueError("LinkedIn API version must use YYYYMM format.")
        self.transport = transport
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_version = api_version

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": self.api_version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    def complete(self, request: AuthorizationCompletion):
        issued_at = datetime.now(UTC)
        try:
            exchanged = self.transport.request(
                "POST", self.TOKEN_URL,
                headers={"Content-Type": "application/json"},
                json={
                    "grant_type": "authorization_code", "code": request.code,
                    "client_id": self.client_id, "client_secret": self.client_secret,
                    "redirect_uri": request.redirect_uri,
                }, timeout_seconds=20,
            )
            if not 200 <= exchanged.status_code < 300:
                raise normalized_failure(exchanged.status_code, during_exchange=True)
            access_token = exchanged.json_body.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise ProviderAuthorizationError("AUTHORIZATION_REJECTED")
            expires_in = exchanged.json_body.get("expires_in")
            expires_at = issued_at + timedelta(seconds=expires_in) if isinstance(expires_in, int) else None
            primary = OAuthTokenSet(access_token=access_token, expires_at=expires_at)
            acl = self.transport.request(
                "GET", self.ACL_URL, headers=self._headers(access_token),
                json=None, timeout_seconds=20,
            )
            if not 200 <= acl.status_code < 300:
                raise normalized_failure(acl.status_code)
            accounts = []
            candidate_tokens = {}
            elements = acl.json_body.get("elements", [])
            for item in elements if isinstance(elements, list) else []:
                if not isinstance(item, dict) or item.get("role") != "ADMINISTRATOR" or item.get("state") != "APPROVED":
                    continue
                urn = item.get("organization") or item.get("organizationTarget")
                if not isinstance(urn, str) or not urn.startswith("urn:li:organization:"):
                    continue
                organization_id = urn.rsplit(":", 1)[-1]
                details = self.transport.request(
                    "GET", f"https://api.linkedin.com/rest/organizations/{organization_id}",
                    headers=self._headers(access_token), json=None, timeout_seconds=20,
                )
                if not 200 <= details.status_code < 300:
                    raise normalized_failure(details.status_code)
                name = details.json_body.get("localizedName")
                if not isinstance(name, str) or not name:
                    continue
                candidate_id = stable_candidate_id("LINKEDIN", organization_id)
                accounts.append(ManagedPublishingAccount(
                    candidate_id=candidate_id,
                    external_id=organization_id,
                    display_name=name,
                    channel="LINKEDIN",
                    capabilities=("PUBLISH", "METRICS_READ"),
                    publication_mode="PUBLIC",
                    discovered_at=issued_at,
                ))
                candidate_tokens[candidate_id] = primary
        except TimeoutError as error:
            raise ProviderAuthorizationError("PROVIDER_UNAVAILABLE") from error
        if not accounts:
            raise ProviderAuthorizationError("NO_MANAGEABLE_ACCOUNT")
        return ProviderCredentialBundle(primary, candidate_tokens, issued_at), accounts, ("PUBLISH", "METRICS_READ")

