from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from typing import Iterator

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models.deletion import ProtectedError
from django.db.models.expressions import BaseExpression

from apps.common.models import OrganizationScopedModel
from apps.knowledge.models import KnowledgeConcept


_allow_explicit_product_version: ContextVar[bool] = ContextVar(
    "allow_explicit_product_version", default=False
)
_allow_link_retirement: ContextVar[bool] = ContextVar("allow_link_retirement", default=False)


@contextmanager
def _explicit_product_version_writes() -> Iterator[None]:
    token = _allow_explicit_product_version.set(True)
    try:
        yield
    finally:
        _allow_explicit_product_version.reset(token)


@contextmanager
def _product_link_retirement_writes() -> Iterator[None]:
    token = _allow_link_retirement.set(True)
    try:
        yield
    finally:
        _allow_link_retirement.reset(token)


def validate_string_list(value: object) -> None:
    if not isinstance(value, list):
        raise ValidationError("Value must be a JSON list of non-blank strings.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError("Every capability must be a non-blank string.")


class ProductQuerySet(models.QuerySet):
    @transaction.atomic
    def update(self, **kwargs):
        if "version" in kwargs:
            raise ValidationError("Product version cannot be assigned directly.")
        if {"organization", "organization_id"} & set(kwargs):
            raise ValidationError("Product organization is immutable after creation.")
        rows = list(self.select_for_update().order_by("pk"))
        for row in rows:
            for field, value in kwargs.items():
                if isinstance(value, BaseExpression):
                    raise ValidationError(
                        f"Expression updates are not supported for validated product field '{field}'."
                    )
                setattr(row, field, value)
            row.save(update_fields=[*kwargs, "updated_at"])
        return len(rows)

    def bulk_create(self, objs, **kwargs):
        rows = sorted(objs, key=lambda row: str(row.pk))
        for row in rows:
            if row.version != 1:
                raise ValidationError("New products must start at version 1.")
            row.full_clean()
        return super().bulk_create(rows, **kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        field_names = {field.name if hasattr(field, "name") else str(field) for field in fields}
        if "version" in field_names:
            raise ValidationError("Product version cannot be assigned directly.")
        if {"organization", "organization_id"} & field_names:
            raise ValidationError("Product organization is immutable after creation.")
        rows = sorted(objs, key=lambda row: str(row.pk))
        for row in rows:
            row.save(update_fields=[*field_names, "updated_at"])
        return len(rows)


class ProductManager(models.Manager.from_queryset(ProductQuerySet)):
    pass


class Product(OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        ARCHIVED = "ARCHIVED", "Archived"

    name_zh = models.CharField(max_length=255, blank=True)
    name_en = models.CharField(max_length=255)
    module_min = models.DecimalField(
        max_digits=10, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))]
    )
    module_max = models.DecimalField(
        max_digits=10, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))]
    )
    tooth_count_min = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    tooth_count_max = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    pressure_angle = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001")), MaxValueValidator(Decimal("90"))],
    )
    accuracy_grade = models.CharField(max_length=128, blank=True)
    heat_treatment = models.CharField(max_length=255, blank=True)
    surface_treatment = models.CharField(max_length=255, blank=True)
    manufacturing_capabilities = models.JSONField(default=list, validators=[validate_string_list])
    inspection_capabilities = models.JSONField(default=list, validators=[validate_string_list])
    moq = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    lead_time = models.CharField(max_length=255, blank=True)
    landing_page_url = models.URLField(max_length=2048, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    internal_notes = models.TextField(blank=True)
    objects = ProductManager()

    class Meta:
        ordering = ["name_en", "id"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(module_min__gt=0), name="catalog_product_module_min_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(module_max__gte=models.F("module_min")),
                name="catalog_product_module_range_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(tooth_count_min__gt=0), name="catalog_product_tooth_min_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(tooth_count_max__gte=models.F("tooth_count_min")),
                name="catalog_product_tooth_range_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(pressure_angle__gt=0, pressure_angle__lte=90),
                name="catalog_product_pressure_angle_valid",
            ),
            models.CheckConstraint(condition=models.Q(moq__gt=0), name="catalog_product_moq_positive"),
            models.CheckConstraint(
                condition=models.Q(version__gt=0), name="catalog_product_version_positive"
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.name_en = self.name_en.strip()
        self.name_zh = self.name_zh.strip()
        if not self.name_en:
            raise ValidationError({"name_en": "English name must not be blank."})
        if self.module_min is not None and self.module_max is not None:
            if self.module_max < self.module_min:
                raise ValidationError({"module_max": "Module maximum must be at least the minimum."})
        if self.tooth_count_min is not None and self.tooth_count_max is not None:
            if self.tooth_count_max < self.tooth_count_min:
                raise ValidationError(
                    {"tooth_count_max": "Tooth-count maximum must be at least the minimum."}
                )

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        creating = self._state.adding
        if creating and self.version != 1:
            raise ValidationError("New products must start at version 1.")
        if not creating:
            original = type(self).objects.select_for_update().get(pk=self.pk)
            if original.organization_id != self.organization_id:
                raise ValidationError("Product organization is immutable after creation.")
            update_fields = kwargs.get("update_fields")
            persisted_fields = (
                {field.removesuffix("_id") for field in update_fields}
                if update_fields is not None
                else {field.name for field in self._meta.concrete_fields}
            )
            changed_fields = {
                field.name
                for field in self._meta.concrete_fields
                if field.name in persisted_fields
                and getattr(self, field.attname) != getattr(original, field.attname)
            }
            explicit_version_change = self.version != original.version
            if explicit_version_change:
                if (
                    not _allow_explicit_product_version.get()
                    or self.version != original.version + 1
                ):
                    raise ValidationError(
                        "Product version may change only by one through a versioned write."
                    )
            elif changed_fields - {"updated_at"}:
                self.version = original.version + 1
                if update_fields is not None:
                    kwargs["update_fields"] = set(update_fields) | {"version"}
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        links = list(self.concept_links.all())
        if links:
            raise ProtectedError(
                "Linked products must be archived rather than deleted.",
                links,
            )
        return super().delete(*args, **kwargs)


ROLE_CONCEPT_TYPES = {
    "TYPE": frozenset({KnowledgeConcept.ConceptType.PRODUCT_TYPE}),
    "MATERIAL": frozenset({KnowledgeConcept.ConceptType.MATERIAL}),
    "PROCESS": frozenset({KnowledgeConcept.ConceptType.PROCESS}),
    "STANDARD": frozenset({KnowledgeConcept.ConceptType.STANDARD}),
    "APPLICATION": frozenset(
        {
            KnowledgeConcept.ConceptType.APPLICATION,
            KnowledgeConcept.ConceptType.INDUSTRY,
        }
    ),
    "PARAMETER": frozenset({KnowledgeConcept.ConceptType.PARAMETER}),
}

LINK_IDENTITY_FIELDS = frozenset(
    {
        "organization",
        "organization_id",
        "product",
        "product_id",
        "concept",
        "concept_id",
        "role",
        "version",
        "retired_at",
    }
)


def _lock_and_refresh_link_references(links) -> None:
    product_ids = sorted({link.product_id for link in links}, key=str)
    products = {
        product.id: product
        for product in Product.objects.filter(pk__in=product_ids)
        .order_by("id")
        .select_for_update(of=("self",))
    }
    concept_ids = sorted({link.concept_id for link in links}, key=str)
    concepts = {
        concept.id: concept
        for concept in KnowledgeConcept.objects.filter(pk__in=concept_ids)
        .order_by("id")
        .select_for_update(of=("self",))
    }
    for link in links:
        product = products.get(link.product_id)
        concept = concepts.get(link.concept_id)
        if product is None:
            raise ValidationError({"product": "Product does not exist."})
        if concept is None:
            raise ValidationError({"concept": "Concept does not exist."})
        if product.status == Product.Status.ARCHIVED:
            raise ValidationError({"product": "Archived products cannot accept new links."})
        link.product = product
        link.concept = concept


class ProductConceptLinkQuerySet(models.QuerySet):
    def active(self):
        return self.filter(retired_at__isnull=True)

    @transaction.atomic
    def bulk_create(self, objs, **kwargs):
        links = list(objs)
        _lock_and_refresh_link_references(links)
        for link in links:
            link._validate_new_state()
            link.full_clean()
        return super().bulk_create(links, **kwargs)

    def delete(self):
        protected = list(self)
        if protected:
            raise ProtectedError(
                "Product concept link history cannot be deleted; retire active links instead.",
                protected,
            )
        return 0, {}

    @transaction.atomic
    def update(self, **kwargs):
        if LINK_IDENTITY_FIELDS & set(kwargs):
            raise ValidationError("Product concept link identity is immutable; replace the link instead.")
        links = list(self.select_related("product", "concept"))
        for link in links:
            for field, value in kwargs.items():
                if isinstance(value, BaseExpression):
                    raise ValidationError(
                        f"Expression updates are not supported for validated link field '{field}'."
                    )
                if field.endswith("_id"):
                    setattr(link, field, value)
                else:
                    setattr(link, field, value)
            link.full_clean()
        return super().update(**kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        field_names = {field.name if hasattr(field, "name") else str(field) for field in fields}
        if LINK_IDENTITY_FIELDS & field_names:
            raise ValidationError("Product concept link identity is immutable; replace the link instead.")
        links = list(objs)
        for link in links:
            link.full_clean()
        return super().bulk_update(links, fields, **kwargs)


class ProductConceptLinkManager(models.Manager.from_queryset(ProductConceptLinkQuerySet)):
    pass


class ProductConceptLink(OrganizationScopedModel):
    class Role(models.TextChoices):
        TYPE = "TYPE", "Type"
        MATERIAL = "MATERIAL", "Material"
        PROCESS = "PROCESS", "Process"
        STANDARD = "STANDARD", "Standard"
        APPLICATION = "APPLICATION", "Application"
        PARAMETER = "PARAMETER", "Parameter"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="concept_links")
    concept = models.ForeignKey(
        KnowledgeConcept, on_delete=models.PROTECT, related_name="product_links"
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    version = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    retired_at = models.DateTimeField(null=True, blank=True)

    objects = ProductConceptLinkManager()

    class Meta:
        ordering = ["role", "concept__code", "id"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["product", "role", "concept"],
                condition=models.Q(retired_at__isnull=True),
                name="catalog_unique_product_role_concept",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0), name="catalog_product_link_version_positive"
            ),
        ]
        indexes = [
            models.Index(
                fields=["product", "retired_at", "role"],
                name="catalog_link_active_role_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if not self.product_id or not self.concept_id or not self.organization_id:
            return
        if self.organization_id != self.product.organization_id:
            raise ValidationError({"organization": "Link organization must match the product organization."})
        if self.concept.organization_id not in {None, self.organization_id}:
            raise ValidationError({"concept": "Concept must belong to the product organization or be SYSTEM."})
        if self.concept.status != KnowledgeConcept.Status.APPROVED:
            raise ValidationError({"concept": "Only APPROVED concepts may be linked."})
        expected_types = ROLE_CONCEPT_TYPES.get(self.role)
        if expected_types is not None and self.concept.concept_type not in expected_types:
            raise ValidationError(
                {"concept": f"Concept type is not compatible with the {self.role} product role."}
            )

    def _validate_new_state(self) -> None:
        if self.version != 1 or self.retired_at is not None:
            raise ValidationError("New product concept links must start active at version 1.")

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        if self._state.adding:
            _lock_and_refresh_link_references([self])
            self._validate_new_state()
        if not self._state.adding:
            original = type(self).objects.get(pk=self.pk)
            if any(
                getattr(self, field) != getattr(original, field)
                for field in ("organization_id", "product_id", "concept_id", "role", "version")
            ):
                raise ValidationError(
                    "Product concept link identity is immutable; replace the link instead."
                )
            if self.retired_at != original.retired_at:
                if not _allow_link_retirement.get() or original.retired_at is not None:
                    raise ValidationError(
                        "Product concept link retirement requires the catalog service."
                    )
                return super().save(*args, **kwargs)
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ProtectedError(
            "Product concept link history cannot be deleted; retire active links instead.",
            [self],
        )


def compatible_link_types_q(*, role_field: str = "role", concept_type_field: str = "concept__concept_type"):
    query = models.Q()
    for role, concept_types in ROLE_CONCEPT_TYPES.items():
        query |= models.Q(
            **{
                role_field: role,
                f"{concept_type_field}__in": tuple(concept_types),
            }
        )
    return query
