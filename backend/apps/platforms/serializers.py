from rest_framework import serializers
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError as DjangoValidationError

from .capabilities import resolve_account_capabilities
from .codes import AccountCapability
from .models import ConnectorCredential, Platform, SocialAccount
from .oauth import validate_return_path


class StrictMixin:
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: ["Unknown field."] for name in sorted(unknown)}
            )
        return super().to_internal_value(data)


class PlatformSerializer(serializers.ModelSerializer):
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = Platform
        fields = ["id", "code", "name", "capabilities"]

    def get_capabilities(self, platform: Platform) -> list[str]:
        return [capability.code for capability in platform.capability_definitions.all()]


class PlatformListSerializer(serializers.Serializer):
    results = PlatformSerializer(many=True)


class SocialAccountReadSerializer(serializers.ModelSerializer):
    platform_id = serializers.UUIDField(read_only=True)
    effective_capabilities = serializers.SerializerMethodField()
    credential_configured = serializers.SerializerMethodField()

    class Meta:
        model = SocialAccount
        fields = [
            "id", "platform_id", "display_name", "publish_mode", "status",
            "effective_capabilities", "credential_configured", "connection_state",
            "last_probe_at", "last_refresh_at", "reauthorization_required_at",
            "disconnected_at", "lifecycle_error_code",
        ]
        read_only_fields = fields

    def get_effective_capabilities(self, account: SocialAccount) -> list[str]:
        return sorted(capability.value for capability in resolve_account_capabilities(account.id))

    def get_credential_configured(self, account: SocialAccount) -> bool:
        return account.credential_id is not None


class SocialAccountCreateSerializer(StrictMixin, serializers.ModelSerializer):
    class Meta:
        model = SocialAccount
        fields = [
            "platform", "credential", "external_id", "display_name",
            "publish_mode", "status",
        ]
        extra_kwargs = {"credential": {"required": False, "allow_null": True}}

    def validate_credential(self, credential: ConnectorCredential | None):
        if credential is not None and credential.organization_id != self.context["organization"].id:
            raise serializers.ValidationError("Credential must belong to your organization.")
        return credential

    def validate(self, attrs):
        platform = attrs["platform"]
        credential = attrs.get("credential")
        if credential is not None and credential.platform_id != platform.id:
            raise serializers.ValidationError({
                "credential": "Credential must belong to the selected platform."
            })
        if attrs.get("publish_mode", SocialAccount.PublishMode.MANUAL) == SocialAccount.PublishMode.API_AUTO:
            platform_scopes = set(platform.capability_definitions.values_list("code", flat=True))
            credential_scopes = set(credential.granted_scopes) if credential else set()
            if AccountCapability.PUBLISH not in platform_scopes or AccountCapability.PUBLISH not in credential_scopes:
                raise serializers.ValidationError({
                    "publish_mode": "API automatic publishing requires a configured PUBLISH connection."
                })
        return attrs

    def create(self, validated_data):
        return SocialAccount.objects.create(
            organization=self.context["organization"], **validated_data
        )


class SocialAccountUpdateSerializer(StrictMixin, serializers.ModelSerializer):
    class Meta:
        model = SocialAccount
        fields = ["credential", "display_name", "publish_mode", "status"]
        extra_kwargs = {
            "credential": {"required": False, "allow_null": True},
            "display_name": {"required": False},
            "publish_mode": {"required": False},
            "status": {"required": False},
        }

    def validate_credential(self, credential: ConnectorCredential | None):
        if credential is not None and credential.organization_id != self.context["organization"].id:
            raise serializers.ValidationError("Credential must belong to your organization.")
        if credential is not None and credential.platform_id != self.instance.platform_id:
            raise serializers.ValidationError("Credential must belong to the account platform.")
        return credential

    def validate(self, attrs):
        credential = attrs.get("credential", self.instance.credential)
        mode = attrs.get("publish_mode", self.instance.publish_mode)
        if mode == SocialAccount.PublishMode.API_AUTO:
            platform_scopes = set(
                self.instance.platform.capability_definitions.values_list("code", flat=True)
            )
            credential_scopes = set(credential.granted_scopes) if credential else set()
            if AccountCapability.PUBLISH not in platform_scopes or AccountCapability.PUBLISH not in credential_scopes:
                raise serializers.ValidationError({
                    "publish_mode": "API automatic publishing requires a configured PUBLISH connection."
                })
        return attrs


class SocialAccountListSerializer(serializers.Serializer):
    results = SocialAccountReadSerializer(many=True)


class SocialAccountConnectionSerializer(StrictMixin, serializers.Serializer):
    platform = serializers.PrimaryKeyRelatedField(queryset=Platform.objects.all())
    external_id = serializers.CharField(max_length=255)
    display_name = serializers.CharField(max_length=255)
    publish_mode = serializers.ChoiceField(choices=[
        SocialAccount.PublishMode.MANUAL,
        SocialAccount.PublishMode.EXPORT_PACKAGE,
        SocialAccount.PublishMode.API_AUTO,
    ])
    status = serializers.ChoiceField(choices=SocialAccount.Status.choices, default=SocialAccount.Status.ACTIVE)
    secret_reference = serializers.CharField(max_length=512, write_only=True, required=False, trim_whitespace=True)

    def validate(self, attrs):
        automatic = attrs["publish_mode"] == SocialAccount.PublishMode.API_AUTO
        if automatic and not attrs.get("secret_reference"):
            raise serializers.ValidationError({"secret_reference": "A credential reference is required."})
        if not automatic and "secret_reference" in attrs:
            raise serializers.ValidationError({"secret_reference": "Credentials are only accepted for API automatic publishing."})
        if automatic and not attrs["platform"].capability_definitions.filter(code=AccountCapability.PUBLISH).exists():
            raise serializers.ValidationError({"publish_mode": "The selected platform does not support API publishing."})
        return attrs

    def create(self, validated_data):
        secret = validated_data.pop("secret_reference", None)
        organization = self.context["organization"]
        try:
            with transaction.atomic():
                credential = None
                if secret is not None:
                    credential = ConnectorCredential(
                        organization=organization, platform=validated_data["platform"],
                        secret_reference=secret, granted_scopes=[AccountCapability.PUBLISH],
                    )
                    credential.full_clean(exclude=["granted_scopes"])
                    credential.save()
                return SocialAccount.objects.create(
                    organization=organization, credential=credential, **validated_data
                )
        except (IntegrityError, DjangoValidationError) as error:
            raise serializers.ValidationError({"external_id": "This platform account is already connected."}) from error


class ConnectorCredentialReadSerializer(serializers.ModelSerializer):
    platform_id = serializers.UUIDField(read_only=True)
    configured = serializers.SerializerMethodField()

    class Meta:
        model = ConnectorCredential
        fields = ["id", "platform_id", "granted_scopes", "expires_at", "configured"]
        read_only_fields = fields

    def get_configured(self, credential: ConnectorCredential) -> bool:
        return bool(credential.secret_reference)


class ConnectorCredentialCreateSerializer(StrictMixin, serializers.ModelSerializer):
    secret_reference = serializers.CharField(max_length=512, write_only=True, trim_whitespace=True)

    class Meta:
        model = ConnectorCredential
        fields = ["platform", "secret_reference", "granted_scopes", "expires_at"]

    def validate(self, attrs):
        allowed = set(attrs["platform"].capability_definitions.values_list("code", flat=True))
        invalid = sorted(set(attrs.get("granted_scopes", [])) - allowed)
        if invalid:
            raise serializers.ValidationError({
                "granted_scopes": "Scopes must be defined capabilities of the selected platform."
            })
        return attrs

    def create(self, validated_data):
        credential = ConnectorCredential(
            organization=self.context["organization"], **validated_data
        )
        credential.full_clean(exclude=["granted_scopes"])
        credential.save()
        return credential


class ConnectorCredentialUpdateSerializer(StrictMixin, serializers.ModelSerializer):
    secret_reference = serializers.CharField(
        max_length=512, write_only=True, required=False, trim_whitespace=True
    )

    class Meta:
        model = ConnectorCredential
        fields = ["secret_reference", "granted_scopes", "expires_at"]
        extra_kwargs = {
            "granted_scopes": {"required": False},
            "expires_at": {"required": False},
        }

    def validate_granted_scopes(self, scopes):
        allowed = set(self.instance.platform.capability_definitions.values_list("code", flat=True))
        if set(scopes) - allowed:
            raise serializers.ValidationError(
                "Scopes must be defined capabilities of the credential platform."
            )
        return scopes

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.full_clean(exclude=["granted_scopes"])
        instance.save(update_fields=[*validated_data, "updated_at"])
        return instance


class ConnectorCredentialListSerializer(serializers.Serializer):
    results = ConnectorCredentialReadSerializer(many=True)


class PlatformConnectionSerializer(serializers.Serializer):
    platform = serializers.CharField()
    platform_name = serializers.CharField()
    status = serializers.ChoiceField(choices=[
        "NOT_CONNECTED", "CONNECTED", "REAUTHORIZATION_REQUIRED", "CONFIGURATION_REQUIRED",
    ])
    connection_label = serializers.CharField()
    recovery_action = serializers.CharField(allow_blank=True)
    mode = serializers.CharField(allow_blank=True)


class PlatformConnectionListSerializer(serializers.Serializer):
    results = PlatformConnectionSerializer(many=True)


class PlatformAuthorizationRequestSerializer(StrictMixin, serializers.Serializer):
    return_path = serializers.CharField(default="/promotion", max_length=512)

    def validate_return_path(self, value):
        try:
            return validate_return_path(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error


class PlatformAuthorizationResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["AUTHORIZATION_REQUIRED"])
    authorization_url = serializers.URLField()
    expires_at = serializers.DateTimeField()


class PlatformAuthorizationCallbackSerializer(StrictMixin, serializers.Serializer):
    code = serializers.CharField(max_length=2048, required=False, trim_whitespace=False)
    state = serializers.CharField(max_length=512, trim_whitespace=False)
    error = serializers.CharField(max_length=255, required=False)

    def validate(self, attrs):
        if not attrs.get("code") and not attrs.get("error"):
            raise serializers.ValidationError({"code": "Authorization code is required."})
        return attrs


class ConnectionCandidateSerializer(serializers.Serializer):
    candidate_id = serializers.UUIDField()
    display_name = serializers.CharField()
    channel = serializers.ChoiceField(
        choices=["FACEBOOK", "INSTAGRAM", "LINKEDIN", "TIKTOK", "YOUTUBE"]
    )
    capability_label = serializers.CharField()
    publication_mode = serializers.ChoiceField(choices=["PUBLIC", "PRIVATE_ONLY"])


class AccountConnectionSessionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    platform = serializers.CharField()
    platform_name = serializers.CharField()
    expires_at = serializers.DateTimeField()
    candidates = ConnectionCandidateSerializer(many=True)


class AccountConnectionConfirmationSerializer(StrictMixin, serializers.Serializer):
    candidate_id = serializers.UUIDField()


class AccountConnectionConfirmationResponseSerializer(serializers.Serializer):
    platform = serializers.CharField()
    status = serializers.CharField()
    connection_label = serializers.CharField()
    recovery_action = serializers.CharField(allow_blank=True)
    mode = serializers.CharField()


class SocialAccountDisconnectSerializer(StrictMixin, serializers.Serializer):
    confirm = serializers.BooleanField()


class SocialAccountLifecycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialAccount
        fields = [
            "id", "status", "connection_state", "last_probe_at", "last_refresh_at",
            "reauthorization_required_at", "disconnected_at", "lifecycle_error_code",
        ]
        read_only_fields = fields
