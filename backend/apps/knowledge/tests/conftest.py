import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.knowledge.models import KnowledgeConcept


@pytest.fixture
def organizations() -> tuple[Organization, Organization]:
    return (
        Organization.objects.create(name="Own", slug="own"),
        Organization.objects.create(name="Other", slug="other"),
    )


@pytest.fixture
def roles() -> dict[str, Role]:
    return {
        role.code: role
        for role in (
            Role.objects.create_administrator(),
            Role.objects.create_operator(),
            Role.objects.create_reviewer(),
            Role.objects.create_read_only(),
        )
    }


def create_member_client(*, organization: Organization, role: Role, username: str) -> tuple[Membership, APIClient]:
    user = get_user_model().objects.create_user(username=username, password="correct-horse-battery-staple")
    membership = Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="correct-horse-battery-staple")
    return membership, client


def make_concept(
    *,
    code: str,
    concept_type: str = KnowledgeConcept.ConceptType.PRODUCT_TYPE,
    organization: Organization | None = None,
    status: str = KnowledgeConcept.Status.APPROVED,
    created_by=None,
) -> KnowledgeConcept:
    scope = KnowledgeConcept.Scope.ORGANIZATION if organization else KnowledgeConcept.Scope.SYSTEM
    return KnowledgeConcept.objects.create(
        scope=scope,
        organization=organization,
        concept_type=concept_type,
        code=code,
        label_zh=code,
        label_en=code.replace("_", " ").title(),
        status=status,
        created_by=created_by,
    )
