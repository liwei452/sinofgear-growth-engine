# Task 5 Fix Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make corrupted source batches safely terminalizable and make ingestion asset validation lock-based, race-safe, and constant-query across any number of rows.

**Architecture:** Add a model-owned, service-guarded state writer that accepts only the mutable ingestion state fields and deliberately bypasses validation of already-corrupted immutable input. Replace boolean preflight with a frozen locked-resource result containing the locked target and one deduplicated asset map, then pass those objects through row and evidence persistence without re-querying assets. Normal batch ORM writes and normal `EvidenceService` callers retain their existing validation paths.

**Tech Stack:** Python 3.12, Django 5.2 transactions and row locks, Django REST Framework, pytest-django, Ruff.

**Execution status:** Completed inline in fix round 2; RED/GREEN and final gate evidence is recorded in the ignored Task 5 report.

## Global Constraints

- Keep `SOURCE_IMPORT_JOB_V1` snapshot comparison and POST mutation OpenAPI schemas unchanged.
- Preflight must finish before `RUNNING` or any ingestion row/evidence write.
- The state bypass may write only `status`, counts, `row_errors`, `started_at`, `finished_at`, and `updated_at`.
- Target and every distinct import/screenshot asset must be locked for the entire outer ingestion transaction.
- Invalid preflight must produce safe batch/Job failure with no partial source records.
- Normal `EvidenceService.create()` callers must retain their current organization-scoped asset locking behavior.

---

### Task 1: Corruption-safe ingestion state transitions

**Files:**
- Modify: `backend/apps/sources/models.py`
- Modify: `backend/apps/sources/services.py`
- Test: `backend/apps/sources/tests/test_source_tasks.py`
- Test: `backend/apps/sources/tests/test_source_hardening.py`

**Interfaces:**
- Consumes: an already locked `IngestionBatch` and service-computed mutable state values.
- Produces: `IngestionService._write_batch_state(batch, **values)`, backed by a private guarded queryset method that rejects every field outside the mutable-state allowlist.

- [ ] **Step 1: Write the failing worker regressions**

Add raw-SQL prepared-reference corruption and cross-organization target-FK corruption cases. Execute the real worker and assert literal safe Job failure, batch `FAILED`, `started_at is None`, the controlled preflight error, and zero rows/content/signals/evidence.

- [ ] **Step 2: Run the focused tests to verify RED**

Run the new task tests together with the existing identity drift test. Expected: worker raises `ValidationError` while the Job becomes `FAILED` and the batch remains `QUEUED`.

- [ ] **Step 3: Add the narrow state writer**

Create a private ingestion-batch state-write context and an `IngestionBatchQuerySet._service_update_state(**values)` method. Reject calls outside the context, reject unknown/immutable fields, sanitize/field-validate allowed values, set `updated_at`, and use Django's base queryset update so corrupted immutable fields are not revalidated.

- [ ] **Step 4: Route service transitions through the writer**

Use `IngestionService._write_batch_state()` for `RUNNING` and terminal statistics/error transitions, updating the in-memory locked instance only after the database write succeeds.

- [ ] **Step 5: Prove the bypass cannot mutate identity**

Add tests showing an unguarded caller cannot use `_service_update_state`, a guarded call still rejects `organization`, `source_type`, `input_reference`, `idempotency_key`, `monitoring_target`, or `job`, and ordinary save/update/bulk-update identity protection remains unchanged.

- [ ] **Step 6: Run the focused tests to verify GREEN**

Run Task 1 task/hardening cases and require all pass.

### Task 2: Locked preflight resource cache and trusted evidence path

**Files:**
- Modify: `backend/apps/sources/models.py`
- Modify: `backend/apps/sources/services.py`
- Test: `backend/apps/sources/tests/test_ingestion_service.py`
- Test: `backend/apps/sources/tests/test_source_tasks.py`

**Interfaces:**
- Consumes: canonical batch reference plus its distinct target/import/screenshot IDs.
- Produces: frozen `_LockedIngestionResources` with a read-only asset map; `_persist_valid_row(..., resources=resources)`; private `EvidenceService._create_from_locked_ingestion_assets(...)` that verifies cache membership, ID, organization, `ACTIVE` status, and screenshot image type.

- [ ] **Step 1: Write query-bound and cache-integrity regressions**

Create equivalent one-row and many-row successful imports using repeated and distinct screenshots plus one import asset. Capture real SQL and assert the same bounded number of `assets_materialasset` queries with no per-row growth. Add a mutation/simulated archive case proving the trusted cache refuses an altered object and writes no evidence for that row.

- [ ] **Step 2: Run the focused tests to verify RED**

Expected: many rows issue more asset queries than one row, because row persistence and evidence creation re-query both assets.

- [ ] **Step 3: Lock and validate all resources once**

Within `IngestionService.run()`'s outer atomic block, use `select_for_update()` for the target and one ordered `pk__in` query for the complete deduplicated asset set. Validate organization, target enabled, asset active state, import membership, and screenshot image type before `RUNNING`.

- [ ] **Step 4: Reuse the locked map through persistence**

Resolve screenshot/import objects from the frozen preflight cache for every row. Remove `_persist_valid_row()` and `_import_asset()` asset queries. Add a private evidence path that revalidates the exact cached objects and skips only redundant asset foreign-key database validation while preserving all other evidence validation and normal-caller behavior.

- [ ] **Step 5: Cover transaction serialization as supported by the test backend**

Assert lock-marked querysets are acquired inside the outer atomic block; if the backend cannot demonstrate real row-lock blocking, use a deterministic transaction-bound archive simulation and document the backend limitation in the report.

- [ ] **Step 6: Run the focused tests to verify GREEN**

Run ingestion service/task/evidence/hardening cases and require constant asset queries plus unchanged direct `EvidenceService` validation.

### Task 3: Controller verification and delivery

**Files:**
- Modify: `.superpowers/sdd/2026-08-10-phase-b1-lead-intelligence-foundation/task-5-report.md` (ignored report only)
- Regenerate only if changed: `frontend/src/api/generated/schema.ts`

**Interfaces:**
- Consumes: Tasks 1 and 2 green commits-in-working-tree.
- Produces: one fix-round commit, exact RED/GREEN evidence, and a clean verified worktree.

- [ ] **Step 1: Run focused suites**

Run source service/task/hardening/API/OpenAPI tests.

- [ ] **Step 2: Run full related suites**

Run all source tests, then jobs + sources + global OpenAPI tests.

- [ ] **Step 3: Run static and drift gates**

Run Django check, `makemigrations --check --dry-run`, full backend Ruff, API artifact drift, and `git diff --check`.

- [ ] **Step 4: Append the ignored report**

Record the exact Task 1 and Task 2 RED/GREEN commands/results plus the final verification output and SQLite locking limitation if applicable.

- [ ] **Step 5: Commit and inspect**

Commit only repository artifacts with `fix: make source preflight transitions race safe`, then confirm the worktree is clean and report status/commit/tests/report to the controller.
