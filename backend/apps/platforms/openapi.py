from __future__ import annotations


def enforce_buffer_rotate_required(result: dict, generator, request, public) -> dict:
    del generator, request, public
    schemas = result.get("components", {}).get("schemas", {})
    target = schemas.get("PatchedBufferProviderConnectionRotate")
    if target is not None:
        target["required"] = ["api_key"]
    return result
