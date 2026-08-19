import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.identity.models import Organization
from apps.platforms.models import (
    ConnectorCredential,
    Platform,
    ProviderConnection,
    SocialAccount,
)


def _org(slug=None):
    return Organization.objects.create(name=slug or "Org", slug=slug or f"org-{uuid.uuid4().hex[:10]}")


def _platform():
    return Platform.objects.create(code=f"PLAT-{uuid.uuid4().hex[:10]}", name="Platform")


def _credential(org, platform):
    return ConnectorCredential.objects.create(
        organization=org,
        platform=platform,
        secret_reference="vault://fixture",
        granted_scopes=["PUBLISH"],
    )


def _buffer(org, **overrides):
    values = dict(
        provider=ProviderConnection.Provider.BUFFER,
        credential_reference="vault://buffer",
        external_id="buffer-workspace-1",
        connection_state=ProviderConnection.ConnectionState.CONNECTED,
    )
    values.update(overrides)
    return ProviderConnection.objects.create(organization=org, **values)


@pytest.mark.django_db
def test_same_organization_can_only_have_one_buffer_connection():
    org = _org()
    _buffer(org)
    with pytest.raises(ValidationError):
        _buffer(org, external_id="buffer-workspace-2")


@pytest.mark.django_db
def test_different_organizations_can_each_have_buffer_connection():
    first = _org()
    second = _org()
    _buffer(first)
    _buffer(second)
    assert ProviderConnection.objects.count() == 2


@pytest.mark.django_db
def test_connected_buffer_requires_credential_reference():
    org = _org()
    with pytest.raises(ValidationError, match="credential reference"):
        _buffer(org, credential_reference="")


@pytest.mark.django_db
def test_connected_buffer_requires_external_id():
    org = _org()
    with pytest.raises(ValidationError, match="external id"):
        _buffer(org, external_id="")


@pytest.mark.django_db
def test_granted_scopes_must_be_unique_string_list():
    org = _org()
    with pytest.raises(ValidationError, match="list"):
        _buffer(org, granted_scopes="not-a-list")
    with pytest.raises(ValidationError, match="strings"):
        _buffer(org, granted_scopes=["PUBLISH", 123])
    with pytest.raises(ValidationError, match="duplicates"):
        _buffer(org, granted_scopes=["PUBLISH", "PUBLISH"])


@pytest.mark.django_db
def test_provider_metadata_must_be_dict():
    org = _org()
    with pytest.raises(ValidationError, match="dict"):
        _buffer(org, provider_metadata=["not", "a", "dict"])


@pytest.mark.django_db
def test_existing_direct_account_shape_is_valid():
    org = _org()
    platform = _platform()
    credential = _credential(org, platform)
    account = SocialAccount.objects.create(
        organization=org,
        platform=platform,
        credential=credential,
        external_id="page-1",
        display_name="LinkedIn Page",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
    )
    assert account.provider == SocialAccount.Provider.DIRECT
    assert account.provider_connection_id is None
    assert account.provider_account_id == ""


@pytest.mark.django_db
def test_direct_account_rejects_provider_connection():
    org = _org()
    platform = _platform()
    connection = _buffer(org)
    with pytest.raises(ValidationError, match="provider connection"):
        SocialAccount.objects.create(
            organization=org,
            platform=platform,
            provider=SocialAccount.Provider.DIRECT,
            provider_connection=connection,
            external_id="page-1",
            display_name="LinkedIn Page",
        )


@pytest.mark.django_db
def test_direct_account_rejects_provider_account_id():
    org = _org()
    platform = _platform()
    with pytest.raises(ValidationError, match="provider account id"):
        SocialAccount.objects.create(
            organization=org,
            platform=platform,
            provider=SocialAccount.Provider.DIRECT,
            provider_account_id="buffer-channel-1",
            external_id="page-1",
            display_name="LinkedIn Page",
        )


@pytest.mark.django_db
def test_buffer_account_requires_provider_connection():
    org = _org()
    platform = _platform()
    with pytest.raises(ValidationError, match="provider connection"):
        SocialAccount.objects.create(
            organization=org,
            platform=platform,
            provider=SocialAccount.Provider.BUFFER,
            provider_account_id="buffer-channel-1",
            external_id="page-1",
            display_name="LinkedIn Page",
        )


@pytest.mark.django_db
def test_buffer_account_requires_provider_account_id():
    org = _org()
    platform = _platform()
    connection = _buffer(org)
    with pytest.raises(ValidationError, match="provider account id"):
        SocialAccount.objects.create(
            organization=org,
            platform=platform,
            provider=SocialAccount.Provider.BUFFER,
            provider_connection=connection,
            provider_account_id="",
            external_id="page-1",
            display_name="LinkedIn Page",
        )


@pytest.mark.django_db
def test_buffer_account_rejects_direct_credential():
    org = _org()
    platform = _platform()
    connection = _buffer(org)
    credential = _credential(org, platform)
    with pytest.raises(ValidationError, match="credential"):
        SocialAccount.objects.create(
            organization=org,
            platform=platform,
            provider=SocialAccount.Provider.BUFFER,
            provider_connection=connection,
            provider_account_id="buffer-channel-1",
            credential=credential,
            external_id="page-1",
            display_name="LinkedIn Page",
        )


@pytest.mark.django_db
def test_buffer_account_rejects_foreign_provider_connection():
    org = _org()
    other = _org()
    platform = _platform()
    connection = _buffer(other)
    with pytest.raises(ValidationError, match="organization"):
        SocialAccount.objects.create(
            organization=org,
            platform=platform,
            provider=SocialAccount.Provider.BUFFER,
            provider_connection=connection,
            provider_account_id="buffer-channel-1",
            external_id="page-1",
            display_name="LinkedIn Page",
        )


@pytest.mark.django_db
def test_buffer_account_rejects_mismatched_provider():
    org = _org()
    platform = _platform()
    connection = _buffer(org)
    connection.provider = "TWITTER"
    account = SocialAccount(
        organization=org,
        platform=platform,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id="buffer-channel-1",
        external_id="page-1",
        display_name="LinkedIn Page",
    )
    with pytest.raises(ValidationError, match="must match"):
        account.clean()


@pytest.mark.django_db
def test_duplicate_buffer_channel_is_rejected():
    org = _org()
    platform = _platform()
    connection = _buffer(org)
    SocialAccount.objects.create(
        organization=org,
        platform=platform,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id="buffer-channel-1",
        external_id="page-1",
        display_name="LinkedIn Page",
    )
    with pytest.raises(ValidationError):
        SocialAccount.objects.create(
            organization=org,
            platform=platform,
            provider=SocialAccount.Provider.BUFFER,
            provider_connection=connection,
            provider_account_id="buffer-channel-1",
            external_id="page-2",
            display_name="LinkedIn Page 2",
        )


@pytest.mark.django_db
def test_provider_connection_cannot_be_deleted_while_in_use():
    org = _org()
    platform = _platform()
    connection = _buffer(org)
    SocialAccount.objects.create(
        organization=org,
        platform=platform,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id="buffer-channel-1",
        external_id="page-1",
        display_name="LinkedIn Page",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        connection.delete()


@pytest.mark.django_db
def test_queryset_update_direct_to_buffer_raises_integrity_error():
    org = _org()
    platform = _platform()
    credential = _credential(org, platform)
    account = SocialAccount.objects.create(
        organization=org,
        platform=platform,
        credential=credential,
        external_id="page-1",
        display_name="LinkedIn Page",
    )
    with pytest.raises(IntegrityError):
        SocialAccount.objects.filter(pk=account.pk).update(
            provider=SocialAccount.Provider.BUFFER
        )


@pytest.mark.django_db
def test_bulk_create_connected_without_credential_reference_raises_integrity_error():
    org = _org()
    with pytest.raises(IntegrityError):
        ProviderConnection.objects.bulk_create(
            [
                ProviderConnection(
                    organization=org,
                    provider=ProviderConnection.Provider.BUFFER,
                    credential_reference="",
                    external_id="buffer-workspace-1",
                    connection_state=ProviderConnection.ConnectionState.CONNECTED,
                )
            ]
        )


@pytest.mark.django_db
def test_bulk_create_connected_without_external_id_raises_integrity_error():
    org = _org()
    with pytest.raises(IntegrityError):
        ProviderConnection.objects.bulk_create(
            [
                ProviderConnection(
                    organization=org,
                    provider=ProviderConnection.Provider.BUFFER,
                    credential_reference="vault://buffer",
                    external_id="",
                    connection_state=ProviderConnection.ConnectionState.CONNECTED,
                )
            ]
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "provider_metadata",
    [
        {"access_token": "x"},
        {"refresh_token": "x"},
        {"client_secret": "x"},
        {"authorization": "x"},
        {"password": "x"},
        {"secret": "x"},
        {"credential": "x"},
        {"nested": {"access_token": "x"}},
        {"list": [{"client_secret": "x"}]},
    ],
)
def test_provider_metadata_rejects_sensitive_keys(provider_metadata):
    org = _org()
    with pytest.raises(ValidationError, match="sensitive"):
        _buffer(org, provider_metadata=provider_metadata)


@pytest.mark.django_db
def test_buffer_account_rejects_whitespace_provider_account_id():
    org = _org()
    platform = _platform()
    connection = _buffer(org)
    with pytest.raises(ValidationError, match="provider account id"):
        SocialAccount.objects.create(
            organization=org,
            platform=platform,
            provider=SocialAccount.Provider.BUFFER,
            provider_connection=connection,
            provider_account_id="   ",
            external_id="page-1",
            display_name="LinkedIn Page",
        )


@pytest.mark.django_db
def test_buffer_account_strips_provider_account_id():
    org = _org()
    platform = _platform()
    connection = _buffer(org)
    account = SocialAccount.objects.create(
        organization=org,
        platform=platform,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id=" channel-1 ",
        external_id="page-1",
        display_name="LinkedIn Page",
    )
    assert account.provider_account_id == "channel-1"


@pytest.mark.django_db
def test_direct_account_rejects_whitespace_provider_account_id():
    org = _org()
    platform = _platform()
    with pytest.raises(ValidationError, match="provider account id"):
        SocialAccount.objects.create(
            organization=org,
            platform=platform,
            provider=SocialAccount.Provider.DIRECT,
            provider_account_id="   ",
            external_id="page-1",
            display_name="LinkedIn Page",
        )


@pytest.mark.django_db
def test_provider_account_id_must_be_string():
    org = _org()
    platform = _platform()
    connection = _buffer(org)
    account = SocialAccount(
        organization=org,
        platform=platform,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id=123,
        external_id="page-1",
        display_name="LinkedIn Page",
    )
    with pytest.raises(ValidationError, match="string"):
        account.clean()
