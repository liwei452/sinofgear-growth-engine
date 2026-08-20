# Buffer CreatePost C.1 Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five reviewed Buffer createPost reliability gaps without entering reconciliation batch D.

**Architecture:** Keep the existing publishing state machine and Buffer adapter boundary. Treat every exception after the persisted provider-call marker as an unknown outcome, enforce one live submission per content version and account in both the service and database, route providers before DIRECT fixture handling, preserve DIRECT payload behavior, and let structurally valid mutation success data win over top-level warnings.

**Tech Stack:** Django 5, PostgreSQL conditional unique constraints, pytest, Python Buffer GraphQL adapter.

**Spec:** User review “Buffer third batch C.1 reliability closure” in the current task.

## Global Constraints

- Do not implement Buffer reconciliation or status polling.
- Do not perform real Buffer requests, OAuth, account changes, or publishing.
- Preserve organization isolation and protected publishing writes.
- Keep credential references and provider messages out of responses, logs, and snapshots.
- Use fixture transports only and keep DIRECT connector behavior backward compatible.

---

### Task 1: Unknown outcome after provider call

**Files:**
- Modify: `backend/apps/publishing/services.py`
- Test: `backend/apps/publishing/tests/test_buffer_publish_submission.py`

**Interfaces:**
- Consumes: `_mark_provider_call_started(task, attempt)` and `connector.publish(request)`.
- Produces: any unclassified exception after the marker completes through `complete_publish_unknown(...)` with `OUTCOME_UNKNOWN`.

- [ ] Add a test connector that records one call and raises `RuntimeError`; assert task and attempt become `SUBMISSION_UNKNOWN` and `retry_publish_task` raises `PublishingConflict`.
- [ ] Run the test and verify it fails as `FAILED/PROVIDER_ERROR`.
- [ ] Map every exception from `connector.publish` after the marker to a safe unknown result.
- [ ] Run the focused test and publishing state tests.

### Task 2: Cross-key duplicate submission guard

**Files:**
- Modify: `backend/apps/publishing/models.py`
- Modify: `backend/apps/publishing/services.py`
- Create: `backend/apps/publishing/migrations/0006_publish_task_live_submission_guard.py`
- Test: `backend/apps/publishing/tests/test_buffer_publish_submission.py`

**Interfaces:**
- Consumes: locked `PlatformContent`, locked `SocialAccount`, `content_version`, and active/submitted task statuses.
- Produces: service conflict plus a conditional unique constraint on `(organization, platform_content, content_version, social_account)` for `SCHEDULED`, `QUEUED`, `RUNNING`, `SUBMITTED`, `SUBMISSION_UNKNOWN`, and `SUCCEEDED`.

- [ ] Add different-key and transactional concurrency/constraint tests; verify both fail against the current implementation.
- [ ] Check for a conflicting task only after locking content/account, returning the same task only for the same idempotency key and otherwise raising `PublishingConflict`.
- [ ] Add the conditional database unique constraint and translate its `IntegrityError` to a conflict without masking the existing key-idempotency path.
- [ ] Run the focused service, model, and migration tests.

### Task 3: Provider-first registry routing

**Files:**
- Modify: `backend/integrations/platforms/registry.py`
- Test: `backend/integrations/platforms/tests/test_registry.py`

**Interfaces:**
- Consumes: `SocialAccount.provider` and DIRECT connector metadata.
- Produces: BUFFER always resolves through `provider_connectors`; demo/official routing applies only to DIRECT.

- [ ] Add a BUFFER account with the demo fixture and assert it resolves the Buffer connector; verify failure.
- [ ] Move provider dispatch ahead of DIRECT fixture interpretation.
- [ ] Run registry and runtime tests.

### Task 4: Restore DIRECT media compatibility

**Files:**
- Modify: `backend/apps/publishing/publish_payload.py`
- Test: `backend/apps/publishing/tests/test_publish_payload.py`
- Test: `backend/integrations/platforms/tests/test_buffer_connector.py`

**Interfaces:**
- Consumes: shared platform content/media and Buffer adapter validation.
- Produces: DIRECT LinkedIn/Facebook video continues as text payload; Buffer still rejects video before network.

- [ ] Add DIRECT LinkedIn/Facebook video regression tests and verify current validation fails.
- [ ] Remove Buffer-only media rejection from the shared builder while leaving Buffer adapter validation intact.
- [ ] Run payload and Buffer connector tests.

### Task 5: Preserve successful mutation data with warnings

**Files:**
- Modify: `backend/integrations/platforms/buffer_client.py`
- Test: `backend/integrations/platforms/tests/test_buffer_client.py`

**Interfaces:**
- Consumes: Buffer GraphQL mutation body containing `data` and optional top-level `errors`.
- Produces: structurally valid `PostActionSuccess` data reaches `BufferConnector`; absent/invalid success falls back to existing safe error classification.

- [ ] Add a response containing valid success data plus a top-level warning and verify the current client raises.
- [ ] For createPost mutations only, recognize structurally complete success data before classifying top-level errors.
- [ ] Run client and connector tests, including malformed-success coverage.

### Task 6: Final verification and delivery

**Files:**
- Verify all files above and generated migration.

- [ ] Run focused Buffer/publishing tests.
- [ ] Run full backend tests, Ruff, migration drift check, frontend API check, typecheck, and build.
- [ ] Scan the staged diff for secrets, run `git diff --check`, and verify no real network path was exercised.
- [ ] Commit as an independent C.1 reliability change, push only `merge/consolidation-security`, and confirm local/remote SHA match with a clean worktree.
