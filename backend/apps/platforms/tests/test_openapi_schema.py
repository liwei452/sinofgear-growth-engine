import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_openapi_describes_platform_and_social_account_envelopes() -> None:
    schema = APIClient().get("/api/v1/schema").json()
    platform_get = schema["paths"]["/api/v1/platforms"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    accounts_get = schema["paths"]["/api/v1/social-accounts"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    accounts_post = schema["paths"]["/api/v1/social-accounts"]["post"]

    assert platform_get["$ref"].endswith("PlatformList")
    assert accounts_get["$ref"].endswith("SocialAccountList")
    assert accounts_post["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("SocialAccountCreate")
    assert accounts_post["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith("SocialAccountRead")
    assert {"get", "patch"} <= set(schema["paths"]["/api/v1/social-accounts/{account_id}"])
    assert {"get", "post"} <= set(schema["paths"]["/api/v1/connector-credentials"])
    assert "patch" in schema["paths"]["/api/v1/connector-credentials/{credential_id}"]
