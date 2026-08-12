import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.director.models import DirectorDecision, DirectorProposal
from apps.identity.models import Organization, Role
from apps.identity.permissions import PermissionCode


@pytest.fixture
def organization() -> Organization:
    return Organization.objects.create(name="Director Own", slug="director-own")


@pytest.fixture
def user():
    return get_user_model().objects.create_user(username="director-user")


@pytest.fixture
def proposal(organization):
    return DirectorProposal.objects.create(
        organization=organization,
        proposal_type=DirectorProposal.ProposalType.PROMOTION_PLAN,
        title_zh="建议推广德国包装机械市场",
        summary_zh="依据已确认产品能力生成。",
        reason_snapshot={"evidence_count": 3},
        action_reference={"kind": "campaign_draft", "id": "draft-1"},
    )


@pytest.mark.django_db
def test_proposal_is_organization_scoped_and_versioned(organization):
    proposal = DirectorProposal.objects.create(
        organization=organization,
        proposal_type="PROMOTION_PLAN",
        title_zh="建议推广德国包装机械市场",
        summary_zh="依据已确认产品能力生成。",
        reason_snapshot={"evidence_count": 3},
        action_reference={"kind": "campaign_draft", "id": "draft-1"},
    )

    assert proposal.organization == organization
    assert proposal.status == "PENDING"
    assert proposal.version == 1


@pytest.mark.django_db
def test_one_human_decision_per_proposal_version(proposal, user):
    DirectorDecision.objects.create(
        proposal=proposal,
        organization=proposal.organization,
        action="APPROVE",
        proposal_version=1,
        actor=user,
    )

    with pytest.raises(IntegrityError):
        DirectorDecision.objects.create(
            proposal=proposal,
            organization=proposal.organization,
            action="REJECT",
            proposal_version=1,
            actor=user,
        )


@pytest.mark.django_db(transaction=True)
def test_proposal_database_constraints_reject_invalid_priority_and_empty_title(organization):
    values = {
        "organization": organization,
        "proposal_type": DirectorProposal.ProposalType.PROMOTION_PLAN,
        "summary_zh": "依据已确认产品能力生成。",
    }

    with pytest.raises(IntegrityError):
        DirectorProposal.objects.create(priority=0, title_zh="有效标题", **values)
    with pytest.raises(IntegrityError):
        DirectorProposal.objects.create(priority=101, title_zh="有效标题", **values)
    with pytest.raises(IntegrityError):
        DirectorProposal.objects.create(priority=50, title_zh="", **values)


@pytest.mark.django_db
def test_decision_history_is_append_only(proposal, user):
    decision = DirectorDecision.objects.create(
        proposal=proposal,
        organization=proposal.organization,
        action=DirectorDecision.Action.APPROVE,
        proposal_version=proposal.version,
        actor=user,
    )

    decision.comment = "Changed later"
    with pytest.raises(ValidationError, match="append-only"):
        decision.save()
    with pytest.raises(ValidationError, match="append-only"):
        DirectorDecision.objects.filter(pk=decision.pk).update(comment="Changed later")
    with pytest.raises(ValidationError, match="append-only"):
        decision.delete()


@pytest.mark.django_db
def test_builtin_roles_grant_director_permissions_by_responsibility():
    roles = {
        Role.Code.ADMINISTRATOR: Role.objects.create_administrator(),
        Role.Code.OPERATOR: Role.objects.create_operator(),
        Role.Code.REVIEWER: Role.objects.create_reviewer(),
        Role.Code.READ_ONLY: Role.objects.create_read_only(),
    }

    expected = {
        Role.Code.ADMINISTRATOR: {"director.read", "director.decide"},
        Role.Code.OPERATOR: {"director.read", "director.decide"},
        Role.Code.REVIEWER: {"director.read", "director.decide"},
        Role.Code.READ_ONLY: {"director.read"},
    }

    assert {PermissionCode.DIRECTOR_READ.value, PermissionCode.DIRECTOR_DECIDE.value} == {
        "director.read",
        "director.decide",
    }
    for code, role in roles.items():
        assert set(role.permissions) & {"director.read", "director.decide"} == expected[code]


def test_director_permission_classes_use_organization_permission_codes():
    from apps.identity.permissions import CanDecideDirector, CanReadDirector

    assert CanReadDirector.permission_code == PermissionCode.DIRECTOR_READ
    assert CanDecideDirector.permission_code == PermissionCode.DIRECTOR_DECIDE
