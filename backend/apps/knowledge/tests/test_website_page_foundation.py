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


@pytest.mark.django_db
def test_page_verify_revalidates_deprecated_concept_link(organizations) -> None:
    organization, _ = organizations
    actor = make_user("page-verify-concept")
    concept = make_concept(
        code="APPLICATION_VERIFY",
        concept_type=KnowledgeConcept.ConceptType.APPLICATION,
        organization=organization,
    )
    page = make_page(organization, actor)
    WebsitePageConceptLink.objects.create(
        website_page=page,
        concept=concept,
        role=WebsitePageConceptLink.Role.APPLICATION,
    )
    service = WebsitePageReviewService(organization)
    service.submit(page, actor=actor)
    with _test_fixture_writes():
        KnowledgeConcept.objects.filter(pk=concept.pk).update(
            status=KnowledgeConcept.Status.DEPRECATED
        )

    with pytest.raises(ValidationError, match="APPROVED"):
        service.verify(page, actor=actor)

    page.refresh_from_db()
    assert page.status == WebsitePage.Status.IN_REVIEW


@pytest.mark.django_db
def test_page_revision_invalid_product_copy_is_atomic_and_can_be_skipped(organizations) -> None:
    organization, _ = organizations
    actor = make_user("page-invalid-product-copy")
    product = make_product(organization, name="Product A")
    page = make_page(organization, actor)
    WebsitePageProductLink.objects.create(
        website_page=page,
        product=product,
        relation_type=WebsitePageProductLink.RelationType.PRIMARY,
    )
    service = WebsitePageReviewService(organization)
    service.submit(page, actor=actor)
    page = service.verify(page, actor=actor)
    product.status = Product.Status.ARCHIVED
    product.save(update_fields=["status"])

    before_count = WebsitePage.objects.count()
    with pytest.raises(ValidationError, match="Archived"):
        service.create_revision(page, actor=actor)
    assert WebsitePage.objects.count() == before_count

    revision = service.create_revision(
        page,
        actor=actor,
        copy_product_links=False,
    )
    assert revision.status == WebsitePage.Status.DRAFT
    assert not revision.product_links.exists()


@pytest.mark.django_db
def test_page_revision_can_skip_invalid_concepts_and_keep_valid_products(organizations) -> None:
    organization, _ = organizations
    actor = make_user("page-invalid-concept-copy")
    product = make_product(organization, name="Product A")
    concept = make_concept(
        code="APPLICATION_COPY",
        concept_type=KnowledgeConcept.ConceptType.APPLICATION,
        organization=organization,
    )
    page = make_page(organization, actor)
    WebsitePageProductLink.objects.create(
        website_page=page,
        product=product,
        relation_type=WebsitePageProductLink.RelationType.PRIMARY,
    )
    WebsitePageConceptLink.objects.create(
        website_page=page,
        concept=concept,
        role=WebsitePageConceptLink.Role.APPLICATION,
    )
    service = WebsitePageReviewService(organization)
    service.submit(page, actor=actor)
    page = service.verify(page, actor=actor)
    with _test_fixture_writes():
        KnowledgeConcept.objects.filter(pk=concept.pk).update(
            status=KnowledgeConcept.Status.DEPRECATED
        )

    before_count = WebsitePage.objects.count()
    with pytest.raises(ValidationError, match="APPROVED"):
        service.create_revision(page, actor=actor)
    assert WebsitePage.objects.count() == before_count

    revision = service.create_revision(
        page,
        actor=actor,
        copy_concept_links=False,
    )
    assert revision.product_links.get().product_id == product.id
    assert not revision.concept_links.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("flag_name", "invalid_value"),
    [
        ("copy_product_links", 0),
        ("copy_product_links", "true"),
        ("copy_concept_links", 1),
        ("copy_concept_links", "false"),
    ],
)
def test_page_revision_copy_flags_require_native_bool(
    organizations, flag_name, invalid_value
) -> None:
    organization, _ = organizations
    actor = make_user(f"page-copy-bool-{flag_name}-{invalid_value}")
    page = make_page(organization, actor)
    service = WebsitePageReviewService(organization)
    service.submit(page, actor=actor)
    page = service.verify(page, actor=actor)

    with pytest.raises(ValidationError, match="boolean"):
        service.create_revision(page, actor=actor, **{flag_name: invalid_value})


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "invalid_value", "message"),
    [
        ("page_type", "INVALID", "page type"),
        ("source_type", "INVALID", "source type"),
        ("primary_cta_url", "http://example.test/contact", "CTA URL"),
        ("primary_cta_url", "https://user:pass@example.test/contact", "CTA URL"),
    ],
)
def test_page_rejects_invalid_enums_and_cta_url(
    organizations, field, invalid_value, message
) -> None:
    actor = make_user(f"page-input-{field}-{len(invalid_value)}")

    with pytest.raises(ValidationError, match=message):
        make_page(organizations[0], actor, **{field: invalid_value})


@pytest.mark.django_db
@pytest.mark.parametrize("invalid_url", [None, 123, ""])
def test_page_canonical_url_non_string_or_empty_is_validation_error(
    organizations, invalid_url
) -> None:
    actor = make_user(f"page-canonical-type-{invalid_url}")

    with pytest.raises(ValidationError, match="Canonical URL"):
        make_page(organizations[0], actor, canonical_url=invalid_url)


@pytest.mark.django_db
def test_page_root_url_spellings_normalize_to_same_identity(organizations) -> None:
    organization, _ = organizations
    actor = make_user("page-root-normalization")

    first = make_page(organization, actor, canonical_url="https://Example.TEST")
    second = make_page(
        organization,
        actor,
        canonical_url="https://example.test/",
        version=2,
    )

    assert first.canonical_url == "https://example.test/"
    assert second.canonical_url == first.canonical_url


@pytest.mark.django_db
def test_page_normalizes_language_and_allows_https_cta_fragment(organizations) -> None:
    actor = make_user("page-language-cta")

    page = make_page(
        organizations[0],
        actor,
        language=" EN-US ",
        primary_cta_url="https://Example.TEST/contact#rfq",
    )

    assert page.language == "en-us"
    assert page.primary_cta_url == "https://example.test/contact#rfq"
