import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from django.db import transaction

from apps.common.tenant_tasks import (
    TenantTaskError,
    TenantWorkResult,
    dispatch_task_on_commit,
    parse_tenant_organization_id,
    run_tenant_coordinator,
    tenant_task_context,
)
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService


@pytest.mark.parametrize(
    "value",
    [None, "", " ", " not-a-uuid ", 1, True, [], {}],
)
def test_tenant_task_organization_id_requires_a_clean_uuid_string(value):
    with pytest.raises(TenantTaskError, match="organization_id"):
        parse_tenant_organization_id(value)

    expected = UUID("10000000-0000-4000-8000-000000000001")
    assert parse_tenant_organization_id(str(expected)) == expected


@pytest.mark.django_db(transaction=True)
def test_tenant_task_context_clears_after_success_and_exception():
    first = uuid4()
    second = uuid4()

    with tenant_task_context(str(first)) as organization_id:
        assert organization_id == first
        with tenant_task_context(str(first)):
            pass

    with pytest.raises(RuntimeError, match="task failed"):
        with tenant_task_context(str(first)):
            raise RuntimeError("task failed")

    with tenant_task_context(str(second)) as organization_id:
        assert organization_id == second


@pytest.mark.django_db(transaction=True)
def test_dispatch_task_on_commit_skips_rollback_and_binds_arguments_once():
    calls = []
    task = SimpleNamespace(delay=lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(RuntimeError, match="rollback"):
        with transaction.atomic():
            dispatch_task_on_commit(task, "org-a", "object-a", reason="retry")
            raise RuntimeError("rollback")
    assert calls == []

    with transaction.atomic():
        dispatch_task_on_commit(task, "org-b", "object-b", reason="commit")
        assert calls == []
    assert calls == [(('org-b', 'object-b'), {'reason': 'commit'})]


@pytest.mark.django_db
def test_tenant_object_lookup_does_not_reveal_another_organization_object():
    from apps.assets.tasks import run_asset_understanding

    own = Organization.objects.create(name="Own", slug=f"own-{uuid4()}")
    other = Organization.objects.create(name="Other", slug=f"other-{uuid4()}")
    foreign_job = JobService.create(
        organization=other,
        job_type=Job.Type.ASSET_UNDERSTAND,
        input_snapshot={"asset_id": str(uuid4())},
    )

    with pytest.raises(TenantTaskError, match="unavailable"):
        run_asset_understanding.run(str(own.id), str(foreign_job.id))


@pytest.mark.django_db(transaction=True)
def test_coordinator_materializes_stable_organizations_and_isolates_contexts():
    organizations = [
        Organization.objects.create(name=f"Org {index}", slug=f"org-{uuid4()}")
        for index in range(3)
    ]
    seen = []

    def operation(organization_id, remaining):
        assert remaining is None
        with tenant_task_context(str(organization_id)):
            seen.append(organization_id)
        return TenantWorkResult(consumed=1, counters={"processed": 1})

    result = run_tenant_coordinator(operation)

    assert seen == sorted((item.id for item in organizations), key=str)
    assert result == {"organizations": 3, "consumed": 3, "processed": 3}
    with tenant_task_context(str(uuid4())):
        pass


@pytest.mark.django_db(transaction=True)
def test_coordinator_limit_is_global_instead_of_per_organization():
    for index in range(3):
        Organization.objects.create(name=f"Limit {index}", slug=f"limit-{uuid4()}")
    received_limits = []

    def operation(_organization_id, remaining):
        received_limits.append(remaining)
        consumed = min(2, remaining)
        return TenantWorkResult(consumed=consumed, counters={"processed": consumed})

    result = run_tenant_coordinator(operation, limit=3)

    assert received_limits == [3, 1]
    assert result == {"organizations": 2, "consumed": 3, "processed": 3}


def test_object_tasks_and_every_production_dispatch_use_organization_id_first():
    from apps.assets.tasks import run_asset_understanding
    from apps.content.tasks import (
        generate_content_recommendations_job,
        generate_master_content_job,
        generate_platform_variants_job,
    )
    from apps.growth.tasks import (
        execute_growth_publish_item,
        run_proactive_acquisition_task,
        sync_growth_publish_item_from_task,
    )
    from apps.jobs.tasks import execute_ai_job
    from apps.publishing.tasks import (
        reconcile_buffer_publish_task_job,
        run_publish_task,
    )

    task_arg_counts = {
        "execute_ai_job": (execute_ai_job, 3, 0),
        "run_asset_understanding": (run_asset_understanding, 2, 2),
        "generate_master_content_job": (generate_master_content_job, 3, 2),
        "generate_platform_variants_job": (generate_platform_variants_job, 2, 2),
        "generate_content_recommendations_job": (
            generate_content_recommendations_job,
            3,
            1,
        ),
        "execute_growth_publish_item": (execute_growth_publish_item, 2, 2),
        "sync_growth_publish_item_from_task": (
            sync_growth_publish_item_from_task,
            2,
            1,
        ),
        "run_publish_task": (run_publish_task, 2, 4),
        "reconcile_buffer_publish_task_job": (
            reconcile_buffer_publish_task_job,
            2,
            1,
        ),
        "run_proactive_acquisition_task": (
            run_proactive_acquisition_task,
            2,
            0,
        ),
    }
    for task, _minimum_args, _dispatch_count in task_arg_counts.values():
        assert next(iter(inspect.signature(task.run).parameters)) == "organization_id"

    backend = Path(__file__).resolve().parents[3]
    found = {name: 0 for name in task_arg_counts}
    for path in (backend / "apps").rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            args = node.args
            if isinstance(node.func, ast.Attribute):
                if node.func.attr not in {"delay", "apply_async", "s", "si"}:
                    continue
                owner = node.func.value
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id == "dispatch_task_on_commit"
                and node.args
            ):
                owner = node.args[0]
                args = node.args[1:]
            else:
                continue
            if not isinstance(owner, ast.Name) or owner.id not in task_arg_counts:
                continue
            _task, minimum_args, _dispatch_count = task_arg_counts[owner.id]
            assert len(args) >= minimum_args
            found[owner.id] += 1
    assert found == {
        name: dispatch_count
        for name, (_task, _minimum_args, dispatch_count) in task_arg_counts.items()
    }
