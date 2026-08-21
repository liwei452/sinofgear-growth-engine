# Change-aware Verification Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one cross-platform, fail-closed verification entry point that keeps local edit loops targeted while preserving every final PR gate.

**Architecture:** `scripts/verification_rules.py` holds declarative path and command mappings; `scripts/verify.py` handles Git discovery, plan rendering, and subprocess execution. The selector returns immutable check objects so tests can verify behavior without running tools. GitHub Actions calls stable modes from the same entry point and uses per-PR concurrency cancellation.

**Tech Stack:** Python 3.12 standard library, pytest parameterization, Git, Ruff, Django, pnpm, Vitest, vue-tsc, ESLint, Vite, Playwright, GitHub Actions.

**Spec:** `docs/developer-verification-workflow.md`

## Global Constraints

- Work only on `feature/verification-workflow` in `.worktrees/verification-workflow`, based on `ea7e66a1a108e8f2279ad72f115bf4cce294d5e5`.
- Do not modify business models, business logic, RLS policy, Buffer/Publishing state machines, or Knowledge Context.
- Do not remove tests, add skips, call real external APIs, publish, rebase, force-push, mark the PR ready, or merge it.
- Keep local execution to the new script's focused tests, Ruff/format hygiene, and dry runs; leave full execution to Draft PR CI.
- Preserve subprocess exit codes and never print secrets or complete environment data.

---

### Task 1: Declarative selector and cross-platform runner

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/verification_rules.py`
- Create: `scripts/verify.py`
- Create: `scripts/tests/test_verify.py`

**Interfaces:**
- `normalize_path(path: str | Path) -> str` returns a repository-relative POSIX path.
- `select_checks(changed_files: Sequence[str]) -> VerificationPlan` returns ordered, deduplicated checks plus human-readable reasons.
- `discover_changed_files(repo_root: Path, base: str | None) -> list[str]` combines Git diff output with untracked files.
- `run_plan(plan: VerificationPlan, dry_run: bool, runner: Callable[..., CompletedProcess]) -> int` stops on the first failure and returns that exact exit code.
- `main(argv: Sequence[str] | None = None) -> int` provides `quick`, `backend`, `frontend`, `api`, `e2e`, and `full` modes.

- [ ] **Step 1: Write selector tests before implementation**

  Add 10–15 parameterized cases covering ordinary backend files, exact changed tests, models/migrations, API files, Vue/TS files, generated schema, global config expansion, docs/images, unknown backend/frontend production paths, and Windows separators. Expected values must be literal check IDs and targets.

- [ ] **Step 2: Verify the selector tests fail for the missing module**

  Run `python -m pytest scripts/tests/test_verify.py -q` from the repository root and confirm collection fails because `scripts.verify` does not exist.

- [ ] **Step 3: Implement centralized rules and selection**

  Store backend package patterns, API filename roles, frontend module/E2E mappings, global expansion paths, documentation extensions, and command definitions as data in `verification_rules.py`. Implement generic pattern evaluation in `verify.py`; any unmatched production path must select its side's full verification.

- [ ] **Step 4: Verify selector tests pass**

  Run `python -m pytest scripts/tests/test_verify.py -q` and confirm every mapping case passes.

- [ ] **Step 5: Add execution behavior tests before implementation**

  Add tests proving `--dry-run` invokes no subprocess, a failing command returns its nonzero status unchanged and stops later checks, Git output normalizes Windows paths, and the summary contains changed-file count, selected checks, and reasons without environment output.

- [ ] **Step 6: Verify the execution tests fail for missing behavior**

  Run the focused test file and confirm failures name the unimplemented execution behavior.

- [ ] **Step 7: Implement discovery, execution, modes, and summary**

  Use `subprocess.run` argument lists with explicit working directories; never invoke Bash or a shell. Use the current Python interpreter for Python/Django commands and `pnpm.cmd` on Windows. Catch only selection/Git/launch errors that need a safe diagnostic; otherwise propagate the real process status.

- [ ] **Step 8: Verify focused tests and Ruff**

  Run `python -m pytest scripts/tests/test_verify.py -q` and Ruff only on the new Python files.

- [ ] **Step 9: Commit the runner**

  Stage only the four runner/test paths and commit as `feat(dev): add change-aware verification runner`.

### Task 2: Pull-request CI orchestration

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Backend job calls `python scripts/verify.py backend`.
- Frontend job calls `python scripts/verify.py frontend` after backend and frontend dependency setup.
- E2E job calls `python scripts/verify.py e2e` with a repository-owned virtual environment and installed Chromium.

- [ ] **Step 1: Update CI without conditional test suppression**

  Add workflow-level concurrency keyed by workflow and PR/branch; preserve pull-request triggering. Keep the existing protected commands through the runner modes, retain pnpm caching, add pip caching, and add the E2E job with isolated local services and fixture mode only.

- [ ] **Step 2: Validate configuration and dry-run modes**

  Parse `.github/workflows/ci.yml`, inspect the resulting diff for concurrency/cache/job preservation, and run the focused tests plus `python scripts/verify.py backend --dry-run`, `frontend --dry-run`, `api --dry-run`, `e2e --dry-run`, and `full --dry-run`. Confirm full contains every existing gate and E2E exactly once. GitHub Actions provides the final behavior-level workflow validation in the Draft PR.

- [ ] **Step 3: Commit CI**

  Stage only `.github/workflows/ci.yml` and any CI-specific test adjustment, then commit as `ci: streamline pull request verification`.

### Task 3: Developer documentation and release verification

**Files:**
- Modify: `docs/developer-verification-workflow.md`
- Add: `docs/superpowers/plans/2026-08-22-verification-workflow.md`

**Interfaces:**
- Documentation lists exact PowerShell commands, quick mappings, full checks, fail-closed behavior, and local-versus-CI policy.

- [ ] **Step 1: Reconcile documentation with implemented command output**

  Replace any audit-time wording that differs from the implemented modes, and include PowerShell examples from repository root and worktree root.

- [ ] **Step 2: Run only authorized local verification**

  Run focused script tests, Ruff on changed Python, every mode with `--dry-run`, and `git diff --check`. Do not run the complete backend, frontend, build, or E2E suites locally.

- [ ] **Step 3: Audit protected boundaries and repository diff**

  Confirm the diff contains no business model/logic, RLS, publishing state-machine, Knowledge Context, deleted tests, or skip markers. Confirm `git status --short` contains only intended paths.

- [ ] **Step 4: Commit documentation**

  Stage only the two documentation paths and commit as `docs: document layered verification workflow`.

- [ ] **Step 5: Publish Draft PR safely**

  Fetch `origin/feature/database-rls-phase2`; if it advanced, merge it normally and resolve only workflow/doc conflicts. Push `feature/verification-workflow` without force, reuse an existing matching PR if present, otherwise create a Draft PR with base `feature/database-rls-phase2`.

- [ ] **Step 6: Wait for final CI evidence**

  Observe the latest Draft PR run until backend, frontend, and E2E complete. Report exact conclusions and links; if a gate fails, diagnose and fix through the same focused workflow before a normal push.
