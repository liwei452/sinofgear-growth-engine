import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor

from apps.director.models import DirectorDecision, DirectorProposal
from apps.identity.models import Organization, Role
from apps.identity.permissions import PermissionCode


@pytest.fixture
def organization() -> Organization:
    return Organization.objects.create(name="Director Own", slug="director-own")


@pytest.fixture
def other_organization() -> Organization:
    return Organization.objects.create(name="Director Other", slug="director-other")


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
def test_proposal_organization_is_immutable_through_public_orm_paths(
    proposal, other_organization
):
    proposal.organization = other_organization
    with pytest.raises(ValidationError, match="immutable"):
        proposal.save()

    rebuilt = DirectorProposal(
        id=proposal.id,
        organization=other_organization,
        proposal_type=proposal.proposal_type,
        status=proposal.status,
        priority=proposal.priority,
        title_zh=proposal.title_zh,
        summary_zh=proposal.summary_zh,
        reason_snapshot=proposal.reason_snapshot,
        action_reference=proposal.action_reference,
        expires_at=proposal.expires_at,
        version=proposal.version,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )
    with pytest.raises(ValidationError, match="immutable"):
        rebuilt.save(force_update=True)

    with pytest.raises(ValidationError, match="immutable"):
        DirectorProposal.objects.filter(pk=proposal.pk).update(organization=other_organization)

    bulk_updated = DirectorProposal.objects.get(pk=proposal.pk)
    bulk_updated.organization = other_organization
    with pytest.raises(ValidationError, match="immutable"):
        DirectorProposal.objects.bulk_update([bulk_updated], ["organization"])

    with pytest.raises(ValidationError, match="upserts"):
        DirectorProposal.objects.bulk_create(
            [DirectorProposal(id=proposal.id, organization=other_organization)],
            update_conflicts=True,
            update_fields=["organization"],
            unique_fields=["id"],
        )


@pytest.mark.django_db
def test_decision_history_rejects_all_public_orm_mutation_paths(proposal, user):
    decision = DirectorDecision.objects.create(
        proposal=proposal,
        organization=proposal.organization,
        action=DirectorDecision.Action.APPROVE,
        proposal_version=proposal.version,
        actor=user,
    )

    rebuilt = DirectorDecision(
        id=decision.id,
        proposal=proposal,
        organization=proposal.organization,
        action=DirectorDecision.Action.REJECT,
        proposal_version=proposal.version,
        actor=user,
        comment="Forged replacement",
        created_at=decision.created_at,
    )
    with pytest.raises(ValidationError, match="append-only"):
        rebuilt.save(force_update=True)
    with pytest.raises(ValidationError, match="append-only"):
        DirectorDecision.objects.filter(pk=decision.pk).update(comment="Forged update")
    with pytest.raises(ValidationError, match="append-only"):
        DirectorDecision.objects.bulk_update([decision], ["comment"])
    with pytest.raises(ValidationError, match="upserts"):
        DirectorDecision.objects.bulk_create(
            [rebuilt],
            update_conflicts=True,
            update_fields=["comment"],
            unique_fields=["id"],
        )


@pytest.mark.django_db
def test_decision_must_belong_to_proposal_organization(proposal, other_organization, user):
    with pytest.raises(ValidationError, match="organization"):
        DirectorDecision.objects.create(
            proposal=proposal,
            organization=other_organization,
            action=DirectorDecision.Action.APPROVE,
            proposal_version=proposal.version,
            actor=user,
        )

    decision = DirectorDecision.objects.create(
        proposal=proposal,
        organization=proposal.organization,
        action=DirectorDecision.Action.APPROVE,
        proposal_version=proposal.version,
        actor=user,
    )
    assert decision.organization_id == proposal.organization_id


@pytest.mark.django_db
def test_decision_bulk_create_rejects_foreign_organization(proposal, other_organization, user):
    with pytest.raises(ValidationError, match="organization"):
        DirectorDecision.objects.bulk_create(
            [
                DirectorDecision(
                    proposal=proposal,
                    organization=other_organization,
                    action=DirectorDecision.Action.APPROVE,
                    proposal_version=proposal.version,
                    actor=user,
                )
            ]
        )


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


@pytest.mark.django_db(transaction=True)
def test_director_permission_migration_augments_builtin_roles_only():
    before = ("identity", "0011_refresh_phase_b1_permissions")
    after = ("identity", "0012_refresh_director_permissions")
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    original_permissions = {
        "ADMINISTRATOR": ["custom.administrator", "existing.shared"],
        "OPERATOR": ["custom.operator", "existing.shared"],
        "REVIEWER": ["custom.reviewer", "existing.shared"],
        "READ_ONLY": ["custom.read_only", "existing.shared"],
    }
    expected_added = {
        "ADMINISTRATOR": {"director.read", "director.decide"},
        "OPERATOR": {"director.read", "director.decide"},
        "REVIEWER": {"director.read", "director.decide"},
        "READ_ONLY": {"director.read"},
    }

    try:
        executor.migrate([before])
        old_role_model = executor.loader.project_state([before]).apps.get_model("identity", "Role")
        for code, permissions in original_permissions.items():
            old_role_model.objects.create(name=code, code=code, permissions=permissions)
        old_role_model.objects.create(
            name="Custom", code="CUSTOM", permissions=["custom.role", "existing.shared"]
        )

        executor = MigrationExecutor(connection)
        executor.migrate([after])
        role_model = executor.loader.project_state([after]).apps.get_model("identity", "Role")
        for code, permissions in original_permissions.items():
            assert set(role_model.objects.get(code=code).permissions) == set(permissions) | expected_added[code]
        assert role_model.objects.get(code="CUSTOM").permissions == ["custom.role", "existing.shared"]
    finally:
        MigrationExecutor(connection).migrate(latest)
