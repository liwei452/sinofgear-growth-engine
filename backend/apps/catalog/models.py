from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models.deletion import ProtectedError
from django.db.models.expressions import BaseExpression

from apps.common.models import OrganizationScopedModel
from apps.knowledge.models import KnowledgeConcept


def validate_string_list(value: object) -> None:
    if not isinstance(value, list):
        raise ValidationError("Value must be a JSON list of non-blank strings.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError("Every capability must be a non-blank string.")


class ProductQuerySet(models.QuerySet):
    @transaction.atomic
    def update(self, **kwargs):
        if "organization" in kwargs or "organization_id" in kwargs:
            raise ValidationError("Product organization is immutable after creation.")
        rows = list(self)
        for row in rows:
            for field, value in kwargs.items():
                if isinstance(value, BaseExpression):
                    raise ValidationError(
                        f"Expression updates are not supported for validated product field '{field}'."
                    )
                setattr(row, field, value)
            row.full_clean()
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        rows = list(objs)
        for row in rows:
            row.full_clean()
        return super().bulk_create(rows, **kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        field_names = {field.name if hasattr(field, "name") else str(field) for field in fields}
        if {"organization", "organization_id"} & field_names:
            raise ValidationError("Product organization is immutable after creation.")
        rows = list(objs)
        for row in rows:
            row.full_clean()
        return super().bulk_update(rows, fields, **kwargs)


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
    concepts = models.ManyToManyField(
        KnowledgeConcept,
        through="ProductConceptLink",
        related_name="products",
        blank=True,
    )

    objects = ProductManager()

    class Meta:
        ordering = ["name_en", "id"]
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

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            original_organization_id = type(self).objects.only("organization_id").get(pk=self.pk).organization_id
            if original_organization_id != self.organization_id:
                raise ValidationError("Product organization is immutable after creation.")
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
    {"organization", "organization_id", "product", "product_id", "concept", "concept_id", "role", "version"}
)


class ProductConceptLinkQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        links = list(objs)
        for link in links:
            link.full_clean()
        return super().bulk_create(links, **kwargs)

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

    objects = ProductConceptLinkManager()

    class Meta:
        ordering = ["role", "concept__code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "role", "concept"],
                name="catalog_unique_product_role_concept",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0), name="catalog_product_link_version_positive"
            ),
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

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            original = type(self).objects.get(pk=self.pk)
            if any(
                getattr(self, field) != getattr(original, field)
                for field in ("organization_id", "product_id", "concept_id", "role", "version")
            ):
                raise ValidationError(
                    "Product concept link identity is immutable; replace the link instead."
                )
        self.full_clean()
        super().save(*args, **kwargs)
