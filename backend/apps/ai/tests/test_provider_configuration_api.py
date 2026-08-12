import json
from types import TracebackType

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.ai.models import AIProviderConfiguration
from apps.identity.models import Membership, Organization, Role
from integrations.ai.providers import ProviderResult
from integrations.credentials import credential_store_override
from rest_framework.exceptions import ParseError
from rest_framework.test import APIRequestFactory

from apps.ai.views import DuplicateSafeJSONParser
from apps.ai.provider_configuration import _clear_uncertain


SECRET = "sk-api-secret-1234567890"
URL = "/api/v1/ai-provider-configuration"


class Store:
    def __init__(self):
        self.values = {}

    def read(self, target): return self.values.get(target)
    def write(self, target, secret): self.values[target] = secret
    def delete(self, target): return self.values.pop(target, None) is not None


class Provider:
    def __init__(self, credential_store): self.store = credential_store
    def generate(self, **kwargs):
        assert self.store.read(self.store.target) == SECRET
        return ProviderResult(output={"connected": True}, metadata={})


@pytest.fixture
def api_context(db, monkeypatch):
    own = Organization.objects.create(name="Own", slug="ai-api-own")
    other = Organization.objects.create(name="Other", slug="ai-api-other")
    roles = {
        r.code: r for r in (Role.objects.create_administrator(), Role.objects.create_operator())
    }
    admin = get_user_model().objects.create_user(username="admin", password="password")
    operator = get_user_model().objects.create_user(username="operator", password="password")
    other_admin = get_user_model().objects.create_user(username="other-admin", password="password")
    Membership.objects.create(user=admin, organization=own, role=roles[Role.Code.ADMINISTRATOR])
    Membership.objects.create(user=operator, organization=own, role=roles[Role.Code.OPERATOR])
    Membership.objects.create(user=other_admin, organization=other, role=roles[Role.Code.ADMINISTRATOR])
    monkeypatch.setattr("apps.ai.provider_configuration.DeepSeekProvider", Provider)
    yield own, other, admin, operator, other_admin
    _clear_uncertain(own.id)
    _clear_uncertain(other.id)


def payload():
    return {
        "api_key": SECRET,
        "daily_budget_usd": "10.00",
        "flash_max_output_tokens": 1200,
        "pro_max_output_tokens": 2400,
        "timeout_seconds": 30,
    }


def authenticated(user, *, csrf=False):
    client = APIClient(enforce_csrf_checks=csrf)
    if csrf:
        assert client.login(username=user.username, password="password")
    else:
        client.force_authenticate(user)
    return client


def assert_secret_absent_from_exception_graph(error, secret):
    pending = [error]
    seen = set()
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        assert secret not in repr(value)
        if isinstance(value, TracebackType):
            if value.tb_frame.f_globals.get("__name__") == "apps.ai.views":
                pending.append(value.tb_frame.f_locals)
            if value.tb_next is not None:
                pending.append(value.tb_next)
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set)):
            pending.extend(value)
        elif isinstance(value, BaseException):
            pending.append(vars(value))
        cause = getattr(value, "__cause__", None)
        context = getattr(value, "__context__", None)
        traceback = getattr(value, "__traceback__", None)
        pending.extend(item for item in (cause, context, traceback) if item is not None)


def test_admin_can_save_get_delete_without_secret_and_is_org_scoped(api_context):
    own, other, admin, _, other_admin = api_context
    class RestoreFailingStore(Store):
        def write(self, target, secret):
            if secret == "sk-old-key":
                raise RuntimeError("replace with credential error")
            return super().write(target, secret)

    store = RestoreFailingStore()
    with credential_store_override(store):
        response = authenticated(admin).put(URL, payload(), format="json")
        assert response.status_code == 200
        assert SECRET not in response.content.decode()
        assert response.data["key_suffix"] == SECRET[-4:]
        assert authenticated(other_admin).get(URL).data["connection_state"] == "NOT_CONFIGURED"
        assert AIProviderConfiguration.objects.get(organization=own).provider_code == "deepseek"
        assert not AIProviderConfiguration.objects.filter(organization=other).exists()
        assert authenticated(admin).delete(URL).status_code == 200


def test_non_admin_unknown_fields_bad_limits_duplicate_json_and_csrf_are_rejected(api_context):
    _, _, admin, operator, _ = api_context
    store = Store()
    with credential_store_override(store):
        assert authenticated(operator).get(URL).status_code == 403
        bad = payload() | {"mystery": "x"}
        assert authenticated(admin).put(URL, bad, format="json").status_code == 400
        bad = payload() | {"timeout_seconds": 0}
        assert authenticated(admin).put(URL, bad, format="json").status_code == 400
        duplicate = json.dumps(payload())[:-1] + ',"api_key":"sk-other-secret"}'
        assert authenticated(admin).put(URL, duplicate, content_type="application/json").status_code == 400
        assert authenticated(admin, csrf=True).put(URL, payload(), format="json").status_code == 403


def test_test_endpoint_does_not_save_submitted_replacement(api_context):
    _, _, admin, _, _ = api_context
    store = Store()
    with credential_store_override(store):
        response = authenticated(admin).post(f"{URL}/test", {"api_key": SECRET}, format="json")
        assert response.status_code == 200
        assert response.data == {"connection_state": "CONNECTED", "recovery_code": None}
        assert store.values == {}
        assert not AIProviderConfiguration.objects.exists()


@pytest.mark.parametrize(
    "body",
    [b'{"api_key":"sk-parser-secret-1234567890",', b'\xffsk-parser-secret-1234567890'],
)
def test_malformed_json_parse_error_does_not_retain_body_or_secret(body, caplog):
    parser = DuplicateSafeJSONParser()
    request = APIRequestFactory().put(URL, body, content_type="application/json")
    with pytest.raises(ParseError) as caught:
        parser.parse(request, parser_context={"encoding": "utf-8"})
    error = caught.value
    assert error.__cause__ is None
    assert error.__context__ is None
    assert_secret_absent_from_exception_graph(error, "sk-parser-secret")
    assert "sk-parser-secret" not in caplog.text


def test_duplicate_json_parse_error_does_not_retain_submitted_secret(caplog):
    parser = DuplicateSafeJSONParser()
    secret = "sk-duplicate-parser-secret-1234567890"
    body = json.dumps({"api_key": secret})[:-1] + f',"api_key":"{secret}"}}'
    request = APIRequestFactory().put(
        URL, body.encode(), content_type="application/json"
    )
    with pytest.raises(ParseError) as caught:
        parser.parse(request, parser_context={"encoding": "utf-8"})
    error = caught.value
    assert error.__cause__ is None
    assert error.__context__ is None
    assert_secret_absent_from_exception_graph(error, secret)
    assert secret not in caplog.text


def test_uncertain_registry_forces_fail_closed_get_and_is_organization_scoped(
    api_context, monkeypatch
):
    own, other, admin, _, other_admin = api_context
    own_configuration = AIProviderConfiguration.objects.create(
        organization=own, connection_state="CONNECTED", key_suffix="old1"
    )
    AIProviderConfiguration.objects.create(
        organization=other, connection_state="CONNECTED", key_suffix="safe"
    )
    store = Store()
    store.values[f"SinofGear/DeepSeek/{own.id}"] = "sk-old-key"
    original_save = AIProviderConfiguration.save

    def fail_every_save(self, *args, **kwargs):
        raise RuntimeError(f"database failure {SECRET}")

    monkeypatch.setattr(AIProviderConfiguration, "save", fail_every_save)
    from apps.ai.provider_configuration import delete_deepseek_credential

    from integrations.credentials import CredentialStoreError
    original_write = store.write

    def fail_restore(target, secret):
        if secret == "sk-old-key":
            raise CredentialStoreError("safe")
        return original_write(target, secret)

    store.write = fail_restore
    with credential_store_override(store), pytest.raises(Exception):
        delete_deepseek_credential(organization=own, actor=admin)

    response = authenticated(admin).get(URL)
    assert response.data["connection_state"] == "NEEDS_RECONNECT"
    assert response.data["key_suffix"] == ""
    other_response = authenticated(other_admin).get(URL)
    assert other_response.data["connection_state"] == "CONNECTED"
    assert other_response.data["key_suffix"] == "safe"

    monkeypatch.setattr(AIProviderConfiguration, "save", original_save)
    with credential_store_override(store):
        repaired = authenticated(admin).put(URL, payload(), format="json")
    assert repaired.status_code == 200
    assert repaired.data["connection_state"] == "CONNECTED"
    assert repaired.data["key_suffix"] == SECRET[-4:]
    own_configuration.refresh_from_db()


def test_openapi_documents_fixed_provider_failure_shape():
    schema = APIClient().get("/api/v1/schema").json()
    for path, method in ((URL, "put"), (URL, "delete"), (f"{URL}/test", "post")):
        response = schema["paths"][path][method]["responses"]["400"]
        rendered = json.dumps(response)
        assert "AIProviderConfigurationTestResult" in rendered
