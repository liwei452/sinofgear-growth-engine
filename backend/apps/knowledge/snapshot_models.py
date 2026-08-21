import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_snapshot_bulk_create_allowed: ContextVar[bool] = ContextVar(
    "knowledge_snapshot_bulk_create_allowed",
    default=False,
)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@contextmanager
def snapshot_service_bulk_create():
    token = _snapshot_bulk_create_allowed.set(True)
    try:
        yield
    finally:
        _snapshot_bulk_create_allowed.reset(token)


class KnowledgeContextSnapshotQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Knowledge context snapshots are append-only.")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Knowledge context snapshots are append-only.")

    def delete(self):
        raise ValidationError("Knowledge context snapshots are append-only.")

    def bulk_create(self, objs, **kwargs):
        if not _snapshot_bulk_create_allowed.get():
            raise ValidationError(
                "Knowledge context snapshot bulk creation is restricted to the snapshot service."
            )
        objects = list(objs)
        for instance in objects:
            instance.full_clean()
        return super().bulk_create(objects, **kwargs)


class KnowledgeContextSnapshotManager(
    models.Manager.from_queryset(KnowledgeContextSnapshotQuerySet)
):
    pass


class KnowledgeContextSnapshot(models.Model):
    class Scope(models.TextChoices):
        MISSION = "MISSION", "Mission"

    SCHEMA_VERSION = "knowledge-context-v1"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="knowledge_context_snapshots",
    )
    mission = models.ForeignKey(
        "growth.GrowthMission",
        on_delete=models.PROTECT,
        related_name="knowledge_context_snapshots",
    )
    mission_plan = models.ForeignKey(
        "growth.MissionPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="knowledge_context_snapshots",
    )
    scope = models.CharField(
        max_length=16,
        choices=Scope.choices,
        default=Scope.MISSION,
    )
    schema_version = models.CharField(max_length=64, default=SCHEMA_VERSION)
    builder_version = models.CharField(max_length=64)
    company_profile = models.ForeignKey(
        "knowledge.CompanyKnowledgeProfile",
        on_delete=models.PROTECT,
        related_name="knowledge_context_snapshots",
    )
    primary_product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="knowledge_context_snapshots",
    )
    source_fingerprint = models.CharField(max_length=64)
    payload_hash = models.CharField(max_length=64)
    payload = models.JSONField()
    payload_size_bytes = models.PositiveIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_knowledge_context_snapshots",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = KnowledgeContextSnapshotManager()

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["organization_id", "scope", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "scope", "source_fingerprint"],
                name="knowledge_unique_context_source_fingerprint",
            ),
            models.CheckConstraint(
                condition=models.Q(scope="MISSION"),
                name="knowledge_context_scope_mission",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version="knowledge-context-v1"),
                name="knowledge_context_schema_v1",
            ),
            models.CheckConstraint(
                condition=models.Q(source_fingerprint__regex=r"^[0-9a-f]{64}$"),
                name="knowledge_context_source_hash_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(payload_hash__regex=r"^[0-9a-f]{64}$"),
                name="knowledge_context_payload_hash_valid",
            ),
        ]

    @property
    def canonical_payload(self) -> str:
        return canonical_json(self.payload)

    def clean(self) -> None:
        super().clean()
        errors = {}
        if self.scope != self.Scope.MISSION:
            errors["scope"] = "Mission knowledge snapshots must use MISSION scope."
        if self.schema_version != self.SCHEMA_VERSION:
            errors["schema_version"] = "Unsupported knowledge context schema version."
        for field in ("source_fingerprint", "payload_hash"):
            if not SHA256_PATTERN.fullmatch(getattr(self, field, "") or ""):
                errors[field] = "Value must be a lowercase SHA-256 hash."
        if self.mission_id and self.mission.organization_id != self.organization_id:
            errors["mission"] = "Mission must belong to the snapshot organization."
        if self.mission_plan_id:
            if self.mission_plan.organization_id != self.organization_id:
                errors["mission_plan"] = "Mission plan must belong to the snapshot organization."
            elif self.mission_plan.mission_id != self.mission_id:
                errors["mission_plan"] = "Mission plan must belong to the snapshot mission."
        if self.company_profile_id and self.company_profile.organization_id != self.organization_id:
            errors["company_profile"] = "Company profile must belong to the snapshot organization."
        if self.primary_product_id and self.primary_product.organization_id != self.organization_id:
            errors["primary_product"] = "Product must belong to the snapshot organization."
        if self.mission_id and self.primary_product_id:
            if self.mission.primary_product_id != self.primary_product_id:
                errors["primary_product"] = "Snapshot product must be the mission primary product."
        canonical_payload = self.canonical_payload
        if self.payload_hash and sha256_text(canonical_payload) != self.payload_hash:
            errors["payload_hash"] = "Payload hash does not match the canonical payload."
        if len(canonical_payload.encode("utf-8")) != self.payload_size_bytes:
            errors["payload_size_bytes"] = "Payload size does not match canonical UTF-8 bytes."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Knowledge context snapshots are append-only.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Knowledge context snapshots are append-only.")
