from .base import PublishRequest, PublishResult


class MockPlatformConnector:
    def __init__(self, *, outcome="success"):
        self.outcome = outcome

    def publish(self, request: PublishRequest) -> PublishResult:
        if self.outcome == "fail_once" and request.attempt_number == 1:
            return PublishResult(
                succeeded=False,
                error_code="PROVIDER_ERROR",
                error_message="Provider rejected the publish request.",
            )
        if self.outcome == "rate_limit":
            return PublishResult(
                succeeded=False, error_code="RATE_LIMITED",
                error_message="Provider rate limit reached.", retry_after_seconds=60,
            )
        if self.outcome == "token_expired":
            return PublishResult(
                succeeded=False, error_code="TOKEN_EXPIRED",
                error_message="Account authorization has expired.",
            )
        if self.outcome == "provider_error":
            return PublishResult(
                succeeded=False, error_code="PROVIDER_ERROR",
                error_message="Provider rejected the publish request.",
            )
        return PublishResult(
            succeeded=True, external_id=f"mock-{request.task_id}"
        )


def mock_connector_factory(account):
    metadata = account.connector_metadata
    outcome = metadata.get("mock_outcome", "success") if isinstance(metadata, dict) else "provider_error"
    return MockPlatformConnector(outcome=outcome)
