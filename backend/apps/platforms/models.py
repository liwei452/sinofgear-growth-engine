import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import OrganizationScopedModel

from .codes import AccountCapability, validate_capability_list


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


class SocialAccount(OrganizationScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    class PublishMode(models.TextChoices):
        API_AUTO = "API_AUTO", "API automatic"
        API_CONFIRM = "API_CONFIRM", "API confirmation"
        EXPORT_PACKAGE = "EXPORT_PACKAGE", "Export package"
        MANUAL = "MANUAL", "Manual"

    platform = models.ForeignKey(Platform, on_delete=models.PROTECT, related_name="social_accounts")
    credential = models.ForeignKey(
        ConnectorCredential, on_delete=models.SET_NULL, null=True, blank=True, related_name="social_accounts"
    )
    external_id = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    publish_mode = models.CharField(max_length=32, choices=PublishMode.choices, default=PublishMode.MANUAL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    connector_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "platform", "external_id"], name="platforms_unique_social_account"
            )
        ]
        ordering = ["display_name"]

    def clean(self) -> None:
        super().clean()
        if self.credential_id and self.credential.organization_id != self.organization_id:
            raise ValidationError({"credential": "Credential must belong to the account organization."})
        if self.credential_id and self.credential.platform_id != self.platform_id:
            raise ValidationError({"credential": "Credential must belong to the selected platform."})

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
