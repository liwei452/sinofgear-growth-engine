import json

from django.db import transaction
from jsonschema import Draft202012Validator

from apps.common.security import scrub_secrets

from .models import PromptVersion, ai_audit_writes


class PromptVersionService:
    @staticmethod
    @transaction.atomic
    def create(
        *, purpose, code, provider, model, template, output_schema,
        status=PromptVersion.Status.DRAFT, version=None, created_by=None,
    ) -> PromptVersion:
        Draft202012Validator.check_schema(output_schema)
        if version is None:
            latest = (
                PromptVersion.objects.select_for_update()
                .filter(purpose=purpose)
                .order_by("-version")
                .first()
            )
            version = 1 if latest is None else latest.version + 1
        with ai_audit_writes():
            return PromptVersion.objects.create(
                purpose=purpose,
                code=code,
                provider=provider,
                model=model,
                template=template,
                output_schema=json.loads(json.dumps(output_schema)),
                version=version,
                status=status,
                created_by=created_by,
            )


__all__ = ["PromptVersionService", "scrub_secrets"]
