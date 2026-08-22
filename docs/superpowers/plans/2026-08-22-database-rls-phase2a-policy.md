# Database RLS Phase 2A Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the global PromptVersion catalog runtime read-only, then enable PostgreSQL FORCE RLS for the exact 21 RLS-2A tables and verify it with the non-owner runtime role.

**Architecture:** Owner migrations seed immutable global prompt contracts and install frozen per-application RLS policies. Runtime code resolves prompts by stable purpose/code, records the actual provider/model on AIRun, and accesses tenant tables only inside transaction-local tenant contexts. A manifest audit remains the reviewable source of intended coverage while historical migrations keep their own frozen table and policy definitions.

**Tech Stack:** Django 5 migrations and management commands, PostgreSQL row-level security, psycopg, pytest, Ruff, Celery tenant transaction helpers.

**Spec:** `C:/Users/Administrator/.codex/attachments/fb419a77-1300-4e48-9ec0-2f321074ae1b/pasted-text.txt` and the preceding RLS-2A.2 task attachment.

## Global Constraints

- Work only on `feature/database-rls-phase2` in the existing linked worktree.
- Do not modify historical migrations or the 96-table manifest classification.
- Do not enter RLS-2B/RLS-2C, Identity control-plane tables, UI, OpenAPI, or generated schema.
- Runtime roles remain `NOINHERIT NOBYPASSRLS`; Web/Celery never use the owner role.
- Tenant context remains transaction-local via `set_config(..., true)` and missing context fails closed.
- No real LLM, Buffer, Google, email, or other external business API calls.
- Stage only explicit paths; never force push, merge the PR, or mark it ready.

---

### Task 1: Close the PromptVersion runtime write path

**Files:**
- Create: `backend/apps/ai/prompt_catalog.py`
- Create: `backend/apps/ai/migrations/0007_asset_understanding_prompt_catalog.py`
- Modify: `backend/apps/assets/understanding.py`
- Test: `backend/apps/ai/tests/test_prompt_catalog.py`
- Test: `backend/apps/assets/tests/test_asset_understanding_service.py`
- Test: `backend/apps/ai/tests/test_asset_prompt_migration.py`

**Interfaces:**
- Produces: `resolve_published_prompt(*, purpose: str, code: str) -> PromptVersion` and `PromptCatalogEntryMissing`.
- Produces catalog identity: purpose `ASSET_UNDERSTAND`, code `asset-understand-evidence-v1`.
- Consumes the existing fixed evidence-extraction template and `FACT_RESULT_SCHEMA` contract.

- [ ] Write failing tests proving provider/model-independent selection, fake/real contract reuse, fail-closed missing catalog entries, no runtime INSERT, no provider call on missing Prompt, and AIRun actual provider/model provenance.
- [ ] Run only the new catalog and directly affected Asset Understanding tests and confirm failures are caused by the current provider/model lookup and lazy create.
- [ ] Implement deterministic `PUBLISHED` lookup by purpose/code with `-version`, `-created_at`, `-id` ordering and a safe structured missing-entry exception.
- [ ] Add migration `ai/0007_asset_understanding_prompt_catalog.py` with frozen template/schema, neutral `provider='system'`, `model='provider-agnostic'`, next-purpose-version allocation, compatible-row reuse, conflict refusal, and noop reverse.
- [ ] Replace `_prompt()` lazy creation with catalog lookup before provider/storage network work; normalize missing catalog errors into the existing safe Asset Understanding failure surface.
- [ ] Verify repeated tasks do not add PromptVersion rows and AIRun retains actual provider/model while referencing the fixed catalog row.
- [ ] Commit explicit Prompt Catalog files as `fix(ai): make asset prompt catalog runtime read-only`.

### Task 2: Freeze and install the six application RLS migrations

**Files:**
- Create: `backend/apps/ai/migrations/0008_enable_phase2a_rls.py`
- Create: `backend/apps/assets/migrations/0004_enable_phase2a_rls.py`
- Create: `backend/apps/audit/migrations/0004_enable_phase2a_rls.py`
- Create: `backend/apps/catalog/migrations/0004_enable_phase2a_rls.py`
- Create: `backend/apps/jobs/migrations/0006_enable_phase2a_rls.py`
- Create: `backend/apps/platforms/migrations/0012_enable_phase2a_rls.py`
- Create: `backend/apps/common/tests/test_postgres_rls_phase2a.py`
- Modify: `backend/apps/common/tests/test_rls_manifest.py`

**Interfaces:**
- Direct policy expression: `organization_id = app_current_organization_id()` for 17 tenant-direct tables.
- Parent expression: `EXISTS (SELECT 1 FROM jobs_job parent WHERE parent.id = job_id AND parent.organization_id = app_current_organization_id())` for `jobs_jobattempt`.
- Global-read expression: `app_current_organization_id() IS NOT NULL` for `ai_promptversion`, `platforms_platform`, and `platforms_platformcapability`.

- [ ] Write failing PostgreSQL policy-shape and frozen-migration-set tests for the exact 17 direct, one parent, and three global tables.
- [ ] Add per-app PostgreSQL-only `RunPython` migrations, each depending on its current leaf plus `knowledge/0008_harden_knowledge_rls_context`; freeze all table names, policy names, and SQL in each migration.
- [ ] For each direct table enable and force RLS and create one stable `FOR ALL` policy with identical `USING` and `WITH CHECK` expressions.
- [ ] For JobAttempt enable and force RLS and create separate SELECT, INSERT, UPDATE, and DELETE policies using the parent expression.
- [ ] For global tables enable and force RLS and create only a SELECT policy using the non-null tenant-context expression.
- [ ] Implement reverse SQL that drops only phase-2A policies and executes `NO FORCE ROW LEVEL SECURITY` then `DISABLE ROW LEVEL SECURITY`, without touching `app_current_organization_id()` or business data.
- [ ] Run owner forward, reverse, and forward migrations; compare fixture primary keys/content before and after and recheck policy shape.
- [ ] Commit the six policy migrations and PostgreSQL tests as `feat(db): enable tenant RLS for phase 2A`.

### Task 3: Add machine-checkable live database auditing

**Files:**
- Modify: `backend/apps/common/management/commands/audit_rls_coverage.py`
- Modify: `backend/apps/common/tests/test_rls_manifest.py`
- Modify if owner guard is needed: `backend/apps/platforms/management/commands/seed_platforms.py`
- Test if guard is added: `backend/apps/platforms/tests/test_social_accounts_api.py`

**Interfaces:**
- Produces command option `python manage.py audit_rls_coverage --database`.
- Default command behavior remains pure manifest validation.

- [ ] Write failing command tests for missing/extra/wrong policy shapes and role metadata using controlled cursor results; keep error output free of rows, DSNs, and credentials.
- [ ] Implement PostgreSQL catalog inspection for all 15 RLS-1 and 21 RLS-2A tables, policy command/expression shape, owner separation, runtime `NOINHERIT/NOBYPASSRLS`, denied owner role membership, and helper-function executability.
- [ ] Refuse `--database` on non-PostgreSQL connections; leave default manifest-only audit unchanged.
- [ ] Add the same owner/BYPASSRLS guard as `seed_gear_ontology` to `seed_platforms` because Platform and PlatformCapability are runtime read-only global dictionaries.
- [ ] Run manifest tests, command tests, `audit_rls_coverage`, and PostgreSQL `audit_rls_coverage --database`.
- [ ] Commit explicit audit and seed-guard files as `feat(ops): audit phase 2A RLS coverage`.

### Task 4: PostgreSQL runtime-role acceptance

**Files:**
- Test: `backend/apps/common/tests/test_postgres_rls_phase2a.py`
- Reuse: `backend/apps/knowledge/tests/test_postgres_rls.py`
- Reuse: `backend/config/postgres_rls_test_settings.py`
- Reuse: `infrastructure/postgres/bootstrap_rls_roles.sql`

**Interfaces:**
- Owner DSN applies migrations and fixtures; runtime DSN executes all acceptance reads/writes.
- Test budget is at most six primary phase-2A test functions, using parameterization across categories.

- [ ] Verify all 21 tables are enabled and forced and runtime owns none of them.
- [ ] Verify missing GUC hides representative direct, parent, and global rows and rejects writes.
- [ ] Verify tenant A direct-table isolation and cross-tenant INSERT/UPDATE/DELETE rejection.
- [ ] Verify JobAttempt cannot read, insert, or switch to a foreign Job parent.
- [ ] Verify both tenants can read the same global dictionaries with context while runtime cannot INSERT/UPDATE/DELETE.
- [ ] Verify COMMIT/ROLLBACK clear GUC, runtime cannot SET ROLE owner or disable RLS, and representative AI/Asset-or-Catalog/Platform/Job paths work via `tenant_atomic`.
- [ ] Run the RLS-1 PostgreSQL critical regression once after the phase-2A suite.

### Task 5: Deployment, rollback, and audit documentation

**Files:**
- Modify: `docs/database-rls-phase2-inventory.md`

**Interfaces:**
- Documents the exact six policy migrations and the Prompt Catalog prerequisite migration.

- [ ] Record PromptVersion write-entry audit categories and the owner-managed global catalog contract.
- [ ] Mark all 21 RLS-2A tables enabled/forced with their policy class and keep the 96-table classification unchanged.
- [ ] Document the maintenance-window sequence: stop Beat/dispatch, drain old queue, stop Web/Worker, bootstrap roles, owner migrate, bootstrap grants, switch runtime DSNs, start Worker/Beat/Web, then run database audit and representative checks.
- [ ] Document rollback: stop services, owner-reverse the six RLS migrations, preserve tenant data and Knowledge helper, verify roles/DSNs, then restore services.
- [ ] State that ALTER TABLE acquires database locks and owner-run application processes do not constitute RLS acceptance.
- [ ] Commit the document as `docs: document phase 2A RLS deployment`.

### Task 6: Final verification, publishing, and CI

**Files:**
- Verify only files named by Tasks 1-5.

**Interfaces:**
- Draft PR base: `merge/consolidation-security`; head: `feature/database-rls-phase2`.

- [ ] Perform a read-only security review of fail-closed behavior, global-table write denial, JobAttempt parent switching, reverse safety, role separation, and secret-free output.
- [ ] Perform a read-only runtime review of HTTP/Celery/command tenant entry points and representative AI, Asset, Platform/Buffer, Job, and Knowledge paths.
- [ ] Run the bounded PostgreSQL suites, prompt/asset tests, manifest/audit tests, modified-file Ruff, `makemigrations --check --dry-run`, and `git diff --check` exactly once on the final tree.
- [ ] Confirm status contains only planned files, push normally, reuse or create a Draft PR with the required title/body, and never mark ready or merge.
- [ ] Wait for Backend tests and Frontend checks; fix at most two branch-caused CI failures with independent commits and normal pushes.
