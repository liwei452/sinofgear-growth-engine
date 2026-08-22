from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps

from apps.ai.models import PromptVersion, ai_audit_writes


migration = import_module("apps.ai.migrations.0007_asset_understanding_prompt_catalog")


class _NonOwnerCursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _sql):
        return None

    def fetchone(self):
        return (False,)


class _NonOwnerSchemaEditor:
    class _Connection:
        vendor = "postgresql"

        @staticmethod
        def cursor():
            return _NonOwnerCursor()

    connection = _Connection()


@pytest.mark.django_db
def test_asset_prompt_seed_has_the_frozen_system_contract():
    prompt = PromptVersion.objects.get(
        purpose=migration.PURPOSE,
        code=migration.PROMPT_CODE,
    )
    assert prompt.template == migration.TEMPLATE
    assert prompt.output_schema == migration.OUTPUT_SCHEMA
    assert prompt.status == PromptVersion.Status.PUBLISHED
    assert (prompt.provider, prompt.model) == ("system", "provider-agnostic")


@pytest.mark.django_db
def test_asset_prompt_seed_reuses_a_compatible_entry(monkeypatch):
    purpose = f"MIGRATION_{uuid4().hex}"
    monkeypatch.setattr(migration, "PURPOSE", purpose)
    with ai_audit_writes():
        migration.seed_asset_understanding_prompt(apps, None)
        migration.seed_asset_understanding_prompt(apps, None)
    assert PromptVersion.objects.filter(purpose=purpose).count() == 1


@pytest.mark.django_db
def test_asset_prompt_seed_rejects_a_conflicting_entry(monkeypatch):
    purpose = f"MIGRATION_{uuid4().hex}"
    monkeypatch.setattr(migration, "PURPOSE", purpose)
    with ai_audit_writes():
        PromptVersion.objects.create(
            purpose=purpose,
            code=migration.PROMPT_CODE,
            provider="system",
            model="provider-agnostic",
            template="conflict",
            output_schema=migration.OUTPUT_SCHEMA,
            version=1,
            status=PromptVersion.Status.PUBLISHED,
        )
    with pytest.raises(RuntimeError, match="conflicts with the system contract"):
        migration.seed_asset_understanding_prompt(apps, None)
    assert PromptVersion.objects.get(purpose=purpose).template == "conflict"


@pytest.mark.django_db
def test_asset_prompt_seed_fails_before_writing_when_migration_role_is_not_owner(
    monkeypatch,
):
    purpose = f"MIGRATION_{uuid4().hex}"
    monkeypatch.setattr(migration, "PURPOSE", purpose)

    with pytest.raises(RuntimeError, match="migration owner"):
        migration.seed_asset_understanding_prompt(apps, _NonOwnerSchemaEditor())

    assert PromptVersion.objects.filter(purpose=purpose).count() == 0
