import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Product
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import (
    KnowledgeConcept,
    WebsitePage,
    WebsitePageConceptLink,
    WebsitePageProductLink,
)
from apps.knowledge.services import WebsitePageReviewService

from .conftest import make_concept
from .test_icp_profile_foundation import make_product, make_user


def make_page(organization, actor, *, version=1, supersedes=None, **overrides):
    values = {
        "organization": organization,
        "canonical_url": "https://example.test/page",
        "version": version,
        "supersedes": supersedes,
        "page_type": WebsitePage.PageType.PRODUCT,
        "language": "en",
        "title": "Example Page",
        "content_summary": "A real page summary.",
        "primary_cta_label": "Request information",
        "primary_cta_url": "https://example.test/contact",
        "seo_keywords": ["keyword"],
        "source_type": WebsitePage.SourceType.MANUAL,
        "created_by": actor,
    }
    values.update(overrides)
    return WebsitePage.objects.create(**values)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_url",
    ["http://example.test/page", "https://not valid/page"],
)
def test_website_page_normalizes_https_url_and_rejects_invalid_url(
    organizations, invalid_url
) -> None:
    actor = make_user("page-url")
    page = make_page(
        organizations[0],
        actor,
        canonical_url="HTTPS://Example.TEST:443/page#section",
    )
    assert page.canonical_url == "https://example.test/page"

    with pytest.raises(ValidationError, match="HTTPS"):
        make_page(
            organizations[0],
            actor,
            canonical_url=invalid_url,
            version=2,
        )


@pytest.mark.django_db
def test_website_page_version_and_current_verified_are_unique(organizations) -> None:
    organization, _ = organizations
    actor = make_user("page-unique")
    page = make_page(organization, actor)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_page(organization, actor)
    with pytest.raises(IntegrityError), transaction.atomic(), _test_fixture_writes():
        make_page(
            organization,
            actor,
            version=2,
            status=WebsitePage.Status.VERIFIED,
        )
        make_page(
            organization,
            actor,
            version=3,
            status=WebsitePage.Status.VERIFIED,
        )
    assert page.version == 1


@pytest.mark.django_db
def test_website_page_version_must_be_positive(organizations) -> None:
    actor = make_user("page-version-positive")

    with pytest.raises(ValidationError, match="version"):
        make_page(organizations[0], actor, version=0)


@pytest.mark.django_db
def test_page_revision_supersedes_old_version_and_copies_all_links(organizations) -> None:
    organization, _ = organizations
    actor = make_user("page-revision")
    product = make_product(organization, name="Product A")
    concept = make_concept(
        code="APPLICATION_A",
        concept_type=KnowledgeConcept.ConceptType.APPLICATION,
        organization=organization,
    )
    first = make_page(organization, actor)
    WebsitePageProductLink.objects.create(
        website_page=first,
        product=product,
        relation_type=WebsitePageProductLink.RelationType.PRIMARY,
    )
    WebsitePageConceptLink.objects.create(
        website_page=first,
        concept=concept,
        role=WebsitePageConceptLink.Role.APPLICATION,
    )
    service = WebsitePageReviewService(organization)
    service.submit(first, actor=actor)
    first = service.verify(first, actor=actor)

    second = service.create_revision(first, actor=actor, title="Example Page v2")

    assert second.product_links.get().product_id == product.id
    assert second.concept_links.get().concept_id == concept.id
    assert second.status == WebsitePage.Status.DRAFT
    assert second.last_verified_at is None
    service.submit(second, actor=actor)
    second = service.verify(second, actor=actor)
    first.refresh_from_db()
    assert first.status == WebsitePage.Status.SUPERSEDED
    assert second.status == WebsitePage.Status.VERIFIED
    assert second.last_verified_at is not None


@pytest.mark.django_db
def test_page_product_link_rejects_cross_organization_and_archived_product(organizations) -> None:
    own, other = organizations
    actor = make_user("page-product-isolation")
    page = make_page(own, actor)
    foreign = make_product(other, name="Foreign Product")
    archived = make_product(own, name="Archived Product", status=Product.Status.ARCHIVED)

    for product in (foreign, archived):
        with pytest.raises(ValidationError, match="organization|Archived"):
            WebsitePageProductLink.objects.create(
                website_page=page,
                product=product,
                relation_type=WebsitePageProductLink.RelationType.RELATED,
            )


@pytest.mark.django_db
def test_page_concept_link_enforces_visibility_approval_and_role_type(organizations) -> None:
    own, other = organizations
    actor = make_user("page-concept-guard")
    page = make_page(own, actor)
    foreign = make_concept(
        code="FOREIGN_INDUSTRY",
        concept_type=KnowledgeConcept.ConceptType.INDUSTRY,
        organization=other,
    )
    unapproved = make_concept(
        code="UNAPPROVED_INDUSTRY",
        concept_type=KnowledgeConcept.ConceptType.INDUSTRY,
        organization=own,
        status=KnowledgeConcept.Status.SUGGESTED,
    )
    application = make_concept(
        code="APPLICATION_B",
        concept_type=KnowledgeConcept.ConceptType.APPLICATION,
        organization=own,
    )

    for concept, role in (
        (foreign, WebsitePageConceptLink.Role.INDUSTRY),
        (unapproved, WebsitePageConceptLink.Role.INDUSTRY),
        (application, WebsitePageConceptLink.Role.INDUSTRY),
    ):
        with pytest.raises(ValidationError, match="organization|APPROVED|compatible"):
            WebsitePageConceptLink.objects.create(
                website_page=page,
                concept=concept,
                role=role,
            )


@pytest.mark.django_db
@pytest.mark.parametrize("link_kind", ["product", "concept"])
@pytest.mark.parametrize("write_style", ["create", "update", "bulk_create", "bulk_update", "delete"])
def test_page_links_are_immutable_after_page_leaves_draft(
    organizations, link_kind, write_style
) -> None:
    organization, _ = organizations
    actor = make_user(f"page-link-{link_kind}-{write_style}")
    page = make_page(organization, actor)
    if link_kind == "product":
        target = make_product(organization, name="Product A")
        second_target = make_product(organization, name="Product B")
        model = WebsitePageProductLink
        link = model.objects.create(
            website_page=page,
            product=target,
            relation_type=model.RelationType.PRIMARY,
        )
        create_values = {
            "website_page": page,
            "product": second_target,
            "relation_type": model.RelationType.RELATED,
        }
        update_values = {"relation_type": model.RelationType.RELATED}
    else:
        target = make_concept(
            code="INDUSTRY_A",
            concept_type=KnowledgeConcept.ConceptType.INDUSTRY,
            organization=organization,
        )
        second_target = make_concept(
            code="INDUSTRY_B",
            concept_type=KnowledgeConcept.ConceptType.INDUSTRY,
            organization=organization,
        )
        model = WebsitePageConceptLink
        link = model.objects.create(
            website_page=page,
            concept=target,
            role=model.Role.INDUSTRY,
        )
        create_values = {
            "website_page": page,
            "concept": second_target,
            "role": model.Role.INDUSTRY,
        }
        update_values = {"role": model.Role.INDUSTRY}
    WebsitePageReviewService(organization).submit(page, actor=actor)

    with pytest.raises(ValidationError, match="DRAFT"):
        if write_style == "create":
            model.objects.create(**create_values)
        elif write_style == "update":
            model.objects.filter(pk=link.pk).update(**update_values)
        elif write_style == "bulk_create":
            model.objects.bulk_create([model(**create_values)])
        elif write_style == "bulk_update":
            for field, value in update_values.items():
                setattr(link, field, value)
            model.objects.bulk_update([link], list(update_values))
        else:
            model.objects.filter(pk=link.pk).delete()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seo_keywords", [""]),
        ("seo_keywords", ["x" * 256]),
        ("seo_keywords", [str(index) for index in range(101)]),
        ("content_hash", "A" * 64),
        ("content_hash", "a" * 63),
    ],
)
def test_page_list_and_content_hash_validation(organizations, field, value) -> None:
    actor = make_user(f"page-validation-{len(value)}")

    with pytest.raises(ValidationError, match="list|blank|length|items|SHA-256"):
        make_page(organizations[0], actor, **{field: value})


@pytest.mark.django_db
def test_page_concept_bulk_create_cannot_bypass_role_validation(organizations) -> None:
    organization, _ = organizations
    actor = make_user("page-concept-bulk")
    page = make_page(organization, actor)
    concept = make_concept(
        code="PURCHASE_A",
        concept_type=KnowledgeConcept.ConceptType.PURCHASE_INTENT,
        organization=organization,
    )

    with pytest.raises(ValidationError, match="compatible"):
        WebsitePageConceptLink.objects.bulk_create(
            [
                WebsitePageConceptLink(
                    website_page=page,
                    concept=concept,
                    role=WebsitePageConceptLink.Role.APPLICATION,
                )
            ]
        )
