from integrations.platforms.authorization import AuthorizationCompletion
from integrations.platforms.linkedin_authorization import LinkedInAuthorizationAdapter
from integrations.platforms.transport import HttpResponse


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


def test_linkedin_keeps_only_approved_administrator_organizations_and_loads_names() -> None:
    transport = RecordingTransport([
        HttpResponse(200, {"access_token": "linkedin-token", "expires_in": 3600}, {}),
        HttpResponse(200, {"elements": [
            {"role": "ADMINISTRATOR", "state": "APPROVED", "organization": "urn:li:organization:123"},
            {"role": "RECRUITING_POSTER", "state": "APPROVED", "organization": "urn:li:organization:999"},
            {"role": "ADMINISTRATOR", "state": "REVOKED", "organization": "urn:li:organization:777"},
        ]}, {}),
        HttpResponse(200, {"id": 123, "localizedName": "Acme LinkedIn"}, {}),
    ])
    adapter = LinkedInAuthorizationAdapter(
        transport=transport,
        client_id="fixture-client",
        client_secret="fixture-secret",
        api_version="202603",
    )

    bundle, accounts, granted = adapter.complete(AuthorizationCompletion(
        code="fixture-linkedin-code",
        redirect_uri="https://local.invalid/linkedin/callback",
        pkce_reference="",
    ))

    assert [(item.channel, item.external_id, item.display_name) for item in accounts] == [
        ("LINKEDIN", "123", "Acme LinkedIn"),
    ]
    assert granted == ("PUBLISH", "METRICS_READ")
    assert bundle.primary.access_token == "linkedin-token"
    assert [url for _method, url, _kwargs in transport.requests] == [
        "https://www.linkedin.com/oauth/v2/accessToken",
        "https://api.linkedin.com/rest/organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED",
        "https://api.linkedin.com/rest/organizations/123",
    ]
    discovery_headers = transport.requests[1][2]["headers"]
    assert discovery_headers["LinkedIn-Version"] == "202603"
    assert discovery_headers["X-Restli-Protocol-Version"] == "2.0.0"
    assert set(bundle.candidate_tokens) == {accounts[0].candidate_id}

