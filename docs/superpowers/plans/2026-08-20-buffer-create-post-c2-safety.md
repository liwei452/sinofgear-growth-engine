# Buffer CreatePost C.2 Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining provider-finalization, retry-race, and existing-database migration safety gaps before Buffer reconciliation batch D.

**Architecture:** Put result classification and every post-provider finalizer behind one conservative boundary that falls back to `SUBMISSION_UNKNOWN`. Reuse the live-task identity invariant when retrying FAILED tasks and translate database races to `PublishingConflict`. Split migration 0006 into a read-only duplicate precheck followed by the constraint, and expose the same detector through a read-only management command.

**Tech Stack:** Django 5, PostgreSQL/SQLite conditional constraints, pytest, MigrationExecutor.

**Spec:** User review “Buffer third batch C.2 finalization, retry, and migration safety closure” in the current task.

## Global Constraints

- Do not implement Buffer status polling or reconciliation batch D.
- Do not call Buffer, OAuth, paid APIs, or any real publishing endpoint.
- Never auto-delete, cancel, overwrite, or relabel existing publishing history.
- Migration and audit output may include only task IDs and statuses; no content, credentials, provider payloads, or personal data.
- Preserve organization isolation, protected publishing writes, and existing DIRECT behavior.

---

### Task 1: Unified post-provider finalization boundary

**Files:**
- Modify: `backend/apps/publishing/services.py`
- Test: `backend/apps/publishing/tests/test_async_publish_states.py`
- Test: `backend/apps/publishing/tests/test_buffer_publish_submission.py`

**Interfaces:**
- Consumes: `_mark_provider_call_started`, `_result_kind`, and the four `complete_publish_*` functions.
- Produces: `_finalize_provider_result(task, attempt, result)` that returns a post or `None` and converts any unclassified classification/finalization exception to `complete_publish_unknown`.

- [ ] Add submitted-finalizer, failure-finalizer, malformed-result, and post-call cancel tests with literal expected states.
- [ ] Run each test against `61114a9`; verify submitted/failure/malformed paths fail or raise and cancellation succeeds incorrectly.
- [ ] Make `_safe_error` use `getattr`, wrap classification and all four finalizers, and reject cancel when a RUNNING task has `provider_call_started_at`.
- [ ] Run async and Buffer publishing state suites.

### Task 2: Retry live-task guard and race translation

**Files:**
- Modify: `backend/apps/publishing/services.py`
- Test: `backend/apps/publishing/tests/test_buffer_publish_submission.py`

**Interfaces:**
- Consumes: `LIVE_PUBLISH_TASK_STATUSES`, locked FAILED `PublishTask`, and `_find_blocking_publish_task`.
- Produces: retry conflict when another task for the same content version/account is live, including a constraint race during FAILED-to-QUEUED transition.

- [ ] Create two FAILED tasks for one content version/account; retry the first and assert retrying the second raises `PublishingConflict` rather than `IntegrityError`.
- [ ] Add a race test that hides the blocker during the precheck and lets the conditional constraint reject the transition.
- [ ] Lock/check other live tasks before retry, wrap the state transition in an inner savepoint, and translate the unique constraint race to the same conflict.
- [ ] Run retry, idempotency, and API tests.

### Task 3: Existing-database migration precheck and audit command

**Files:**
- Modify: `backend/apps/publishing/migrations/0006_publishtask_unique_live_content_account.py`
- Create: `backend/apps/publishing/duplicate_live_tasks.py`
- Create: `backend/apps/publishing/management/__init__.py`
- Create: `backend/apps/publishing/management/commands/__init__.py`
- Create: `backend/apps/publishing/management/commands/audit_duplicate_publish_tasks.py`
- Create: `backend/apps/publishing/tests/test_publish_task_migration.py`
- Create: `backend/apps/publishing/tests/test_duplicate_publish_task_audit.py`

**Interfaces:**
- Consumes: publishing task rows grouped by organization, platform content, content version, and social account for the six live/succeeded statuses.
- Produces: deterministic groups containing only task IDs and statuses; migration raises a clear exception before AddConstraint when any group exists; command prints the same read-only report and exits non-zero through `CommandError`.

- [ ] Write MigrationExecutor tests for clean upgrade and duplicate upgrade failure, recording complete before/after row snapshots.
- [ ] Write command tests for clean output and duplicate output containing only IDs/statuses.
- [ ] Run tests and verify current migration fails with raw `IntegrityError` and the command is absent.
- [ ] Add a shared read-only grouping helper, RunPython precheck before AddConstraint, and command with no write operations.
- [ ] Run migration, command, migration-drift, and publishing tests.

### Task 4: Final verification and delivery

**Files:**
- Verify all files above and the C.2 plan.

- [ ] Run focused finalization/retry/migration tests.
- [ ] Run full backend tests, Ruff, migration drift check, frontend API check, typecheck, and build.
- [ ] Run staged diff and secret scans; confirm no real transport was invoked.
- [ ] Commit C.2 independently, push only `merge/consolidation-security`, and verify local/remote SHA plus clean worktree.
