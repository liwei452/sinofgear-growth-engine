import pytest

from integrations.platforms.base import OfficialPublishRequest
from integrations.platforms.linkedin import LinkedInConnector
from integrations.platforms.token_store import OAuthTokenSet
from integrations.platforms.transport import HttpResponse


class TokenStore:
    def resolve(self, reference: str) -> OAuthTokenSet:
        return OAuthTokenSet(access_token="linkedin-token")


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.response


def request() -> OfficialPublishRequest:
    return OfficialPublishRequest(
        channel="LINKEDIN",
        account_external_id="5515715",
        credential_reference="vault://linkedin/acme",
        payload={"commentary": "Factory inspection evidence"},
        idempotency_key="linkedin-batch",
        consent={},
    )


def test_linkedin_posts_as_organization_with_versioned_rest_contract() -> None:
    transport = RecordingTransport(HttpResponse(201, {}, {"x-restli-id": "urn:li:share:123"}))

    result = LinkedInConnector(
        transport=transport, token_store=TokenStore(), api_version="202607",
    ).publish(request())

    assert result.status == "SUCCEEDED"
    assert result.external_id == "urn:li:share:123"
    method, url, kwargs = transport.requests[0]
    assert (method, url) == ("POST", "https://api.linkedin.com/rest/posts")
    assert kwargs["headers"] == {
        "Authorization": "Bearer linkedin-token",
        "LinkedIn-Version": "202607",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
        "X-RestLi-Idempotency-Key": "linkedin-batch",
    }
    assert kwargs["json"] == {
        "author": "urn:li:organization:5515715",
        "commentary": "Factory inspection evidence",
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [(400, "VALIDATION_REJECTED", False), (401, "REAUTHORIZATION_REQUIRED", False),
     (403, "VALIDATION_REJECTED", False), (429, "RATE_LIMITED", True),
     (503, "PROVIDER_UNAVAILABLE", True)],
)
def test_linkedin_errors_are_normalized(
    status_code: int, expected_code: str, retryable: bool,
) -> None:
    transport = RecordingTransport(HttpResponse(
        status_code, {"message": "linkedin-token rejected"}, {"Retry-After": "9"},
    ))

    result = LinkedInConnector(
        transport=transport, token_store=TokenStore(), api_version="202607",
    ).publish(request())

    assert result.error_code == expected_code
    assert result.retryable is retryable
    assert result.retry_after_seconds == (9 if status_code == 429 else None)
    assert "linkedin-token" not in result.error_message
