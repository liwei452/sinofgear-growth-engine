from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from typing import Iterator

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.deletion import ProtectedError
from django.db.models.expressions import BaseExpression


class _WriteMode(StrEnum):
    NORMAL = "NORMAL"
    AUDITED_REVIEW = "AUDITED_REVIEW"
    SYSTEM_SEED = "SYSTEM_SEED"
    TEST_FIXTURE = "TEST_FIXTURE"
    VALIDATED_BULK = "VALIDATED_BULK"


_write_mode: ContextVar[_WriteMode] = ContextVar("knowledge_write_mode", default=_WriteMode.NORMAL)


@contextmanager
def _write_mode_context(mode: _WriteMode) -> Iterator[None]:
    token = _write_mode.set(mode)
    try:
        yield
    finally:
        _write_mode.reset(token)


def _audited_review_writes() -> Iterator[None]:
    return _write_mode_context(_WriteMode.AUDITED_REVIEW)


def _system_seed_writes() -> Iterator[None]:
    return _write_mode_context(_WriteMode.SYSTEM_SEED)


@contextmanager
def _test_fixture_writes() -> Iterator[None]:
    if not getattr(settings, "KNOWLEDGE_TEST_FIXTURE_WRITES", False):
        raise RuntimeError("Test-fixture knowledge writes are disabled outside test settings.")
    with _write_mode_context(_WriteMode.TEST_FIXTURE):
        yield


LIFECYCLE_FIELDS = frozenset({"status", "version", "suggested_by_ai_run_id"})


class KnowledgeQuerySet(models.QuerySet):
    @transaction.atomic
    def update(self, **kwargs):
        mode = _write_mode.get()
        if mode == _WriteMode.SYSTEM_SEED:
            if self.filter(organization_id__isnull=False).exists():
                raise ValidationError("SYSTEM seed writes cannot mutate organization knowledge.")
            return super().update(**kwargs)
        if mode in {_WriteMode.AUDITED_REVIEW, _WriteMode.TEST_FIXTURE, _WriteMode.VALIDATED_BULK}:
            return super().update(**kwargs)
        self.model._validate_queryset_update_fields(set(kwargs))
        objects = list(self)
        for instance in objects:
            for field, value in kwargs.items():
                if isinstance(value, BaseExpression):
                    raise ValidationError(f"Expression updates are not supported for guarded field '{field}'.")
                setattr(instance, field, value)
            instance._prepare_knowledge_write()
            instance._validate_knowledge_write(creating=False)
        with _write_mode_context(_WriteMode.VALIDATED_BULK):
            return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        objects = list(objs)
        mode = _write_mode.get()
        for instance in objects:
            instance._prepare_knowledge_write()
            instance._validate_knowledge_write(creating=True)
            if mode == _WriteMode.SYSTEM_SEED and instance.organization_id is not None:
                raise ValidationError("SYSTEM seed writes cannot create organization knowledge.")
        return super().bulk_create(objects, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objects = list(objs)
        mode = _write_mode.get()
        field_names = {field.name if hasattr(field, "name") else str(field) for field in fields}
        if mode == _WriteMode.NORMAL:
            self.model._validate_queryset_update_fields(field_names)
        for instance in objects:
            instance._prepare_knowledge_write()
            instance._validate_knowledge_write(creating=False)
        with _write_mode_context(_WriteMode.VALIDATED_BULK):
            return super().bulk_update(objects, fields, **kwargs)

    @transaction.atomic
    def delete(self):
        objects = list(self)
        for instance in objects:
            instance._ensure_knowledge_not_referenced()
        return super().delete()


class KnowledgeManager(models.Manager.from_queryset(KnowledgeQuerySet)):
    pass


class GuardedKnowledgeModel(models.Model):
    objects = KnowledgeManager()

    immutable_fields: frozenset[str] = frozenset()
    guarded_relation_fields: frozenset[str] = frozenset()

    class Meta:
        abstract = True

    def _prepare_knowledge_write(self) -> None:
        pass

    def _validate_domain_invariants(self) -> None:
        self.clean()

    @classmethod
    def _validate_queryset_update_fields(cls, fields: set[str]) -> None:
        normalized = {field.removesuffix("_id") for field in fields}
        if normalized & LIFECYCLE_FIELDS:
            raise ValidationError("Knowledge status, version, and AI origin may change only through the audited review service.")
        immutable = {field.removesuffix("_id") for field in cls.immutable_fields}
        if normalized & immutable:
            raise ValidationError("Knowledge evidence source snapshots are immutable.")

    def _validate_knowledge_write(self, *, creating: bool) -> None:
        mode = _write_mode.get()
        self._validate_domain_invariants()
        if mode == _WriteMode.SYSTEM_SEED:
            if self.organization_id is not None:
                raise ValidationError("SYSTEM seed writes cannot mutate organization knowledge.")
            return
        if mode in {_WriteMode.AUDITED_REVIEW, _WriteMode.TEST_FIXTURE, _WriteMode.VALIDATED_BULK}:
            return
        if creating:
            if self.suggested_by_ai_run_id and self.status != "SUGGESTED":
                raise ValidationError("AI-originated knowledge must start SUGGESTED.")
            if self.status != "SUGGESTED" or self.version != 1:
                raise ValidationError("Ordinary knowledge creation must start SUGGESTED at version 1.")
            return
        original = type(self).objects.get(pk=self.pk)
        if (
            self.status != original.status
            or self.version != original.version
            or self.suggested_by_ai_run_id != original.suggested_by_ai_run_id
        ):
            raise ValidationError("Knowledge lifecycle changes must use the audited review service.")
        if any(getattr(self, field) != getattr(original, field) for field in self.immutable_fields):
            raise ValidationError("Knowledge evidence source snapshots are immutable.")

    def save(self, *args, **kwargs) -> None:
        creating = self._state.adding
        self._prepare_knowledge_write()
        self._validate_knowledge_write(creating=creating)
        super().save(*args, **kwargs)

    def _knowledge_reference_objects(self) -> list[object]:
        return []

    def _ensure_knowledge_not_referenced(self) -> None:
        references = self._knowledge_reference_objects()
        if references:
            raise ProtectedError(
                f"{type(self).__name__} is referenced and must be deprecated rather than deleted.",
                references,
            )

    def delete(self, *args, **kwargs):
        self._ensure_knowledge_not_referenced()
        return super().delete(*args, **kwargs)


def validate_evidence_link_scope(*, owner, evidence_objects) -> None:
    evidence = list(evidence_objects)
    if owner.organization_id is None:
        if any(item.organization_id is not None for item in evidence):
            raise ValidationError("SYSTEM knowledge may link only SYSTEM evidence.")
        return
    if any(item.organization_id not in {None, owner.organization_id} for item in evidence):
        raise ValidationError("Knowledge evidence must be visible to the owner's organization.")
