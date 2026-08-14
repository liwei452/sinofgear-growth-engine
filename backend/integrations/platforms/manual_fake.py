from dataclasses import dataclass


class ExternalPublishDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class ManualPackageReceipt:
    channel: str
    mode: str
    data_label: str
    payload: dict


@dataclass(frozen=True)
class SimulatedPublishReceipt:
    succeeded: bool
    data_label: str = "Demo / Fake"
    external_id: str = ""
    external_url: str = ""
    error_code: str = ""
    error_message: str = ""


def simulate_publish(
    *, channel: str, payload: dict, item_id: str, attempt_number: int,
    outcome: str, is_demo: bool,
) -> SimulatedPublishReceipt:
    """Return a local receipt without making any network request."""
    if not is_demo:
        raise ExternalPublishDisabled("Demo packages are required for simulated publishing.")
    if not isinstance(payload, dict):
        raise ValueError("Simulated publishing payload must be an object.")
    if outcome == "fail_once" and attempt_number == 1:
        return SimulatedPublishReceipt(
            succeeded=False,
            error_code="PROVIDER_ERROR",
            error_message="Demo provider rejected the first publish attempt.",
        )
    if outcome in {"provider_error", "token_expired", "rate_limit"}:
        code = {
            "provider_error": "PROVIDER_ERROR",
            "token_expired": "TOKEN_EXPIRED",
            "rate_limit": "RATE_LIMITED",
        }[outcome]
        return SimulatedPublishReceipt(
            succeeded=False,
            error_code=code,
            error_message="Demo connector could not publish this channel.",
        )
    normalized_channel = channel.strip().lower()
    normalized_item_id = str(item_id).strip()
    return SimulatedPublishReceipt(
        succeeded=True,
        external_id=f"demo-{normalized_channel}-{normalized_item_id}",
        external_url=(
            f"https://example.invalid/demo-post/{normalized_channel}/{normalized_item_id}"
        ),
    )


class ManualPackageFakeConnector:
    """Local-only connector boundary; it never performs an external request."""

    def build_package(self, *, channel: str, payload: dict) -> ManualPackageReceipt:
        if channel == "TIKTOK":
            duration = payload.get("duration_seconds")
            if not isinstance(duration, int) or not 15 <= duration <= 60:
                raise ValueError("TikTok duration must be between 15 and 60 seconds.")
            if payload.get("aspect_ratio") != "9:16":
                raise ValueError("TikTok aspect ratio must be 9:16.")
        return ManualPackageReceipt(
            channel=channel,
            mode="MANUAL_PACKAGE",
            data_label="Demo / Fake",
            payload=dict(payload),
        )

    def publish(self, *_args, **_kwargs):
        raise ExternalPublishDisabled("Real publishing requires approved OAuth, scopes, and human confirmation.")
