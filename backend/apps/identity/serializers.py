from django.contrib.auth import authenticate
from rest_framework import serializers

from .models import Membership


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(trim_whitespace=False, write_only=True)

    def validate(self, attrs: dict[str, str]) -> dict[str, str]:
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["username"],
            password=attrs["password"],
        )
        if user is None:
            raise serializers.ValidationError({"detail": "Invalid credentials."})
        attrs["user"] = user
        return attrs


class MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = ["id", "user", "organization", "role", "status"]
        read_only_fields = ["id", "user", "organization", "role"]


class MembershipStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = ["status"]


class CurrentUserSerializer(serializers.Serializer):
    def to_representation(self, membership: Membership) -> dict[str, object]:
        return {
            "user": {"id": membership.user_id, "username": membership.user.get_username()},
            "organization": {
                "id": str(membership.organization_id),
                "name": membership.organization.name,
                "slug": membership.organization.slug,
            },
            "membership": {
                "id": str(membership.id),
                "role": membership.role.code,
                "status": membership.status,
                "permissions": sorted(str(permission) for permission in membership.role.permissions),
            },
        }
