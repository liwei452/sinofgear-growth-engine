from enum import StrEnum

from django.core.exceptions import ValidationError


class AccountCapability(StrEnum):
    PUBLISH = "PUBLISH"
    METRICS_READ = "METRICS_READ"
    COMMENT_READ = "COMMENT_READ"
    PUBLIC_SEARCH = "PUBLIC_SEARCH"
    MEDIA_UPLOAD = "MEDIA_UPLOAD"
    WEBHOOK = "WEBHOOK"


def validate_capability_list(value: object) -> None:
    if not isinstance(value, list):
        raise ValidationError("Capability scopes must be a list.")
    invalid_codes = [code for code in value if code not in AccountCapability._value2member_map_]
    if invalid_codes:
        raise ValidationError(f"Unknown capability codes: {invalid_codes}")
