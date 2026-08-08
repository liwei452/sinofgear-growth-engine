from rest_framework import serializers

from .models import ConnectorCredential, Platform, SocialAccount


class PlatformSerializer(serializers.ModelSerializer):
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = Platform
        fields = ["code", "name", "capabilities"]

    def get_capabilities(self, platform: Platform) -> list[str]:
        return list(platform.capability_definitions.values_list("code", flat=True))


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

    def create(self, validated_data: dict[str, object]) -> SocialAccount:
        return SocialAccount.objects.create(organization=self.context["organization"], **validated_data)

