from __future__ import annotations

from apps.ai.models import PromptVersion


class PromptCatalogEntryMissing(RuntimeError):
    code = "PROMPT_CATALOG_ENTRY_MISSING"

    def __init__(self, *, purpose: str, prompt_code: str) -> None:
        self.purpose = purpose
        self.prompt_code = prompt_code
        super().__init__("Required published system prompt is unavailable.")


def resolve_published_prompt(*, purpose: str, code: str) -> PromptVersion:
    prompt = (
        PromptVersion.objects.filter(
            purpose=purpose,
            code=code,
            status=PromptVersion.Status.PUBLISHED,
        )
        .order_by("-version", "-created_at", "-id")
        .first()
    )
    if prompt is None:
        raise PromptCatalogEntryMissing(purpose=purpose, prompt_code=code)
    return prompt
