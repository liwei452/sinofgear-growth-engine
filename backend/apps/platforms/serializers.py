from rest_framework import serializers

from .capabilities import resolve_account_capabilities
from .codes import AccountCapability
from .models import ConnectorCredential, Platform, SocialAccount


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
            "effective_capabilities", "credential_configured",
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
