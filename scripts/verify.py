#!/usr/bin/env python3
"""Cross-platform, change-aware verification entry point."""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verification_rules import (
    API_CHECKS,
    API_FILE_NAMES,
    API_TEST_PATTERNS,
    BACKEND_CHECKS,
    BACKEND_GLOBAL_PREFIXES,
    BACKEND_GLOBAL_PATTERNS,
    CHECK_LABELS,
    CHECK_ORDER,
    DOCUMENT_PREFIXES,
    DOCUMENT_SUFFIXES,
    E2E_BY_FRONTEND_MODULE,
    E2E_MAIN_CHAIN_SUFFIXES,
    FRONTEND_CHECKS,
    FRONTEND_GLOBAL_PATTERNS,
    FRONTEND_GLOBAL_PREFIXES,
    FRONTEND_SOURCE_SUFFIXES,
    FRONTEND_TEST_PATTERNS,
    MODEL_FILE_NAMES,
    PRODUCTION_PREFIXES,
    ROOT_GLOBAL_FILES,
    ROOT_GLOBAL_PREFIXES,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    identifier: str
    label: str
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationPlan:
    checks: tuple[Check, ...]
    reasons: tuple[str, ...]
    base: str | None = None

    @property
    def check_ids(self) -> tuple[str, ...]:
        return tuple(check.identifier for check in self.checks)

    def targets_for(self, identifier: str) -> tuple[str, ...]:
        return next((check.targets for check in self.checks if check.identifier == identifier), ())


@dataclass
class _PlanBuilder:
    targets: dict[str, set[str] | None] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def add(self, identifier: str, *targets: str) -> None:
        existing = self.targets.get(identifier)
        if identifier in self.targets and existing is None:
            return
        if not targets:
            self.targets[identifier] = None
            return
        normalized = {normalize_path(target) for target in targets}
        if existing is None and identifier not in self.targets:
            self.targets[identifier] = normalized
        elif existing is not None:
            existing.update(normalized)

    def add_many(self, identifiers: Sequence[str]) -> None:
        for identifier in identifiers:
            self.add(identifier)

    def reason(self, message: str) -> None:
        if message not in self.reasons:
            self.reasons.append(message)

    def build(self, *, base: str | None = None) -> VerificationPlan:
        checks = []
        for identifier in CHECK_ORDER:
            if identifier not in self.targets:
                continue
            raw_targets = self.targets[identifier]
            targets = () if raw_targets is None else tuple(sorted(raw_targets))
            checks.append(Check(identifier, CHECK_LABELS[identifier], targets))
        return VerificationPlan(tuple(checks), tuple(self.reasons), base)


def normalize_path(path: str | Path) -> str:
    value = str(path).replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return PurePosixPath(value).as_posix()


def _matches(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _is_document(path: str) -> bool:
    if path.startswith(DOCUMENT_PREFIXES):
        return True
    return not path.startswith(PRODUCTION_PREFIXES) and path.lower().endswith(DOCUMENT_SUFFIXES)


def _existing_globs(repo_root: Path, directory: str, patterns: Sequence[str]) -> tuple[str, ...]:
    root = repo_root / Path(directory)
    matches = {
        normalize_path(path.relative_to(repo_root))
        for pattern in patterns
        for path in root.glob(pattern)
        if path.is_file()
    }
    return tuple(sorted(matches))


def _backend_package(path: str) -> tuple[str, str] | None:
    parts = path.split("/")
    if len(parts) >= 4 and parts[:2] == ["backend", "apps"]:
        return parts[2], f"backend/apps/{parts[2]}"
    if len(parts) >= 4 and parts[:2] == ["backend", "integrations"]:
        return parts[2], f"backend/integrations/{parts[2]}"
    if len(parts) >= 3 and parts[:2] == ["backend", "config"]:
        return "config", "backend/config"
    return None


def _add_backend_full(builder: _PlanBuilder, reason: str) -> None:
    builder.add_many(BACKEND_CHECKS)
    builder.reason(reason)


def _add_frontend_full(builder: _PlanBuilder, reason: str) -> None:
    builder.add_many(FRONTEND_CHECKS)
    builder.reason(reason)


def _select_backend(path: str, repo_root: Path, builder: _PlanBuilder) -> None:
    if path in BACKEND_GLOBAL_PATTERNS:
        _add_backend_full(builder, f"Global backend configuration changed: {path}")
        return
    if not path.endswith(".py"):
        _add_backend_full(builder, f"Unrecognized backend production path expanded safely: {path}")
        return

    builder.add("ruff", path)
    if path.startswith("backend/tests/test_"):
        builder.add("pytest", path)
        builder.reason(f"Changed backend test must run directly: {path}")
        return
    if path.startswith(BACKEND_GLOBAL_PREFIXES) and "/tests/test_" not in path:
        _add_backend_full(builder, f"Shared backend infrastructure changed: {path}")
        return
    package = _backend_package(path)
    if package is None:
        _add_backend_full(builder, f"Unrecognized backend Python path expanded safely: {path}")
        return

    package_name, package_root = package
    filename = path.rsplit("/", 1)[-1]
    tests_root = f"{package_root}/tests"
    if "/tests/test_" in path or path.startswith("backend/tests/test_"):
        builder.add("pytest", path)
        builder.reason(f"Changed backend test must run directly: {path}")
        return

    is_model_change = filename in MODEL_FILE_NAMES or "/migrations/" in path
    is_api_change = filename in API_FILE_NAMES
    if is_model_change:
        builder.add("pytest", tests_root)
        builder.add("migration-drift")
        builder.reason(f"{package_name} model or migration changed")
        return
    if is_api_change:
        api_tests = _existing_globs(repo_root, tests_root, API_TEST_PATTERNS)
        builder.add("pytest", *(api_tests or (tests_root,)))
        builder.add("api-check")
        builder.reason(f"{package_name} API surface changed")
        return

    direct_pattern = f"test_{Path(filename).stem}.py"
    direct_tests = _existing_globs(repo_root, tests_root, (direct_pattern,))
    builder.add("pytest", *(direct_tests or (tests_root,)))
    builder.reason(f"{package_name} backend code and its direct tests changed")


def _frontend_module(path: str) -> tuple[str, str] | None:
    parts = path.split("/")
    if len(parts) >= 5 and parts[:3] == ["frontend", "src", "modules"]:
        return parts[3], "/".join(parts[:4])
    return None


def _select_frontend(path: str, repo_root: Path, builder: _PlanBuilder) -> None:
    if path == "frontend/src/api/generated/schema.ts":
        builder.add_many(API_CHECKS)
        builder.reason("Generated API schema changed")
        return
    if path.startswith("frontend/e2e/") and path.endswith(".spec.ts"):
        builder.add("e2e", path)
        builder.reason(f"Changed E2E spec must run directly: {path}")
        return
    if path in FRONTEND_GLOBAL_PATTERNS or path.startswith(FRONTEND_GLOBAL_PREFIXES):
        _add_frontend_full(builder, f"Global frontend configuration or shared code changed: {path}")
        if path == "frontend/playwright.config.ts":
            builder.add("e2e")
        return
    if not path.endswith(FRONTEND_SOURCE_SUFFIXES):
        _add_frontend_full(builder, f"Unrecognized frontend production path expanded safely: {path}")
        return

    module = _frontend_module(path)
    if module is None:
        _add_frontend_full(builder, f"Unrecognized frontend source path expanded safely: {path}")
        return
    module_name, module_root = module
    if ".test." in path:
        builder.add("vitest", path)
    else:
        stem = Path(path).stem
        direct_tests = _existing_globs(repo_root, str(PurePosixPath(path).parent), (f"{stem}.test.*",))
        module_tests = _existing_globs(repo_root, module_root, FRONTEND_TEST_PATTERNS)
        builder.add("vitest", *(direct_tests or module_tests or (module_root,)))
    builder.add("typecheck")
    builder.reason(f"{module_name} frontend code and its direct Vitest coverage changed")

    if path.endswith(E2E_MAIN_CHAIN_SUFFIXES):
        specs = E2E_BY_FRONTEND_MODULE.get(module_name, ())
        if specs:
            builder.add("e2e", *(f"frontend/e2e/{spec}" for spec in specs))


def select_checks(
    changed_files: Sequence[str],
    *,
    repo_root: Path = REPOSITORY_ROOT,
    base: str | None = None,
) -> VerificationPlan:
    builder = _PlanBuilder()
    builder.add("diff")
    normalized_files = tuple(dict.fromkeys(normalize_path(path) for path in changed_files))
    for path in normalized_files:
        if _is_document(path):
            builder.reason("Documentation or screenshots changed")
        elif path.startswith("backend/"):
            _select_backend(path, repo_root, builder)
        elif path.startswith("frontend/"):
            _select_frontend(path, repo_root, builder)
        elif path.startswith("scripts/") and path.endswith(".py"):
            builder.add("ruff", path)
            builder.add("pytest", "scripts/tests")
            builder.reason("Verification tooling changed")
        elif path in ROOT_GLOBAL_FILES or path.startswith(ROOT_GLOBAL_PREFIXES):
            _add_backend_full(builder, f"Repository-wide configuration changed: {path}")
            _add_frontend_full(builder, f"Repository-wide configuration changed: {path}")
            if path.startswith(".github/workflows/"):
                builder.add("e2e")
        else:
            _add_backend_full(builder, f"Unrecognized production path expanded safely: {path}")
            _add_frontend_full(builder, f"Unrecognized production path expanded safely: {path}")
    if not normalized_files:
        builder.reason("No changed files detected")
    return builder.build(base=base)


def plan_for_mode(mode: str, *, repo_root: Path = REPOSITORY_ROOT, base: str | None = None) -> VerificationPlan:
    del repo_root
    builder = _PlanBuilder()
    builder.add("diff")
    if mode == "backend":
        builder.add_many(BACKEND_CHECKS)
        builder.reason("Complete backend verification requested")
    elif mode == "frontend":
        builder.add_many(FRONTEND_CHECKS)
        builder.reason("Complete frontend verification requested")
    elif mode == "api":
        builder.add_many(API_CHECKS)
        builder.reason("API artifact verification requested")
    elif mode == "e2e":
        builder.add("e2e")
        builder.reason("Complete E2E verification requested")
    elif mode == "full":
        builder.add_many(BACKEND_CHECKS)
        builder.add_many(FRONTEND_CHECKS)
        builder.add("e2e")
        builder.reason("Complete final verification requested")
    else:
        raise ValueError(f"Unknown verification mode: {mode}")
    return builder.build(base=base)


def _git_paths(repo_root: Path, arguments: Sequence[str]) -> list[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=False,
    )
    if result.returncode:
        diagnostic = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(diagnostic or f"Git exited with {result.returncode}")
    return [normalize_path(item.decode(errors="surrogateescape")) for item in result.stdout.split(b"\0") if item]


def discover_changed_files(repo_root: Path, base: str | None) -> list[str]:
    comparison = base or "HEAD"
    tracked = _git_paths(repo_root, ("diff", "--name-only", "--diff-filter=ACMRD", "-z", comparison, "--"))
    untracked = _git_paths(repo_root, ("ls-files", "--others", "--exclude-standard", "-z"))
    return list(dict.fromkeys([*tracked, *untracked]))


def _relative_targets(check: Check, prefix: str) -> list[str]:
    marker = f"{prefix}/"
    return [target[len(marker) :] if target.startswith(marker) else target for target in check.targets]


def _command_for(check: Check, plan: VerificationPlan) -> tuple[list[str], str]:
    python = sys.executable
    pnpm = "pnpm.cmd" if os.name == "nt" else "pnpm"
    if check.identifier == "diff":
        return ["git", "diff", "--check", plan.base or "HEAD", "--"], "."
    if check.identifier == "ruff":
        if check.targets:
            return [python, "-m", "ruff", "check", *check.targets], "."
        return [python, "-m", "ruff", "check", "apps", "integrations", "config"], "backend"
    if check.identifier == "pytest":
        if check.targets and any(target.startswith("scripts/") for target in check.targets):
            return [python, "-m", "pytest", "-q", "-c", "backend/pyproject.toml", *check.targets], "."
        return [python, "-m", "pytest", "-q", *_relative_targets(check, "backend")], "backend"
    if check.identifier == "django-check":
        return [python, "manage.py", "check", "--settings=config.test_settings"], "backend"
    if check.identifier == "migration-drift":
        return [
            python,
            "manage.py",
            "makemigrations",
            "--check",
            "--dry-run",
            "--settings=config.test_settings",
        ], "backend"
    if check.identifier == "openapi-validate":
        return [python, "manage.py", "spectacular", "--settings=config.test_settings", "--validate"], "backend"
    if check.identifier == "api-check":
        return [pnpm, "api:check"], "frontend"
    if check.identifier == "vitest":
        return [pnpm, "test", "--", "--run", *_relative_targets(check, "frontend")], "frontend"
    if check.identifier == "typecheck":
        return [pnpm, "typecheck"], "frontend"
    if check.identifier == "eslint":
        return [pnpm, "lint"], "frontend"
    if check.identifier == "build":
        return [pnpm, "build"], "frontend"
    if check.identifier == "e2e":
        return [pnpm, "test:e2e", *_relative_targets(check, "frontend")], "frontend"
    raise ValueError(f"No command registered for {check.identifier}")


def _selection_detail(check: Check) -> str:
    if check.targets:
        if check.identifier == "ruff":
            return f"{len(check.targets)} changed Python file(s)"
        return ", ".join(check.targets)
    return "complete"


def render_summary(plan: VerificationPlan, *, changed_count: int) -> str:
    lines = [f"Changed files: {changed_count}", "Selected checks:"]
    lines.extend(f"- {check.label}: {_selection_detail(check)}" for check in plan.checks)
    lines.append("Reason:")
    lines.extend(f"- {reason}" for reason in plan.reasons)
    return "\n".join(lines)


def run_plan(
    plan: VerificationPlan,
    *,
    repo_root: Path = REPOSITORY_ROOT,
    dry_run: bool,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    if dry_run:
        return 0
    for check in plan.checks:
        command, relative_cwd = _command_for(check, plan)
        print(f"Running: {check.label}", flush=True)
        try:
            result = runner(command, cwd=repo_root / relative_cwd, check=False)
        except OSError as error:
            print(f"Unable to start {check.label}: {error}", file=sys.stderr)
            return 127
        if result.returncode:
            return result.returncode
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("quick", "backend", "frontend", "api", "e2e", "full"))
    parser.add_argument("--base", help="Git revision used for changed files and patch hygiene")
    parser.add_argument("--dry-run", action="store_true", help="Print selection without running verification commands")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.mode == "quick":
            changed_files = discover_changed_files(REPOSITORY_ROOT, args.base)
            plan = select_checks(changed_files, repo_root=REPOSITORY_ROOT, base=args.base)
            changed_count = len(changed_files)
        else:
            plan = plan_for_mode(args.mode, repo_root=REPOSITORY_ROOT, base=args.base)
            changed_count = 0
        print(render_summary(plan, changed_count=changed_count))
        return run_plan(plan, repo_root=REPOSITORY_ROOT, dry_run=args.dry_run)
    except (RuntimeError, ValueError) as error:
        print(f"Verification selection failed closed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
