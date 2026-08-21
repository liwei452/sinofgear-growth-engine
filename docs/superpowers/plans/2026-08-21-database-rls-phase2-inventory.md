# Database RLS Phase 2 Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete, explicit, machine-validated classification for every managed business table and document every runtime path that must be tenant-scoped in RLS-2A/B/C.

**Architecture:** A frozen manifest records one reviewed entry per table. A registry-based validator compares that manifest with every managed concrete model, including auto-created M2M models, and validates category-specific organization metadata without generating policy SQL. A management command exposes the validator to CI, while a separate inventory document records the source-audited HTTP, task, public, and command entry points.

**Tech Stack:** Django 5.2 app registry and management commands, Python frozen dataclasses/enums, pytest, Ruff.

**Spec:** User-approved RLS-2.0 requirements in this task.

## Global Constraints

- Exact baseline: `3612756f62d082ba2ee7e9823dc6ff9bc3b15cda`.
- Do not add migrations or PostgreSQL policies.
- Do not modify models, task parameters, API, UI, OpenAPI, or business state machines.
- Every managed concrete business model, including automatic M2M models, must have exactly one explicit manifest entry.
- Built-in Django exclusions must be explicit and must never hide an installed business app.
- Historical migrations must never import the live Python manifest.
- Add no more than four direct tests and run only those tests, Ruff, the audit command, and `git diff --check`.

---

### Task 1: Manifest contract and failing coverage tests

**Files:**
- Create: `backend/apps/common/tests/test_rls_manifest.py`
- Create: `backend/apps/common/rls_manifest.py`

**Interfaces:**
- Produces `RLSCategory`, `RLSPhase`, `RLSManifestEntry`, `RLS_MANIFEST`, `audit_rls_coverage`, `assert_rls_coverage`, and `RLSManifestError`.
- Consumes Django's configured apps registry only; it does not inspect row data or produce SQL.

- [ ] Add four tests covering complete classification, duplicate entries, invalid table/parent path metadata, and command failure after deliberate manifest removal.
- [ ] Run the new tests and confirm they fail because the manifest module/command does not exist.
- [ ] Implement frozen types and category-specific validation.
- [ ] Populate all 96 explicit entries, including the 15 RLS-1 tables and `KnowledgeGraphLock`.
- [ ] Run the tests and confirm the validator accepts exactly the current registry.

### Task 2: CI-facing audit command

**Files:**
- Create: `backend/apps/common/management/commands/audit_rls_coverage.py`

**Interfaces:**
- Consumes `assert_rls_coverage()`.
- Produces a zero exit status and summary counts for a valid manifest; raises `CommandError` with labels/table names only for invalid coverage.

- [ ] Implement the read-only command without database row queries.
- [ ] Confirm deliberate missing-entry injection raises `CommandError` without sensitive output.
- [ ] Run `python manage.py audit_rls_coverage` against test settings.

### Task 3: Runtime entry audit and phase plan

**Files:**
- Create: `docs/database-rls-phase2-inventory.md`

**Interfaces:**
- Consumes the explicit manifest plus source searches of permissions, tasks, Beat configuration, public views, services, and management commands.
- Produces the reviewed RLS-2A/B/C handoff; it does not change runtime behavior.

- [ ] Document category counts and full table names.
- [ ] Document HTTP pre-context/control-plane behavior and authenticated tenant-context behavior.
- [ ] List every `shared_task`, its arguments, first ORM access, and risk.
- [ ] List every Beat scan and required control-plane-enumeration pattern.
- [ ] Document redirect, RFQ, visit, and OAuth callback tenant-location behavior.
- [ ] Document all custom management commands and owner/per-tenant requirements.
- [ ] Record RLS-2A/B/C dependencies and every table whose organization cannot yet be safely located before RLS.

### Task 4: Bounded verification and delivery

**Files:**
- Verify all files changed by Tasks 1-3.

**Interfaces:**
- Produces one independent commit on `feature/database-rls-phase2` and a normal push to `origin`.

- [ ] Run only `apps/common/tests/test_rls_manifest.py`.
- [ ] Run Ruff only on modified Python files.
- [ ] Run `audit_rls_coverage`.
- [ ] Run `git diff --check` and inspect the exact file list.
- [ ] Commit, push without force, confirm clean status, and stop before RLS-2A.
