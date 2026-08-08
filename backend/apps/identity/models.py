import uuid

from django.conf import settings
from django.db import models

from .permissions import PermissionCode


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class RoleManager(models.Manager["Role"]):
    def create_administrator(self) -> "Role":
        return self._create_builtin(Role.Code.ADMINISTRATOR)

    def create_operator(self) -> "Role":
        return self._create_builtin(Role.Code.OPERATOR)

    def create_reviewer(self) -> "Role":
        return self._create_builtin(Role.Code.REVIEWER)

    def create_read_only(self) -> "Role":
        return self._create_builtin(Role.Code.READ_ONLY)

    def _create_builtin(self, code: str) -> "Role":
        name, permissions = Role.BUILTIN_ROLES[code]
        role, _ = self.update_or_create(
            code=code,
            defaults={"name": name, "permissions": list(permissions)},
        )
        return role


class Role(models.Model):
    class Code(models.TextChoices):
        ADMINISTRATOR = "ADMINISTRATOR", "Administrator"
        OPERATOR = "OPERATOR", "Operator"
        REVIEWER = "REVIEWER", "Reviewer"
        READ_ONLY = "READ_ONLY", "Read only"

    BUILTIN_ROLES = {
        Code.ADMINISTRATOR: (
            "Administrator",
            tuple(permission.value for permission in PermissionCode),
        ),
        Code.OPERATOR: (
            "Operator",
            (
                PermissionCode.MEMBERSHIPS_READ,
                PermissionCode.MEMBERSHIPS_MANAGE,
                PermissionCode.KNOWLEDGE_READ,
                PermissionCode.KNOWLEDGE_CREATE,
            ),
        ),
        Code.REVIEWER: (
            "Reviewer",
            (PermissionCode.MEMBERSHIPS_READ, PermissionCode.KNOWLEDGE_READ, PermissionCode.KNOWLEDGE_REVIEW_ORGANIZATION),
        ),
        Code.READ_ONLY: ("Read only", (PermissionCode.MEMBERSHIPS_READ, PermissionCode.KNOWLEDGE_READ)),
    }

    code = models.CharField(max_length=32, choices=Code.choices, unique=True)
    name = models.CharField(max_length=255)
    permissions = models.JSONField(default=list)

    objects = RoleManager()

    def __str__(self) -> str:
        return self.name


class Membership(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "organization"], name="identity_unique_membership"),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="ACTIVE"),
                name="identity_one_active_membership_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} in {self.organization}"
