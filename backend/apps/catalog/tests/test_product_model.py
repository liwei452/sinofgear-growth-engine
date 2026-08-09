from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from apps.catalog.models import Product


def product_values(organization, **overrides):
    values = {
        "organization": organization,
        "name_zh": "精密斜齿轮",
        "name_en": "Precision Helical Gear",
        "module_min": Decimal("0.5"),
        "module_max": Decimal("8.0"),
        "tooth_count_min": 8,
        "tooth_count_max": 240,
        "pressure_angle": Decimal("20"),
        "accuracy_grade": "ISO 6",
        "heat_treatment": "Carburized",
        "surface_treatment": "Shot peened",
        "manufacturing_capabilities": ["hobbing", "grinding"],
        "inspection_capabilities": ["CMM", "gear measuring center"],
        "moq": 10,
        "lead_time": "4-6 weeks",
        "landing_page_url": "https://example.com/gears/helical",
        "status": Product.Status.ACTIVE,
        "internal_notes": "Margin target is confidential.",
    }
    values.update(overrides)
    return values


@pytest.mark.django_db
def test_valid_structured_product_is_persisted(organizations) -> None:
    own, _ = organizations

    product = Product.objects.create(**product_values(own))

    assert product.version == 1
    assert product.module_min == Decimal("0.5")
    assert product.manufacturing_capabilities == ["hobbing", "grinding"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"name_en": "   "}, "name_en"),
        ({"module_min": 0}, "module_min"),
        ({"module_min": 2, "module_max": 1}, "module_max"),
        ({"tooth_count_min": 0}, "tooth_count_min"),
        ({"tooth_count_min": 20, "tooth_count_max": 10}, "tooth_count_max"),
        ({"pressure_angle": 0}, "pressure_angle"),
        ({"pressure_angle": 91}, "pressure_angle"),
        ({"moq": 0}, "moq"),
        ({"landing_page_url": "not a URL"}, "landing_page_url"),
        ({"manufacturing_capabilities": "hobbing"}, "manufacturing_capabilities"),
        ({"inspection_capabilities": ["CMM", 3]}, "inspection_capabilities"),
        ({"manufacturing_capabilities": ["hobbing", " "]}, "manufacturing_capabilities"),
    ],
)
def test_invalid_product_fields_are_rejected(organizations, overrides, field) -> None:
    own, _ = organizations
    product = Product(**product_values(own, **overrides))

    with pytest.raises(ValidationError) as error:
        product.full_clean()

    assert field in error.value.message_dict


@pytest.mark.django_db
def test_database_constraints_reject_invalid_ordered_ranges(organizations) -> None:
    own, _ = organizations
    valid = Product.objects.create(**product_values(own))

    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE catalog_product SET module_min = %s, module_max = %s WHERE id = %s",
            ["9", "1", valid.id.hex],
        )


@pytest.mark.django_db
def test_product_organization_cannot_change_after_creation(organizations) -> None:
    own, other = organizations
    product = Product.objects.create(**product_values(own))
    product.organization = other

    with pytest.raises(ValidationError, match="organization"):
        product.save()
