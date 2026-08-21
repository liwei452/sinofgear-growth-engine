# Developer verification workflow

## Audit summary

The repository currently has these verification layers:

| Layer | Existing command | Current use |
| --- | --- | --- |
| Backend lint | `ruff check apps integrations config` | Every backend CI run |
| Backend tests | `python -m pytest -q` | Every backend CI run; recent PRs report 1,677–1,682 tests |
| Django checks | `python manage.py check --settings=config.test_settings` | Every backend CI run |
| Migration drift | `python manage.py makemigrations --check --dry-run --settings=config.test_settings` | Every backend CI run and often local PR verification |
| OpenAPI validation | `python manage.py spectacular --settings=config.test_settings --validate` | Every backend CI run; also performed while generating the frontend artifact |
| API artifact | `pnpm api:check` / `pnpm api:generate` | Every frontend CI run and often local PR verification |
| Frontend unit tests | `pnpm test -- --run` | Every frontend CI run |
| Type checking | `pnpm typecheck` | Every frontend CI run and often local PR verification |
| Frontend lint | `pnpm lint` | Every frontend CI run |
| Production build | `pnpm build` | Every frontend CI run and often local PR verification |
| Browser E2E | `pnpm test:e2e [Playwright arguments]` | Run manually for affected flows; not currently in CI |
| Patch hygiene | `git diff --check` | Used manually, but not provided through one repository command |

Pytest configuration lives in `backend/pyproject.toml` and uses Django test settings. Backend tests are colocated under 15 `backend/apps/*/tests` directories, three integration test directories, `backend/config/tests`, and `backend/tests` (196 Python test files at this baseline). Vitest is configured in `frontend/vite.config.ts`; 42 unit-test files are colocated with frontend modules and shared code. Playwright has nine specs under `frontend/e2e` and runs through a cross-platform Node launcher that owns its temporary database, services, browser output, and cleanup.

Recent PR evidence shows the repetition clearly: PRs #1, #2, and #3 each had two pull-request CI runs, and every run repeated the complete backend and frontend jobs. PR descriptions also record repeated local full-suite checks. For example, PR #1 records the 1,677-test backend suite plus a 201-test publishing subset, while PR #2 records focused UI tests, all frontend tests, the 1,682-test backend suite, E2E, lint, type checking, API checking, and build. The checks are valuable; the inefficient part is running the full layers after each small edit instead of once at the PR gate.

## Change-aware local selection

`python scripts/verify.py quick` is the edit-loop entry point. It always runs `git diff --check`, then selects the smallest safe set from centralized rules:

| Change | Quick verification |
| --- | --- |
| Ordinary Python in `backend/apps/<app>` or an integration package | Ruff on changed Python files; the changed test itself, a directly named test file, or the package test directory |
| Model or migration | Owning app tests plus migration drift |
| Serializer, view, URL, or OpenAPI code | Owning API/schema tests plus `api:check` |
| Vue or TypeScript module code | Direct/same-module Vitest files plus `vue-tsc` |
| Generated frontend schema | `api:check` plus `vue-tsc` |
| Build config, dependency manifests, Django settings, shared backend infrastructure, app shell/router, shared frontend code | Expand to the corresponding complete backend or frontend module verification |
| E2E spec or mapped main-flow page | Only the related Playwright spec(s) |
| Documentation or screenshots only | `git diff --check`; no backend or frontend suite |
| Unrecognized production code | Fail safe by expanding to the relevant complete backend/frontend verification; never report “no tests needed” |

Use `--base <revision>` to include committed work in a batch. Without `--base`, quick mode compares the working tree, index, and untracked files with `HEAD`.
Documentation-only selection is restricted to `docs/` and known root documentation files such as `README.md`; an unfamiliar root `.txt`, dependency file, or configuration file expands to complete verification instead of being guessed to be documentation.

## Layered developer use

- During a small edit loop, run `python scripts/verify.py quick`.
- At the end of a backend, frontend, or API batch, run the matching `backend`, `frontend`, or `api` mode.
- Use `quick --dry-run` to review selection without executing subprocesses.
- Do not repeatedly run `full` locally. The Draft PR runs the complete protected checks once for the newest commit.

The complete gate remains fail closed: full backend pytest, full Ruff, Django checks, migration drift, OpenAPI/API artifact validation, full Vitest, `vue-tsc`, ESLint, production build, and Playwright E2E. A command failure is returned unchanged. Selection errors, Git errors, missing mappings for production code, stale generated artifacts, migration drift, and unrecognized production paths must broaden verification or fail; they must not silently skip checks.

The path policy is data-driven in `scripts/verification_rules.py`; command execution and Git discovery live in `scripts/verify.py`. Add or change mappings in the rule module instead of growing per-feature command branches in the CLI.

## Commands on Windows PowerShell

Run from the repository or worktree root with an activated Python 3.12 environment:

```powershell
python scripts/verify.py quick
python scripts/verify.py quick --dry-run
python scripts/verify.py quick --base origin/merge/consolidation-security
python scripts/verify.py quick --base origin/feature/database-rls-phase2
python scripts/verify.py backend
python scripts/verify.py frontend
python scripts/verify.py api
python scripts/verify.py e2e
python scripts/verify.py full --dry-run
```

If the backend virtual environment is not activated, call it explicitly:

```powershell
.\backend\.venv\Scripts\python.exe scripts\verify.py quick --dry-run
```

The runner invokes argument arrays directly and uses `pnpm.cmd` on Windows; it does not invoke Bash or interpolate a shell command. `--dry-run` performs Git discovery and prints the plan, but runs none of the selected verification subprocesses. A real run stops on the first failed check and returns that check's exit code. It prints check names, targets, and reasons only—not tokens, connection strings, API keys, secrets, or environment dumps.

## Mode checklist

| Mode | Checks |
| --- | --- |
| `quick` | `git diff --check` plus the change-selected Ruff, pytest, migration, API, Vitest, typecheck, or E2E checks |
| `backend` | `git diff --check`; full Ruff; full pytest; Django system check; migration drift; OpenAPI validation |
| `frontend` | `git diff --check`; API artifact check; full Vitest; `vue-tsc`; ESLint; production build |
| `api` | `git diff --check`; API artifact check; `vue-tsc` |
| `e2e` | `git diff --check`; all repository Playwright specs through the owned launcher |
| `full` | The union of backend, frontend, API, and E2E checks, with each check executed once |

`api:generate` is intentionally not run by verification because it changes a committed artifact. A stale artifact fails closed in `api:check`; the developer explicitly runs `pnpm api:generate`, reviews the generated diff, and then verifies again.

## CI policy

Pull-request CI keeps the existing backend and frontend quality gates and adds the repository E2E gate. Workflow concurrency cancels an older in-progress run for the same PR when a new commit arrives. The existing pnpm cache remains enabled and Python dependency caching is added. No test condition, skip marker, business behavior, or protected assertion is changed.

Before this change, every PR commit started two complete jobs with no concurrency cancellation; backend dependencies were downloaded without the setup-python pip cache, and E2E remained a manual final step. After this change, only the newest commit for a PR continues running. Backend and frontend remain independent complete jobs, both dependency ecosystems use lock/config-keyed caches, and a third fixture-only browser job runs the existing owned E2E launcher. This reduces superseded work while increasing—not reducing—the final PR gate.
