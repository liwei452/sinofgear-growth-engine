from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.verify import (
    Check,
    VerificationPlan,
    render_summary,
    run_plan,
    select_checks,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("changed_file", "expected_ids", "pytest_target", "vitest_target", "e2e_target"),
    [
        (
            "backend/apps/publishing/services.py",
            {"diff", "ruff", "pytest"},
            "backend/apps/publishing/tests",
            None,
            None,
        ),
        (
            "backend/tests/test_openapi.py",
            {"diff", "ruff", "pytest"},
            "backend/tests/test_openapi.py",
            None,
            None,
        ),
        (
            "backend/apps/catalog/models.py",
            {"diff", "ruff", "pytest", "migration-drift"},
            "backend/apps/catalog/tests",
            None,
            None,
        ),
        (
            "backend/apps/growth/serializers.py",
            {"diff", "ruff", "pytest", "api-check"},
            "backend/apps/growth/tests/test_agent_api.py",
            None,
            None,
        ),
        (
            "frontend/src/modules/products/ProductFormDialog.vue",
            {"diff", "vitest", "typecheck"},
            None,
            "frontend/src/modules/products/ProductFormDialog.test.ts",
            None,
        ),
        (
            "frontend/src/api/generated/schema.ts",
            {"diff", "api-check", "typecheck"},
            None,
            None,
            None,
        ),
        (
            "backend/config/settings.py",
            {"diff", "ruff", "pytest", "django-check", "migration-drift", "openapi-validate"},
            None,
            None,
            None,
        ),
        ("docs/verification.md", {"diff"}, None, None, None),
        (
            "backend/runtime/production.template",
            {"diff", "ruff", "pytest", "django-check", "migration-drift", "openapi-validate"},
            None,
            None,
            None,
        ),
        (
            "frontend/e2e/social-operations.spec.ts",
            {"diff", "e2e"},
            None,
            None,
            "frontend/e2e/social-operations.spec.ts",
        ),
        (
            r"backend\apps\knowledge\migrations\0001_initial.py",
            {"diff", "ruff", "pytest", "migration-drift"},
            "backend/apps/knowledge/tests",
            None,
            None,
        ),
    ],
)
def test_change_mapping_is_minimal_and_fail_closed(
    changed_file: str,
    expected_ids: set[str],
    pytest_target: str | None,
    vitest_target: str | None,
    e2e_target: str | None,
) -> None:
    plan = select_checks([changed_file], repo_root=REPOSITORY_ROOT)

    assert set(plan.check_ids) == expected_ids
    if pytest_target:
        assert pytest_target in plan.targets_for("pytest")
    if vitest_target:
        assert vitest_target in plan.targets_for("vitest")
    if e2e_target:
        assert e2e_target in plan.targets_for("e2e")

def test_full_mode_contains_every_final_gate_once() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify.py", "full", "--dry-run"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    for label in (
        "Patch hygiene",
        "Ruff",
        "Pytest",
        "Django system check",
        "Migration drift",
        "OpenAPI validation",
        "API artifact check",
        "Vitest",
        "vue-tsc",
        "ESLint",
        "Production build",
        "Playwright E2E",
    ):
        assert result.stdout.count(f"- {label}:") == 1


def test_dry_run_does_not_execute_selected_commands() -> None:
    calls: list[tuple[object, ...]] = []
    plan = VerificationPlan((Check("diff", "Patch hygiene"),), ("Documentation changed",))

    exit_code = run_plan(
        plan,
        repo_root=REPOSITORY_ROOT,
        dry_run=True,
        runner=lambda *args, **kwargs: calls.append(args),
    )

    assert exit_code == 0
    assert calls == []


def test_subcommand_failure_is_returned_unchanged_and_stops_execution() -> None:
    calls: list[list[str]] = []
    plan = VerificationPlan(
        (
            Check(
                "ruff",
                "Ruff",
                ("backend/apps/catalog/models.py", "scripts/verify.py"),
            ),
            Check("typecheck", "Typecheck"),
        ),
        ("Production code changed",),
    )

    def failing_runner(command, **kwargs):
        calls.append(command)
        assert kwargs["cwd"] == REPOSITORY_ROOT
        assert "backend/apps/catalog/models.py" in command
        assert "scripts/verify.py" in command
        return CompletedProcess(command, 17)

    exit_code = run_plan(plan, repo_root=REPOSITORY_ROOT, dry_run=False, runner=failing_runner)

    assert exit_code == 17
    assert len(calls) == 1


def test_summary_reports_selection_reasons_without_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://do-not-print")
    monkeypatch.setenv("API_KEY", "do-not-print")
    plan = select_checks(["docs/verification.md"], repo_root=REPOSITORY_ROOT)

    summary = render_summary(plan, changed_count=1)

    assert "Changed files: 1" in summary
    assert "Selected checks:" in summary
    assert "Patch hygiene" in summary
    assert "Reason:" in summary
    assert "Documentation or screenshots changed" in summary
    assert os.environ["DATABASE_URL"] not in summary
    assert os.environ["API_KEY"] not in summary
