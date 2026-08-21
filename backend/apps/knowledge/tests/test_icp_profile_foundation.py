from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Product
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import ICPProductLink, ICPProfile
from apps.knowledge.services import ICPProfileReviewService


def make_user(username: str):
    return get_user_model().objects.create_user(username=username)


def make_product(organization, *, name: str, status=Product.Status.ACTIVE) -> Product:
    return Product.objects.create(
        organization=organization,
        name_en=name,
        module_min=Decimal("1"),
        module_max=Decimal("2"),
        tooth_count_min=10,
        tooth_count_max=20,
        pressure_angle=Decimal("20"),
        manufacturing_capabilities=["Capability A"],
        inspection_capabilities=["Inspection A"],
        moq=1,
        status=status,
    )


def make_icp(organization, actor, *, code="PROFILE_A", version=1, supersedes=None, **overrides):
    values = {
        "organization": organization,
        "code": code,
        "version": version,
        "supersedes": supersedes,
        "name": "Profile A",
        "description": "A reusable customer profile.",
        "target_industries": ["Industry A"],
        "company_types": ["Manufacturer"],
        "buyer_roles": ["Buyer"],
        "target_markets": ["Market A"],
        "languages": ["en"],
        "pain_points": ["Long lead time"],
        "buying_triggers": ["New project"],
        "exclusion_rules": ["No active project"],
        "preferred_channels": ["Email"],
        "created_by": actor,
    }
    values.update(overrides)
    return ICPProfile.objects.create(**values)


@pytest.mark.django_db
def test_same_code_has_one_approved_icp_while_different_codes_can_be_approved(organizations) -> None:
    organization, _ = organizations
    actor = make_user("icp-approved")
    first = make_icp(organization, actor, code="PROFILE_A")
    other = make_icp(organization, actor, code="PROFILE_B")
    service = ICPProfileReviewService(organization)
    service.submit(first, actor=actor)
    first = service.approve(first, actor=actor)
    service.submit(other, actor=actor)
    other = service.approve(other, actor=actor)

    assert first.status == ICPProfile.Status.APPROVED
    assert other.status == ICPProfile.Status.APPROVED
    with pytest.raises(IntegrityError), transaction.atomic(), _test_fixture_writes():
        make_icp(
            organization,
            actor,
            code="PROFILE_A",
            version=2,
            status=ICPProfile.Status.APPROVED,
        )


@pytest.mark.django_db
def test_icp_revision_approval_supersedes_old_version_and_copies_links(organizations) -> None:
    organization, _ = organizations
    actor = make_user("icp-revision")
    product = make_product(organization, name="Product A")
    first = make_icp(organization, actor)
    ICPProductLink.objects.create(
        icp_profile=first,
        product=product,
        role=ICPProductLink.Role.PRIMARY,
        priority=1,
        use_cases=["Use case A"],
    )
    service = ICPProfileReviewService(organization)
    service.submit(first, actor=actor)
    first = service.approve(first, actor=actor)

    second = service.create_revision(first, actor=actor, name="Profile A v2")

    copied = second.product_links.get()
    assert copied.product_id == product.id
    assert copied.use_cases == ["Use case A"]
    assert second.status == ICPProfile.Status.DRAFT
    service.submit(second, actor=actor)
    second = service.approve(second, actor=actor)
    first.refresh_from_db()
    assert first.status == ICPProfile.Status.SUPERSEDED
    assert second.status == ICPProfile.Status.APPROVED


@pytest.mark.django_db
@pytest.mark.parametrize("invalid_kind", ["cross_organization", "archived"])
def test_icp_product_link_rejects_foreign_or_archived_product(organizations, invalid_kind) -> None:
    own, other = organizations
    actor = make_user(f"icp-product-{invalid_kind}")
    icp = make_icp(own, actor)
    product = make_product(
        other if invalid_kind == "cross_organization" else own,
        name="Invalid Product",
        status=Product.Status.ARCHIVED if invalid_kind == "archived" else Product.Status.ACTIVE,
    )

    with pytest.raises(ValidationError, match="organization|Archived"):
        ICPProductLink.objects.create(
            icp_profile=icp,
            product=product,
            role=ICPProductLink.Role.PRIMARY,
            priority=1,
            use_cases=[],
        )


@pytest.mark.django_db
@pytest.mark.parametrize("write_style", ["create", "update", "bulk_create", "bulk_update", "delete"])
def test_icp_links_are_immutable_after_profile_leaves_draft(organizations, write_style) -> None:
    organization, _ = organizations
    actor = make_user(f"icp-link-frozen-{write_style}")
    product = make_product(organization, name="Product A")
    second_product = make_product(organization, name="Product B")
    icp = make_icp(organization, actor)
    link = ICPProductLink.objects.create(
        icp_profile=icp,
        product=product,
        role=ICPProductLink.Role.PRIMARY,
        priority=1,
        use_cases=[],
    )
    ICPProfileReviewService(organization).submit(icp, actor=actor)

    with pytest.raises(ValidationError, match="DRAFT"):
        if write_style == "create":
            ICPProductLink.objects.create(
                icp_profile=icp,
                product=second_product,
                role=ICPProductLink.Role.SECONDARY,
                priority=2,
                use_cases=[],
            )
        elif write_style == "update":
            ICPProductLink.objects.filter(pk=link.pk).update(priority=2)
        elif write_style == "bulk_create":
            ICPProductLink.objects.bulk_create(
                [
                    ICPProductLink(
                        icp_profile=icp,
                        product=second_product,
                        role=ICPProductLink.Role.SECONDARY,
                        priority=2,
                        use_cases=[],
                    )
                ]
            )
        elif write_style == "bulk_update":
            link.priority = 2
            ICPProductLink.objects.bulk_update([link], ["priority"])
        else:
            ICPProductLink.objects.filter(pk=link.pk).delete()


@pytest.mark.django_db
def test_stale_link_instance_delete_checks_current_parent_status(organizations) -> None:
    organization, _ = organizations
    actor = make_user("icp-link-stale-delete")
    product = make_product(organization, name="Product A")
    first = make_icp(organization, actor, code="PROFILE_A")
    second = make_icp(organization, actor, code="PROFILE_B")
    stale_link = ICPProductLink.objects.create(
        icp_profile=first,
        product=product,
        role=ICPProductLink.Role.PRIMARY,
        priority=1,
        use_cases=[],
    )
    ICPProductLink.objects.filter(pk=stale_link.pk).update(icp_profile=second)
    ICPProfileReviewService(organization).submit(second, actor=actor)

    with pytest.raises(ValidationError, match="DRAFT"):
        stale_link.delete()

    assert ICPProductLink.objects.filter(pk=stale_link.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_industries", [""]),
        ("buyer_roles", ["x" * 256]),
        ("languages", [str(index) for index in range(101)]),
    ],
)
def test_icp_json_lists_enforce_nonblank_length_and_count(organizations, field, value) -> None:
    actor = make_user(f"icp-list-{field}")

    with pytest.raises(ValidationError, match="list|blank|length|items"):
        make_icp(organizations[0], actor, **{field: value})


@pytest.mark.django_db
def test_icp_version_must_be_positive(organizations) -> None:
    actor = make_user("icp-version-positive")

    with pytest.raises(ValidationError, match="version"):
        make_icp(organizations[0], actor, version=0)


@pytest.mark.django_db
def test_icp_queryset_update_cannot_bypass_revision_identity_or_frozen_business_fields(organizations) -> None:
    organization, _ = organizations
    actor = make_user("icp-queryset-guard")
    icp = make_icp(organization, actor)
    service = ICPProfileReviewService(organization)
    service.submit(icp, actor=actor)

    with pytest.raises(ValidationError):
        ICPProfile.objects.filter(pk=icp.pk).update(name="Bypass")
    with pytest.raises(ValidationError):
        ICPProfile.objects.filter(pk=icp.pk).update(code="OTHER")
