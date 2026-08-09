from contextlib import contextmanager
from contextvars import ContextVar
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.deletion import ProtectedError

from apps.common.models import OrganizationScopedModel


_tracking_write = ContextVar("tracking_service_write", default=False)
_click_write = ContextVar("click_event_write", default=False)
_click_purge = ContextVar("click_event_purge", default=False)


@contextmanager
def tracking_writes():
    token = _tracking_write.set(True)
    try:
        yield
    finally:
        _tracking_write.reset(token)


@contextmanager
def click_writes():
    token = _click_write.set(True)
    try:
        yield
    finally:
        _click_write.reset(token)


@contextmanager
def click_purges():
    token = _click_purge.set(True)
    try:
        yield
    finally:
        _click_purge.reset(token)


class ProtectedTrackingQuerySet(models.QuerySet):
    @staticmethod
    def _guard():
        if not _tracking_write.get():
            raise ValidationError("Tracking identity may change only through services.")

    def update(self, **kwargs):
        self._guard()
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        self._guard()
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        self._guard()
        return super().bulk_update(objs, fields, **kwargs)

    def delete(self):
        protected = list(self)
        if protected:
            raise ProtectedError("Tracking history cannot be deleted.", protected)
        return 0, {}


class ProtectedTrackingModel(OrganizationScopedModel):
    objects = models.Manager.from_queryset(ProtectedTrackingQuerySet)()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(self, *args, **kwargs):
        if not _tracking_write.get():
            raise ValidationError("Tracking identity may change only through services.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ProtectedError("Tracking history cannot be deleted.", [self])


class TrackingLink(ProtectedTrackingModel):
    destination = models.URLField(max_length=2048)
    full_url = models.URLField(max_length=2048)
    utm_source = models.CharField(max_length=128)
    utm_medium = models.CharField(max_length=128)
    utm_campaign = models.CharField(max_length=128)
    utm_content = models.CharField(max_length=128, blank=True)
    utm_term = models.CharField(max_length=128, blank=True)
    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.PROTECT, related_name="tracking_links")
    platform = models.ForeignKey("platforms.Platform", on_delete=models.PROTECT, related_name="tracking_links")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="tracking_links")
    published_post = models.ForeignKey(
        "publishing.PublishedPost", on_delete=models.PROTECT, related_name="tracking_links"
    )
    idempotency_key = models.CharField(max_length=128)
    request_fingerprint = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="created_tracking_links",
    )

    class Meta(ProtectedTrackingModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="tracking_unique_tracking_idempotency",
            )
        ]


class ShortLink(ProtectedTrackingModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DISABLED = "DISABLED", "Disabled"

    tracking_link = models.ForeignKey(TrackingLink, on_delete=models.PROTECT, related_name="short_links")
    code = models.CharField(max_length=32, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    idempotency_key = models.CharField(max_length=128)
    request_fingerprint = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="created_short_links",
    )

    class Meta(ProtectedTrackingModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="tracking_unique_short_idempotency",
            )
        ]


class ClickEventQuerySet(models.QuerySet):
    @staticmethod
    def _write_guard():
        if not _click_write.get():
            raise ValidationError("Click events may be appended only through the recording service.")

    def update(self, **kwargs):
        raise ValidationError("Click events are append-only.")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Click events are append-only.")

    def bulk_create(self, objs, **kwargs):
        self._write_guard()
        return super().bulk_create(objs, **kwargs)

    def delete(self):
        if not _click_purge.get():
            raise ValidationError("Click events may be deleted only through the retention service.")
        return super().delete()


class ClickEvent(models.Model):
    class Device(models.TextChoices):
        DESKTOP = "desktop", "Desktop"
        MOBILE = "mobile", "Mobile"
        TABLET = "tablet", "Tablet"
        BOT = "bot", "Bot"
        OTHER = "other", "Other"

    objects = models.Manager.from_queryset(ClickEventQuerySet)()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("identity.Organization", on_delete=models.PROTECT)
    tracking_link = models.ForeignKey(TrackingLink, on_delete=models.PROTECT, related_name="click_events")
    short_link = models.ForeignKey(ShortLink, on_delete=models.PROTECT, related_name="click_events")
    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.PROTECT, related_name="click_events")
    platform = models.ForeignKey("platforms.Platform", on_delete=models.PROTECT, related_name="click_events")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="click_events")
    occurred_at = models.DateTimeField()
    occurred_date = models.DateField()
    country = models.CharField(max_length=2, blank=True)
    device = models.CharField(max_length=16, choices=Device.choices)
    referrer_host = models.CharField(max_length=253, blank=True)
    network_hash = models.CharField(max_length=64)
    hash_version = models.CharField(max_length=32)

    class Meta:
        ordering = ["occurred_at", "id"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(fields=["organization", "occurred_date"], name="tracking_click_org_date"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding or not _click_write.get():
            raise ValidationError("Click events are append-only and service-created.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not _click_purge.get():
            raise ValidationError("Click events may be deleted only through the retention service.")
        return super().delete(*args, **kwargs)
