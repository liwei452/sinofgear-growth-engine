from uuid import uuid4

import pytest

from apps.ai.models import PromptVersion
from apps.ai.services import PromptVersionService


@pytest.mark.django_db
def test_catalog_selects_latest_published_prompt_by_purpose_and_code():
    from apps.ai.prompt_catalog import resolve_published_prompt

    purpose = f"CATALOG_{uuid4().hex}"
    code = "stable-contract-v1"
    older = PromptVersionService.create(
        purpose=purpose,
        code=code,
        provider="legacy-provider",
        model="legacy-model",
        template="older",
        output_schema={"type": "object"},
        version=1,
        status=PromptVersion.Status.PUBLISHED,
    )
    latest = PromptVersionService.create(
        purpose=purpose,
        code=code,
        provider="system",
        model="provider-agnostic",
        template="latest",
        output_schema={"type": "object"},
        version=2,
        status=PromptVersion.Status.PUBLISHED,
    )
    PromptVersionService.create(
        purpose=purpose,
        code="other-contract",
        provider="system",
        model="provider-agnostic",
        template="wrong code",
        output_schema={"type": "object"},
        version=3,
        status=PromptVersion.Status.PUBLISHED,
    )

    resolved = resolve_published_prompt(purpose=purpose, code=code)

    assert resolved.id == latest.id
    assert resolved.id != older.id


@pytest.mark.django_db
def test_catalog_missing_entry_fails_closed_without_creating_prompt():
    from apps.ai.prompt_catalog import (
        PromptCatalogEntryMissing,
        resolve_published_prompt,
    )

    before = PromptVersion.objects.count()

    with pytest.raises(PromptCatalogEntryMissing) as caught:
        resolve_published_prompt(
            purpose=f"MISSING_{uuid4().hex}",
            code="missing-contract",
        )

    assert caught.value.code == "PROMPT_CATALOG_ENTRY_MISSING"
    assert PromptVersion.objects.count() == before
