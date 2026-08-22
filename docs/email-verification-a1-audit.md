# Email Verification A1 Audit

**Baseline:** `d633b96e737b1f7b7a55b1daa3392c8b4da5344f` (`origin/merge/consolidation-security`)

## Scope and conclusion

This audit covers the existing local verification helper, contact data, outreach approval and delivery, feedback events, tenant transaction boundaries, background work, and RLS inventory. The repository has reusable provider and tenant primitives, but it does not yet have a durable email-verification domain model or a local deliverability pipeline.

No migration-graph conflict or security blocker requires stopping A1. Growth currently belongs to the planned RLS-2C tranche, so any A1 tenant table must be explicitly listed in the manifest and must enable its own PostgreSQL FORCE RLS policy without modifying migrations `growth.0001` through `growth.0049`.

## Current capabilities

### Verification

- `apps.growth.email_verification.verify_email()` normalizes with `strip().lower()`, applies a regular expression, and calls `socket.gethostbyname()`.
- The current result values are `INVALID_SYNTAX`, `DOMAIN_RESOLVES`, and `DOMAIN_UNRESOLVABLE`; they are not the requested five-state contract.
- `EmailVerificationProvider` and `EMAIL_VERIFICATION_PROVIDER_FACTORY` already provide an extension seam. There is no Bouncer implementation.
- The proactive acquisition Agent invokes verification after leaving its tenant transaction. This already avoids putting the current DNS lookup inside a database transaction.
- `apps.sources.adapters.dns_lookup.DnsLookupAdapter` can query Google DNS-over-HTTPS for MX and A records, but it is a generic external source adapter, has a 30-second timeout, and does not implement local SMTP, evidence persistence, retry, or tenant-aware throttling.

### Contact identity

- `growth.Contact` represents a named person attached to a `TargetAccount`; it has `full_name`, `role_title`, `public_contact_path`, and a coarse `verification_status`.
- There is no `Person` or `ContactPoint` model and no normalized email column on `Contact`.
- Discovered email addresses are primarily stored as labels inside `CandidateEnrichmentSnapshot.public_contact_paths` JSON. Website extraction labels them `UNVERIFIED`.
- Agent contact verification reads those JSON paths. A second, generic pipeline tool can call `verify_email()` without an organization.
- A new verifier must not reinterpret `Contact.verification_status` as an email-deliverability record. Verification needs an independent identity, optional links to `Contact`/`DiscoveryCandidate`, and an organization boundary.

### Outreach and approval

- `OutreachDraft` has `DRAFT`/`APPROVED` state and can bind the frozen Knowledge Context Snapshot.
- Proactive Agent email sending is a high-risk tool and waits for AgentRun approval. The send path validates Snapshot-bound external claims before Provider I/O.
- `record_sent()` is already split into prepare transaction, Provider send outside the transaction, and finalize transaction.
- The current verifier is advisory; there is no persisted verification gate between approval and delivery. A1 should expose a safe result for callers but must not silently change outreach approval or sending policy.

### Delivery and feedback

- `EmailDeliveryProvider` supports a mock provider and Django SMTP delivery. Default mock delivery is fail closed.
- `OutreachMessage` records Provider identity, message ID, status, timestamps, and an unstructured payload.
- `record_reply()`, `record_bounce()`, and `record_unsubscribe()` update the latest message for an account and advance `FollowUp`.
- Growth events record sent, failed, replied, bounced, and unsubscribed outcomes. There is no distinct delivery event and no hard/soft bounce classification.
- Historical matching can use the normalized recipient already present in outbound payloads, but an accepted send is only weak evidence; a reply is strong evidence and a bounce is negative evidence.

### Tenant and task infrastructure

- `tenant_atomic(UUID)` uses transaction-local `set_config('app.current_organization_id', ..., true)`, rejects unsafe nested tenant changes, and has an explicit SQLite compatibility mode that is not RLS.
- Celery task IDs are parsed by `parse_tenant_organization_id()`. Object tasks receive a trusted organization UUID and re-query with an explicit organization predicate.
- `dispatch_task_on_commit()` is available for durable dispatch after the creating transaction commits.
- Coordinator tasks materialize control-plane organization IDs and allocate a global limit without holding one tenant transaction across network work.
- Growth tenant tables are explicitly classified as RLS-2C. The baseline manifest audit reports 96 classified tables: RLS-1 15, RLS-2A 21, RLS-2B 16, RLS-2C 40, exempt 4.

## Gaps

- No MX-specific or null-MX handling, disposable-domain list, role-mailbox classification, company-domain/name-pattern comparison, SMTP RCPT probe, catch-all probe, greylist interpretation, or domain-level limiter.
- No separate deliverability and contact-quality scores.
- No stable reason-code vocabulary or five-state result contract.
- No stored verification source, evidence, observation time, expiry, verifier version, or immutable check history.
- No idempotent/pauseable verification run, claim token, stale-finalize protection, or Celery task.
- No persisted fallback decision for `RISKY`, `UNKNOWN`, catch-all, or high-value contacts.
- No current feedback webhook maps a Provider delivery/bounce to an exact email verification record.
- No PostgreSQL runtime-role RLS test exists for a future verification table.

## Data-model impact

Add two models rather than modifying `Contact`:

1. `EmailVerificationRun` — a tenant-owned lifecycle record keyed by an organization-scoped idempotency key. It stores the normalized address, a fingerprint, optional `Contact` and `DiscoveryCandidate` links, lifecycle state, final five-state result, independent scores, reason codes, verifier version, third-party-review decision, safe error code, claim token, and timing.
2. `EmailVerificationEvidence` — append-only tenant-owned check evidence linked to a run. It stores check type, source, source version, outcome, reason code, observation/expiry time, duration, and a sanitized JSON envelope.

Both models carry `organization_id` directly. Service validation must ensure optional parents belong to the same organization. Evidence must be immutable after insertion. The migration will be new `growth.0050`; no historical migration or data will be rewritten or backfilled.

## Network and transaction boundary

The execution service will use three phases:

1. **Prepare:** inside `tenant_atomic`, validate tenant ownership, lock/reuse the idempotent run, respect `PAUSED`, assign a claim token, and freeze the minimal request snapshot.
2. **Network:** outside all database transactions, perform DNS and SMTP checks and optional injected Provider verification. No ORM access is allowed. Resolver, SMTP, and Provider calls receive immutable value objects only.
3. **Finalize:** in a new `tenant_atomic`, re-lock the run, compare claim token/state, insert sanitized evidence, and save the result. A stale worker cannot overwrite a pause or newer claim.

Domain concurrency and minimum interval will use a shared Django cache lock keyed by a hash of the domain. Production cache uses Redis; tests may use the local cache. Timeout and retry counts are bounded by settings. SMTP performs only handshake, `MAIL FROM`, `RCPT TO`, reset, and quit; it never sends `DATA`.

## Security and privacy risks

- Email addresses are personal/customer data. Logs and task errors must use safe codes and must not include addresses, payloads, SMTP transcripts, credentials, tokens, or raw Provider errors.
- Evidence may include MX hostnames and SMTP response classes/codes, but not raw banners or response text.
- SMTP probing can look abusive. It needs strict timeouts, a small retry budget, a hashed shared domain lock, and no message delivery.
- SMTP `250` can be caused by catch-all or delayed rejection and is never sufficient for `VALID`.
- Catch-all acceptance cannot produce `VALID`; role mailboxes reduce contact quality but do not produce `INVALID`.
- Existing GrowthEvent delivery payloads contain full recipient addresses. A1 will read them for history but will not copy them into logs or evidence envelopes.
- Third-party verification remains optional and injected. The repository will not include Bouncer credentials, a Bouncer client, or a real call.
- SQLite tests prove functional compatibility only. PostgreSQL acceptance must connect as the real non-owner, NOBYPASSRLS runtime role.

## Staged implementation

### A1.1 — Contracts and pure local checks

- Define normalized request/result/evidence value objects, status/reason enums, scoring rules, disposable/role rules, company-name pattern comparison, resolver and SMTP protocols.
- Implement deterministic unit tests with fake DNS/SMTP boundaries.

### A1.2 — Persistence, lifecycle, and task

- Add run/evidence models, tenant-safe prepare/finalize services, pause behavior, idempotent dispatch, and a Celery object task with explicit `organization_id`.
- Reuse delivery history conservatively and update the proactive Agent verifier to use the tenant-aware service.

### A1.3 — RLS and operations

- Add the two tables to the explicit manifest, enable FORCE RLS in `growth.0050`, and test isolation with the real runtime role.
- Add bounded settings for DNS/SMTP timeouts, retries, and hashed domain throttling. Document that production cache must be shared Redis.

### A1.4 — Verification and Draft PR

- Run targeted tests, migration round-trip/full graph recovery, backend suite, Ruff, system check, migration drift check, PostgreSQL runtime-role tests, and whitespace checks.
- Push normally and create a Draft PR only. No merge or auto-merge.

## Baseline evidence

- `pytest apps/growth/tests/test_email_verification.py -q`: 4 passed.
- `manage.py audit_rls_coverage` under test settings: valid, 96 tables classified.
- Worktree was clean at baseline `d633b96e737b1f7b7a55b1daa3392c8b4da5344f`.
