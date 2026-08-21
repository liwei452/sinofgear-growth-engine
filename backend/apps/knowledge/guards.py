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
    COMPANY_REVIEW = "COMPANY_REVIEW"


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


def _company_review_writes() -> Iterator[None]:
    return _write_mode_context(_WriteMode.COMPANY_REVIEW)


def company_write_override_active() -> bool:
    return _write_mode.get() in {_WriteMode.COMPANY_REVIEW, _WriteMode.TEST_FIXTURE}


@contextmanager
def _test_fixture_writes() -> Iterator[None]:
    if not getattr(settings, "KNOWLEDGE_TEST_FIXTURE_WRITES", False):
        raise RuntimeError("Test-fixture knowledge writes are disabled outside test settings.")
    with _write_mode_context(_WriteMode.TEST_FIXTURE):
        yield


LIFECYCLE_FIELDS = frozenset({"status", "version", "suggested_by_ai_run_id"})


def _acquire_snapshot_write_lock(model: type[models.Model]) -> None:
    if not getattr(model, "affects_ontology_snapshot", False):
        return
    from .graph import acquire_knowledge_graph_lock

    acquire_knowledge_graph_lock()


class KnowledgeQuerySet(models.QuerySet):
    @transaction.atomic
    def update_or_create(self, defaults=None, create_defaults=None, **kwargs):
        _acquire_snapshot_write_lock(self.model)
        return super().update_or_create(
            defaults=defaults,
            create_defaults=create_defaults,
            **kwargs,
        )

    @transaction.atomic
    def update(self, **kwargs):
        _acquire_snapshot_write_lock(self.model)
        mode = _write_mode.get()
        if mode == _WriteMode.SYSTEM_SEED:
            if self.filter(organization_id__isnull=False).exists():
                raise ValidationError("SYSTEM seed writes cannot mutate organization knowledge.")
            self.model._validate_system_seed_queryset_fields(set(kwargs))
            objects = list(self)
            for instance in objects:
                for field, value in kwargs.items():
                    if isinstance(value, BaseExpression):
                        raise ValidationError(
                            f"Expression updates are not supported for guarded field '{field}'."
                        )
                    setattr(instance, field, value)
                instance._prepare_knowledge_write()
                instance._validate_knowledge_write(
                    creating=False, write_fields=set(kwargs)
                )
            with _write_mode_context(_WriteMode.VALIDATED_BULK):
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
            instance._validate_knowledge_write(creating=False, write_fields=set(kwargs))
        with _write_mode_context(_WriteMode.VALIDATED_BULK):
            return super().update(**kwargs)

    @transaction.atomic
    def bulk_create(self, objs, **kwargs):
        _acquire_snapshot_write_lock(self.model)
        objects = list(objs)
        mode = _write_mode.get()
        for instance in objects:
            instance._validate_bulk_create()
            instance._prepare_knowledge_write()
            instance._validate_knowledge_write(creating=True)
            if mode == _WriteMode.SYSTEM_SEED and instance.organization_id is not None:
                raise ValidationError("SYSTEM seed writes cannot create organization knowledge.")
        return super().bulk_create(objects, **kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        _acquire_snapshot_write_lock(self.model)
        objects = list(objs)
        mode = _write_mode.get()
        field_names = {field.name if hasattr(field, "name") else str(field) for field in fields}
        if mode == _WriteMode.NORMAL:
            self.model._validate_bulk_update_fields(field_names)
        elif mode == _WriteMode.SYSTEM_SEED:
            self.model._validate_system_seed_fields(field_names)
        for instance in objects:
            instance._prepare_knowledge_write()
            instance._validate_knowledge_write(creating=False, write_fields=field_names)
        fields = self.model._augment_bulk_update_fields(field_names)
        with _write_mode_context(_WriteMode.VALIDATED_BULK):
            return super().bulk_update(objects, fields, **kwargs)

    @transaction.atomic
    def delete(self):
        _acquire_snapshot_write_lock(self.model)
        objects = list(self)
        for instance in objects:
            instance._ensure_knowledge_not_referenced()
        return super().delete()


class KnowledgeManager(models.Manager.from_queryset(KnowledgeQuerySet)):
    pass


class GraphAssociationQuerySet(models.QuerySet):
    @staticmethod
    def _acquire_lock() -> None:
        from .graph import acquire_knowledge_graph_lock

        acquire_knowledge_graph_lock()

    @transaction.atomic
    def update_or_create(self, defaults=None, create_defaults=None, **kwargs):
        self._acquire_lock()
        return super().update_or_create(
            defaults=defaults,
            create_defaults=create_defaults,
            **kwargs,
        )

    @transaction.atomic
    def update(self, **kwargs):
        self._acquire_lock()
        return super().update(**kwargs)

    @transaction.atomic
    def bulk_create(self, objs, **kwargs):
        self._acquire_lock()
        return super().bulk_create(objs, **kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        self._acquire_lock()
        return super().bulk_update(objs, fields, **kwargs)

    @transaction.atomic
    def delete(self):
        self._acquire_lock()
        return super().delete()


class GraphAssociationManager(models.Manager.from_queryset(GraphAssociationQuerySet)):
    pass


class GraphAssociationModel(models.Model):
    objects = GraphAssociationManager()

    class Meta:
        abstract = True

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        from .graph import acquire_knowledge_graph_lock

        acquire_knowledge_graph_lock()
        super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        from .graph import acquire_knowledge_graph_lock

        acquire_knowledge_graph_lock()
        return super().delete(*args, **kwargs)


class GuardedKnowledgeModel(models.Model):
    objects = KnowledgeManager()
    affects_ontology_snapshot = False

    immutable_fields: frozenset[str] = frozenset()
    identity_fields: frozenset[str] = frozenset({"organization_id"})
    system_seed_update_fields: frozenset[str] = frozenset(
        {"status", "version", "suggested_by_ai_run_id", "updated_at"}
    )

    class Meta:
        abstract = True

    def _prepare_knowledge_write(self) -> None:
        pass

    def _validate_bulk_create(self) -> None:
        pass

    @classmethod
    def _augment_bulk_update_fields(cls, fields: set[str]) -> list[str]:
        return list(fields)

    def _augment_save_update_fields(self, fields: set[str]) -> set[str]:
        return fields

    def _validate_domain_invariants(self) -> None:
        self.clean()

    @classmethod
    def _validate_guarded_update_fields(cls, fields: set[str]) -> None:
        normalized = {field.removesuffix("_id") for field in fields}
        if normalized & LIFECYCLE_FIELDS:
            raise ValidationError("Knowledge status, version, and AI origin may change only through the audited review service.")
        identity = {field.removesuffix("_id") for field in cls.identity_fields}
        if normalized & identity:
            raise ValidationError("Knowledge ownership and identity fields are immutable after creation.")
        immutable = {field.removesuffix("_id") for field in cls.immutable_fields}
        if normalized & immutable:
            raise ValidationError("Knowledge evidence source snapshots are immutable.")

    @classmethod
    def _validate_queryset_update_fields(cls, fields: set[str]) -> None:
        cls._validate_guarded_update_fields(fields)

    @classmethod
    def _validate_bulk_update_fields(cls, fields: set[str]) -> None:
        cls._validate_guarded_update_fields(fields)

    @classmethod
    def _validate_system_seed_fields(cls, fields: set[str]) -> None:
        normalized = {field.removesuffix("_id") for field in fields}
        allowed = {field.removesuffix("_id") for field in cls.system_seed_update_fields}
        if normalized - allowed:
            raise ValidationError("SYSTEM seed may update only declared seed-safe content and lifecycle fields.")

    @classmethod
    def _validate_system_seed_queryset_fields(cls, fields: set[str]) -> None:
        cls._validate_system_seed_fields(fields)

    def _validate_knowledge_write(
        self, *, creating: bool, write_fields: set[str] | None = None
    ) -> None:
        mode = _write_mode.get()
        original = None
        changed_fields: set[str] = set()
        if not creating:
            original = type(self).objects.get(pk=self.pk)
            changed_fields = {
                field.name
                for field in self._meta.concrete_fields
                if getattr(self, field.attname) != getattr(original, field.attname)
            }
            if any(getattr(self, field) != getattr(original, field) for field in self.identity_fields):
                raise ValidationError("Knowledge ownership and identity fields are immutable after creation.")
            if any(getattr(self, field) != getattr(original, field) for field in self.immutable_fields):
                raise ValidationError("Knowledge evidence source snapshots are immutable.")
        self._validate_domain_invariants()
        if mode == _WriteMode.SYSTEM_SEED:
            if self.organization_id is not None:
                raise ValidationError("SYSTEM seed writes cannot mutate organization knowledge.")
            self._validate_system_seed_fields(
                changed_fields if write_fields is None else write_fields
            )
            return
        if mode in {_WriteMode.AUDITED_REVIEW, _WriteMode.TEST_FIXTURE, _WriteMode.VALIDATED_BULK}:
            return
        if creating:
            if self.suggested_by_ai_run_id and self.status != "SUGGESTED":
                raise ValidationError("AI-originated knowledge must start SUGGESTED.")
            if self.status != "SUGGESTED" or self.version != 1:
                raise ValidationError("Ordinary knowledge creation must start SUGGESTED at version 1.")
            return
        if (
            self.status != original.status
            or self.version != original.version
            or self.suggested_by_ai_run_id != original.suggested_by_ai_run_id
        ):
            raise ValidationError("Knowledge lifecycle changes must use the audited review service.")

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        _acquire_snapshot_write_lock(type(self))
        creating = self._state.adding
        self._prepare_knowledge_write()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = self._augment_save_update_fields(set(update_fields))
            kwargs["update_fields"] = update_fields
        self._validate_knowledge_write(creating=creating, write_fields=update_fields)
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

    @transaction.atomic
    def delete(self, *args, **kwargs):
        _acquire_snapshot_write_lock(type(self))
        self._ensure_knowledge_not_referenced()
        return super().delete(*args, **kwargs)


class CompanyRevisionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if company_write_override_active():
            return super().update(**kwargs)
        objects = list(self)
        for instance in objects:
            for field, value in kwargs.items():
                if isinstance(value, BaseExpression):
                    raise ValidationError("Expression updates are not supported for company revisions.")
                setattr(instance, field, value)
            instance._validate_company_revision_write(creating=False)
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        objects = list(objs)
        for instance in objects:
            instance._validate_company_revision_write(creating=True)
        return super().bulk_create(objects, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objects = list(objs)
        for instance in objects:
            instance._validate_company_revision_write(creating=False)
        return super().bulk_update(objects, fields, **kwargs)

    def delete(self):
        for instance in self:
            instance._validate_company_revision_delete()
        return super().delete()


class CompanyRevisionManager(models.Manager.from_queryset(CompanyRevisionQuerySet)):
    pass


class CompanyRevisionModel(models.Model):
    objects = CompanyRevisionManager()
    initial_status = "DRAFT"
    frozen_statuses: frozenset[str] = frozenset()
    identity_fields = frozenset({"organization_id", "version", "supersedes_id", "created_by_id"})
    business_fields: frozenset[str] = frozenset()
    frozen_label = "revision"

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def _validate_company_revision_write(self, *, creating: bool) -> None:
        self.clean()
        if creating:
            if not company_write_override_active() and self.status != self.initial_status:
                raise ValidationError(
                    f"Company revisions must start in {self.initial_status} status and use the review service."
                )
            return
        original = type(self).objects.get(pk=self.pk)
        if any(getattr(self, field) != getattr(original, field) for field in self.identity_fields):
            raise ValidationError("Company revision ownership and identity fields are immutable.")
        changed_business_fields = {
            field
            for field in self.business_fields
            if getattr(self, field) != getattr(original, field)
        }
        if original.status in self.frozen_statuses and changed_business_fields:
            raise ValidationError(f"{self.frozen_label} business fields are immutable.")
        if self.status != original.status and not company_write_override_active():
            raise ValidationError("Company revision lifecycle changes must use the review service.")

    def _validate_company_revision_delete(self) -> None:
        if self.status in self.frozen_statuses:
            raise ValidationError(f"{self.frozen_label} revisions are immutable and cannot be deleted.")

    def save(self, *args, **kwargs):
        self._validate_company_revision_write(creating=self._state.adding)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._validate_company_revision_delete()
        return super().delete(*args, **kwargs)


def validate_evidence_link_scope(*, owner, evidence_objects) -> None:
    evidence = list(evidence_objects)
    if owner.organization_id is None:
        if any(item.organization_id is not None for item in evidence):
            raise ValidationError("SYSTEM knowledge may link only SYSTEM evidence.")
        return
    if any(item.organization_id not in {None, owner.organization_id} for item in evidence):
        raise ValidationError("Knowledge evidence must be visible to the owner's organization.")
