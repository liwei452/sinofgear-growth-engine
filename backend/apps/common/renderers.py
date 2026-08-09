from typing import Any

from rest_framework.renderers import JSONRenderer


_RECOVERY_BY_STATUS = {
    400: "Correct the request and try again.",
    401: "Sign in and try again.",
    403: "Refresh the page or ask an administrator for access.",
    404: "Refresh the page and choose an available resource.",
    409: "Refresh the latest data and try again.",
    412: "Refresh the latest data and try again.",
    429: "Wait briefly and try again.",
}


def recoverable_error(data: Any, status_code: int) -> dict[str, Any]:
    payload = dict(data) if isinstance(data, dict) else {"detail": data}
    if status_code >= 500:
        message = "The server could not complete the request."
    elif isinstance(payload.get("message"), str):
        message = payload["message"]
    elif isinstance(payload.get("detail"), str):
        message = payload["detail"]
    elif "errors" in payload:
        message = "The request contains invalid fields."
    else:
        message = "The request could not be completed."
    code = payload.get("code")
    if not isinstance(code, str) or not code:
        code = f"http_{status_code}"
    recovery_action = payload.get("recovery_action")
    if not isinstance(recovery_action, str) or not recovery_action:
        recovery_action = _RECOVERY_BY_STATUS.get(status_code, "Try again later.")
    return {**payload, "code": code, "message": message, "recovery_action": recovery_action}


class RecoverableErrorJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        context = renderer_context or {}
        response = context.get("response")
        request = context.get("request")
        if (
            response is not None
            and response.status_code >= 400
            and getattr(request, "method", "").upper() in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            data = recoverable_error(data, response.status_code)
        return super().render(data, accepted_media_type, renderer_context)
