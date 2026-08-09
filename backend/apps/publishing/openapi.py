from .services import MAX_PUBLISH_ATTEMPTS


def enforce_publish_attempt_bound(result, generator, request, public):
    del generator, request, public

    publish_task = result.get("components", {}).get("schemas", {}).get("PublishTask", {})
    attempts = publish_task.get("properties", {}).get("attempts")
    if attempts is not None:
        attempts["maxItems"] = MAX_PUBLISH_ATTEMPTS

    return result
