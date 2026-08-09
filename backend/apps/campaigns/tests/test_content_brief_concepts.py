import pytest
from django.core.exceptions import ValidationError

from apps.campaigns.models import Campaign, ContentBrief, ContentBriefConceptLink
from apps.campaigns.serializers import ConceptLinkInputSerializer

from .conftest import make_concept


@pytest.mark.parametrize("role", ["PRODUCT_TYPE", "MANUFACTURING_PROCESS"])
def test_brief_concept_input_accepts_supported_product_and_process_roles(role):
    serializer = ConceptLinkInputSerializer(data={
        "role": role,
        "concept_id": "10000000-0000-4000-8000-000000000001",
    })

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role", "concept_type"),
    [
        ("PRODUCT_TYPE", "PRODUCT_TYPE"),
        ("MANUFACTURING_PROCESS", "PROCESS"),
        ("TARGET_INDUSTRY", "INDUSTRY"),
        ("TARGET_CUSTOMER_TYPE", "CUSTOMER_TYPE"),
        ("PURCHASE_INTENT", "PURCHASE_INTENT"),
        ("STANDARD", "STANDARD"),
        ("APPLICATION", "APPLICATION"),
    ],
)
def test_brief_concept_roles_accept_exact_approved_visible_type(
    campaign_organizations, campaign_user, role, concept_type
):
    own, _ = campaign_organizations
    campaign = Campaign.objects.create(organization=own, name="Launch")
    brief = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=campaign_user
    )
    concept = make_concept(own, concept_type=concept_type, code=role)

    link = ContentBriefConceptLink.objects.create(
        organization=own, brief=brief, concept=concept, role=role
    )

    assert link.concept_id == concept.id


@pytest.mark.django_db
def test_brief_concept_link_fails_closed_for_wrong_type_scope_or_status(
    campaign_organizations, campaign_user
):
    own, other = campaign_organizations
    campaign = Campaign.objects.create(organization=own, name="Launch")
    brief = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=campaign_user
    )
    wrong_type = make_concept(own, concept_type="MATERIAL", code="WRONG")
    foreign = make_concept(other, concept_type="INDUSTRY", code="FOREIGN")
    suggested = make_concept(
        own, concept_type="INDUSTRY", code="SUGGESTED", status="SUGGESTED"
    )

    for concept in (wrong_type, foreign, suggested):
        with pytest.raises(ValidationError):
            ContentBriefConceptLink.objects.create(
                organization=own,
                brief=brief,
                concept=concept,
                role="TARGET_INDUSTRY",
            )
