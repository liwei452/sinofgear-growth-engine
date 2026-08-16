import re
import socket
from typing import Protocol

from django.conf import settings
from django.utils.module_loading import import_string


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class EmailVerificationProvider(Protocol):
    def verify(self, email: str) -> dict: ...


class BasicEmailVerificationProvider:
    def verify(self, email: str) -> dict:
        normalized = email.strip().lower()
        if not EMAIL_RE.match(normalized):
            return {
                "email": normalized,
                "status": "INVALID_SYNTAX",
                "domain_resolves": False,
            }
        domain = normalized.rsplit("@", 1)[1]
        try:
            socket.gethostbyname(domain)
            domain_resolves = True
        except (socket.gaierror, OSError):
            domain_resolves = False
        return {
            "email": normalized,
            "status": "DOMAIN_RESOLVES" if domain_resolves else "DOMAIN_UNRESOLVABLE",
            "domain_resolves": domain_resolves,
        }


def get_verification_provider() -> EmailVerificationProvider:
    factory_path = getattr(settings, "EMAIL_VERIFICATION_PROVIDER_FACTORY", "")
    if factory_path:
        return import_string(factory_path)()
    return BasicEmailVerificationProvider()


def verify_email(email: str) -> dict:
    return get_verification_provider().verify(email)
