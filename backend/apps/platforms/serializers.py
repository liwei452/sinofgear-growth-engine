from rest_framework import serializers

from .models import ConnectorCredential, Platform, SocialAccount


class PlatformSerializer(serializers.ModelSerializer):
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = Platform
        fields = ["code", "name", "capabilities"]

    def get_capabilities(self, platform: Platform) -> list[str]:
        return [capability.code for capability in platform.capability_definitions.all()]


class PlatformListSerializer(serializers.Serializer):
    results = PlatformSerializer(many=True)


class SocialAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialAccount
        fields = [
            "id",
            "organization",
            "platform",
            "credential",
            "external_id",
            "display_name",
            "publish_mode",
        ]
        read_only_fields = ["id", "organization"]

    def validate_credential(self, credential: ConnectorCredential | None) -> ConnectorCredential | None:
        if credential is not None and credential.organization_id != self.context["organization"].id:
            raise serializers.ValidationError("Credential must belong to your organization.")
        return credential

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        credential = attrs.get("credential")
        platform = attrs.get("platform")
        if credential is not None and platform is not None and credential.platform_id != platform.id:
            raise serializers.ValidationError({"credential": "Credential must belong to the selected platform."})
        return attrs

    def create(self, validated_data: dict[str, object]) -> SocialAccount:
        return SocialAccount.objects.create(organization=self.context["organization"], **validated_data)


class SocialAccountListSerializer(serializers.Serializer):
    results = SocialAccountSerializer(many=True)
