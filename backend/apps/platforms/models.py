import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import OrganizationScopedModel
from apps.common.security import is_sensitive_key

from .codes import AccountCapability, validate_capability_list


def _find_sensitive_key(value):
    """Return the first sensitive key found anywhere in a JSON-shaped value."""
    if isinstance(value, dict):
        for key, item in value.items():
            if is_sensitive_key(key):
                return key
            nested = _find_sensitive_key(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _find_sensitive_key(item)
            if nested is not None:
                return nested
    return None


class Platform(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["name"]


class PlatformCapability(models.Model):
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name="capability_definitions")
    code = models.CharField(max_length=32, choices=[(code.value, code.value) for code in AccountCapability])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["platform", "code"], name="platforms_unique_capability")]
        ordering = ["code"]


class ConnectorCredential(OrganizationScopedModel):
    platform = models.ForeignKey(Platform, on_delete=models.PROTECT, related_name="connector_credentials")
    secret_reference = models.CharField(max_length=512)
    granted_scopes = models.JSONField(default=list, validators=[validate_capability_list])
    expires_at = models.DateTimeField(null=True, blank=True)


class OAuthConnectionAttempt(OrganizationScopedModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_oauth_attempts",
    )
    platform = models.ForeignKey(
        Platform,
        on_delete=models.PROTECT,
        related_name="oauth_attempts",
    )
    state_hash = models.CharField(max_length=64, unique=True)
    return_path = models.CharField(max_length=512)
    pkce_verifier_reference = models.CharField(max_length=512, blank=True, default="")
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["organization", "platform", "expires_at"],
                name="platforms_oauth_org_exp_idx",
            ),
        ]


class AccountConnectionSession(OrganizationScopedModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_connection_sessions",
    )
    platform = models.ForeignKey(
        Platform,
        on_delete=models.PROTECT,
        related_name="connection_sessions",
    )
    secret_reference = models.CharField(max_length=512)
    candidates = models.JSONField(default=list)
    granted_capabilities = models.JSONField(default=list, validators=[validate_capability_list])
    credential_expires_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    confirmed_candidate_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["organization", "platform", "expires_at"],
                name="platforms_connect_org_exp_idx",
            ),
        ]


class EncryptedOAuthCredential(OrganizationScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ROTATED = "ROTATED", "Rotated"
        DISCONNECTED = "DISCONNECTED", "Disconnected"

    reference = models.CharField(max_length=96, unique=True)
    actor_identifier = models.CharField(max_length=64)
    platform_code = models.CharField(max_length=64)
    connection_attempt_id = models.UUIDField()
    account_binding = models.CharField(max_length=255, blank=True, default="")
    ciphertext = models.BinaryField(blank=True, default=bytes)
    nonce = models.BinaryField(blank=True, default=bytes)
    key_version = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["organization", "platform_code", "status"],
                name="platforms_oauth_vault_idx",
            ),
        ]


class ProviderConnection(OrganizationScopedModel):
    class Provider(models.TextChoices):
        BUFFER = "BUFFER", "Buffer"

    class ConnectionState(models.TextChoices):
        CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED", "Configuration required"
        CONNECTED = "CONNECTED", "Connected"
        REFRESH_DUE = "REFRESH_DUE", "Refresh due"
        REAUTHORIZATION_REQUIRED = "REAUTHORIZATION_REQUIRED", "Reauthorization required"
        INSUFFICIENT_CAPABILITY = "INSUFFICIENT_CAPABILITY", "Insufficient capability"
        PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE", "Provider unavailable"
        DISCONNECTED = "DISCONNECTED", "Disconnected"

    provider = models.CharField(max_length=32, choices=Provider.choices)
    credential_reference = models.CharField(max_length=512, blank=True, default="")
    external_id = models.CharField(max_length=255, blank=True, default="")
    display_name = models.CharField(max_length=255, blank=True, default="")
    granted_scopes = models.JSONField(default=list, blank=True)
    provider_metadata = models.JSONField(default=dict, blank=True)
    connection_state = models.CharField(
        max_length=32,
        choices=ConnectionState.choices,
        default=ConnectionState.CONFIGURATION_REQUIRED,
    )
    last_probe_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    reauthorization_required_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    lifecycle_error_code = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider"],
                name="platforms_unique_provider_connection",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(connection_state="CONNECTED")
                    | (
                        ~models.Q(credential_reference="")
                        & ~models.Q(external_id="")
                    )
                ),
                name="platforms_provider_connection_connected_shape",
            ),
        ]
        ordering = ["provider"]

    def clean(self) -> None:
        super().clean()
        if not isinstance(self.granted_scopes, list):
            raise ValidationError({"granted_scopes": "granted_scopes must be a list."})
        for scope in self.granted_scopes:
            if not isinstance(scope, str):
                raise ValidationError({
                    "granted_scopes": "granted_scopes must contain only strings."
                })
        if len(self.granted_scopes) != len(set(self.granted_scopes)):
            raise ValidationError({
                "granted_scopes": "granted_scopes must not contain duplicates."
            })
        if not isinstance(self.provider_metadata, dict):
            raise ValidationError({"provider_metadata": "provider_metadata must be a dict."})
        sensitive_key = _find_sensitive_key(self.provider_metadata)
        if sensitive_key is not None:
            raise ValidationError({
                "provider_metadata": "provider_metadata must not contain sensitive keys."
            })
        if self.connection_state == self.ConnectionState.CONNECTED:
            if not self.credential_reference.strip():
                raise ValidationError({
                    "credential_reference": "CONNECTED provider requires a credential reference."
                })
            if not self.external_id.strip():
                raise ValidationError({
                    "external_id": "CONNECTED provider requires an external id."
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class SocialAccount(OrganizationScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    class PublishMode(models.TextChoices):
        API_AUTO = "API_AUTO", "API automatic"
        API_CONFIRM = "API_CONFIRM", "API confirmation"
        EXPORT_PACKAGE = "EXPORT_PACKAGE", "Export package"
        MANUAL = "MANUAL", "Manual"

    class ConnectionState(models.TextChoices):
        CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED", "Configuration required"
        CONNECTED = "CONNECTED", "Connected"
        REFRESH_DUE = "REFRESH_DUE", "Refresh due"
        REAUTHORIZATION_REQUIRED = "REAUTHORIZATION_REQUIRED", "Reauthorization required"
        INSUFFICIENT_CAPABILITY = "INSUFFICIENT_CAPABILITY", "Insufficient capability"
        PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE", "Provider unavailable"
        DISCONNECTED = "DISCONNECTED", "Disconnected"

    class Provider(models.TextChoices):
        DIRECT = "DIRECT", "Direct"
        BUFFER = "BUFFER", "Buffer"

    platform = models.ForeignKey(Platform, on_delete=models.PROTECT, related_name="social_accounts")
    credential = models.ForeignKey(
        ConnectorCredential, on_delete=models.SET_NULL, null=True, blank=True, related_name="social_accounts"
    )
    external_id = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    publish_mode = models.CharField(max_length=32, choices=PublishMode.choices, default=PublishMode.MANUAL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    connector_metadata = models.JSONField(default=dict, blank=True)
    connection_state = models.CharField(
        max_length=32,
        choices=ConnectionState.choices,
        default=ConnectionState.CONFIGURATION_REQUIRED,
    )
    last_probe_at = models.DateTimeField(null=True, blank=True)
    last_refresh_at = models.DateTimeField(null=True, blank=True)
    reauthorization_required_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    lifecycle_error_code = models.CharField(max_length=64, blank=True, default="")
    provider = models.CharField(
        max_length=32, choices=Provider.choices, default=Provider.DIRECT,
    )
    provider_connection = models.ForeignKey(
        ProviderConnection,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="social_accounts",
    )
    provider_account_id = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "platform", "external_id"], name="platforms_unique_social_account"
            ),
            models.UniqueConstraint(
                fields=["organization", "provider_connection", "provider_account_id"],
                condition=models.Q(provider_connection__isnull=False),
                name="platforms_unique_buffer_channel",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        provider="DIRECT",
                        provider_connection__isnull=True,
                        provider_account_id="",
                    )
                    | (
                        models.Q(
                            provider="BUFFER",
                            provider_connection__isnull=False,
                            credential__isnull=True,
                        )
                        & ~models.Q(provider_account_id="")
                    )
                ),
                name="platforms_social_account_provider_shape",
            ),
        ]
        ordering = ["display_name"]

    def clean(self) -> None:
        super().clean()
        if not isinstance(self.provider_account_id, str):
            raise ValidationError({
                "provider_account_id": "provider_account_id must be a string."
            })
        if self.credential_id and self.credential.organization_id != self.organization_id:
            raise ValidationError({"credential": "Credential must belong to the account organization."})
        if self.credential_id and self.credential.platform_id != self.platform_id:
            raise ValidationError({"credential": "Credential must belong to the selected platform."})
        if self.provider == self.Provider.DIRECT:
            if self.provider_connection_id:
                raise ValidationError({
                    "provider_connection": "DIRECT accounts cannot have a provider connection."
                })
            if self.provider_account_id:
                raise ValidationError({
                    "provider_account_id": "DIRECT accounts cannot have a provider account id."
                })
        elif self.provider == self.Provider.BUFFER:
            if not self.provider_connection_id:
                raise ValidationError({
                    "provider_connection": "BUFFER accounts require a provider connection."
                })
            provider_account_id = self.provider_account_id.strip()
            if not provider_account_id:
                raise ValidationError({
                    "provider_account_id": "BUFFER accounts require a non-empty provider account id."
                })
            if self.credential_id:
                raise ValidationError({
                    "credential": "BUFFER accounts must not carry a direct credential."
                })
            if self.provider_connection.organization_id != self.organization_id:
                raise ValidationError({
                    "provider_connection": "Provider connection must belong to the account organization."
                })
            if self.provider_connection.provider != self.Provider.BUFFER:
                raise ValidationError({
                    "provider_connection": "Provider connection provider must match the account provider."
                })
            self.provider_account_id = provider_account_id

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
