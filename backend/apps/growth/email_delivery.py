"""Pluggable outbound email delivery provider."""

from __future__ import annotations

import uuid
from typing import Protocol

from django.conf import settings
from django.core.mail import send_mail
from django.utils.module_loading import import_string


class EmailDeliveryProvider(Protocol):
    def send(self, *, email: str, subject: str, body: str) -> dict: ...


class MockEmailDeliveryProvider:
    def send(self, *, email: str, subject: str, body: str) -> dict:
        return {
            "provider": "mock",
            "message_id": f"mock-{uuid.uuid4().hex}",
            "status": "SENT",
        }


class SMTPEmailDeliveryProvider:
    def send(self, *, email: str, subject: str, body: str) -> dict:
        from_email = (
            getattr(settings, "DEFAULT_FROM_EMAIL", "")
            or getattr(settings, "EMAIL_HOST_USER", "")
            or None
        )
        sent = send_mail(
            subject=subject or "SinofGear",
            message=body,
            from_email=from_email,
            recipient_list=[email],
            fail_silently=False,
        )
        return {
            "provider": "smtp",
            "message_id": f"smtp-{uuid.uuid4().hex}",
            "status": "SENT" if sent else "FAILED",
        }


def get_delivery_provider() -> EmailDeliveryProvider:
    factory_path = getattr(settings, "EMAIL_DELIVERY_PROVIDER_FACTORY", "")
    if factory_path:
        return import_string(factory_path)()
    return MockEmailDeliveryProvider()
