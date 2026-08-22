# Email Verification A1 Review Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five Important findings from the independent PR #7 review without adding Contact Discovery, Bouncer, or real email delivery.

**Architecture:** Keep verification local-first and transaction-phased. Resolve and pin public MX addresses before SMTP, bind history to the exact normalized mailbox, make A1 provider fallback decision-only, enforce append-only evidence through an ORM manager, and strengthen Run RLS parent checks. Retire the unaudited legacy Agent verification path by binding it to the tenant service.

**Tech Stack:** Django 5.2, Celery, dnspython, PostgreSQL FORCE RLS, pytest, Ruff.

**Spec:** `docs/email-verification-a1-audit.md`

## Global Constraints

- Do not call a real verification Provider or send email.
- SMTP may issue only connection, greeting, `MAIL FROM`, `RCPT TO`, `RSET`, and `QUIT`; never `DATA`.
- DNS and SMTP remain outside database transactions.
- Do not add Contact Discovery, UI, API, or sending infrastructure.
- Keep PR #7 Draft and do not merge it.

---

### Task 1: Public MX target enforcement

**Files:**
- Modify: `backend/apps/growth/email_verification.py`
- Test: `backend/apps/growth/tests/test_email_verification.py`

**Interfaces:**
- Produces: bounded `MXAddressResolver.resolve(mx_host) -> tuple[str, ...]` and a pinned-IP SMTP connection.

- [x] Add failing tests for private IPv4, loopback/IPv6, mixed public/private answers, and pinned public-IP connection.
- [x] Run the focused tests and confirm they fail because MX addresses are not validated.
- [x] Implement bounded A/AAAA resolution, reject any non-global address, and connect only to a validated pinned IP.
- [x] Run the SMTP/DNS tests and confirm they pass without `DATA`.

### Task 2: Exact-mailbox history and conservative bounce scoring

**Files:**
- Modify: `backend/apps/growth/email_verification.py`
- Modify: `backend/apps/growth/email_verification_services.py`
- Test: `backend/apps/growth/tests/test_email_verification.py`
- Test: `backend/apps/growth/tests/test_email_verification_services.py`

**Interfaces:**
- Consumes: normalized email stored on `EmailVerificationRun`.
- Produces: mutually exclusive latest decisive reply/bounce history for that exact address.

- [x] Add failing tests with two addresses on one account and an unclassified bounce.
- [x] Confirm the current account-wide query and INVALID bounce weighting fail those tests.
- [x] Filter history by exact normalized email, use the latest decisive event, and score an unclassified bounce as RISKY rather than definitively INVALID.
- [x] Run history and scoring tests.

### Task 3: Decision-only third-party fallback and audited Agent entry

**Files:**
- Modify: `backend/apps/growth/email_verification_services.py`
- Modify: `backend/apps/growth/agent/pipeline_tools.py`
- Test: `backend/apps/growth/tests/test_email_verification_services.py`
- Test: `backend/apps/growth/tests/test_agent_enrichment_tools.py`

**Interfaces:**
- Produces: `requires_provider_review` only; A1 never invokes `EmailVerificationProvider.verify`.
- Produces: a tenant-bound Agent tool that calls `verify_email_for_tenant`.

- [x] Add failing tests proving risky/high-value results do not call a Provider and the legacy tool cannot run without a trusted organization.
- [x] Remove A1 Provider execution while retaining the Provider protocol for the later fallback phase.
- [x] Replace the direct Agent `verify_email()` call with a trusted-organization service closure.
- [x] Run service and Agent tool tests.

### Task 4: ORM append-only evidence

**Files:**
- Modify: `backend/apps/growth/models.py`
- Test: `backend/apps/growth/tests/test_email_verification_models.py`

**Interfaces:**
- Produces: an append-only Evidence QuerySet/manager that rejects update, bulk_update, and delete while validating inserts.

- [x] Add failing QuerySet update/delete/bulk_update tests.
- [x] Implement the append-only QuerySet and manager.
- [x] Run model and service evidence tests.

### Task 5: Database parent-tenant enforcement

**Files:**
- Modify: `backend/apps/growth/migrations/0050_email_verification_pipeline.py`
- Modify: `backend/apps/growth/models.py`
- Modify: `backend/apps/growth/tests/test_postgres_email_verification_rls.py`
- Modify: `backend/apps/growth/tests/test_email_verification_rls_manifest.py`

**Interfaces:**
- Produces: Run INSERT/UPDATE `WITH CHECK` predicates that require optional Contact and Candidate parents to belong to the active tenant.

- [x] Add failing frozen-contract and runtime-role cross-parent tests.
- [x] Strengthen the frozen 0050 policy contract and normal ORM save validation.
- [ ] Run manifest tests locally and runtime-role tests in PostgreSQL CI.

### Task 6: Verification and Draft PR update

**Files:**
- Modify: `docs/email-verification-a1-operations.md`

- [x] Run all Email Verification and directly related Agent/migration tests.
- [x] Run Backend full tests, Ruff, Django check, migration drift, RLS manifest audit, and `git diff --check`.
- [ ] Commit and push normally to `feature/email-verification-a1`.
- [ ] Wait for Backend, Frontend, and PostgreSQL runtime-role CI.
- [ ] Keep PR #7 Draft and report the new Head and remaining findings.
