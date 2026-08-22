# Email Verification A1 Operations

## Runtime boundary

Every verification uses short tenant transactions around preparation and finalization. DNS, SMTP, and shared-cache acquisition execute after preparation commits and before finalization begins. SMTP probing never issues `DATA` and therefore never sends a message. A1 does not execute a third-party verification Provider.

MX A/AAAA records are resolved with bounded DNS lifetimes before SMTP. Every returned address must be globally routable, and the probe connects to a validated pinned IP rather than resolving the hostname again. Private, loopback, link-local, special-use, invalid, empty, and mixed public/private answers are fail-closed without opening an SMTP socket.

Celery payloads contain only `organization_id` and `verification_id` UUID strings. Workers must use the `sinofgear_app` runtime database role. They must not infer an organization from a verification ID.

## Bounded network settings

| Setting | Default | Purpose |
| --- | ---: | --- |
| `EMAIL_VERIFICATION_DNS_TIMEOUT_SECONDS` | 3 | Per DNS attempt timeout |
| `EMAIL_VERIFICATION_DNS_LIFETIME_SECONDS` | 5 | Total resolver lifetime |
| `EMAIL_VERIFICATION_SMTP_TIMEOUT_SECONDS` | 5 | SMTP connect/read timeout |
| `EMAIL_VERIFICATION_SMTP_RETRIES` | 1 | Additional bounded SMTP attempt |
| `EMAIL_VERIFICATION_DOMAIN_LOCK_SECONDS` | 10 | Shared hashed-domain exclusion interval |
| `EMAIL_VERIFICATION_CLAIM_TIMEOUT_SECONDS` | 120 | Reclaim abandoned RUNNING work while stale workers remain fenced by claim token |
| `CACHE_URL` | unset locally | Shared production Redis cache used for domain exclusion |

Production Web and Celery processes must share Redis. The cache key contains only a SHA-256 digest of the domain. A local-memory cache is used by tests only and does not provide cross-worker throttling.

## Evidence and privacy

Evidence records store check type, safe outcome, reason code, source/version, timing, MX count, and numeric SMTP response code. They do not store SMTP banners, response text, transcripts, credentials, tokens, Provider payloads, or raw exceptions. Logs and task failures use stable safe error codes and must not include the address. Instance, QuerySet, RLS Policy, and runtime table privileges independently reject Evidence mutation or deletion.

`VALID` requires strong historical evidence such as a reply for the exact normalized mailbox. SMTP acceptance alone is `LIKELY_VALID`; catch-all is `RISKY`; role mailboxes affect contact quality but are not invalid. An unclassified historical bounce is a risk signal rather than definitive INVALID because the current feedback model does not distinguish hard and soft bounces. No local-screening percentage is promised before real production data is calibrated.

## Third-party boundary

`EmailVerificationProvider` is an interface contract only. No factory, Bouncer client, credential, or Provider execution path is included in A1. Risky, unknown, catch-all, and high-value results are only marked with `requires_provider_review`; a later explicitly approved phase must implement any third-party call.

## Deployment

1. Stop new verification task dispatch and drain old workers.
2. Run migrations as `sinofgear_owner`; never use the runtime role.
3. Re-run `bootstrap_rls_roles.sql` as owner so the runtime role receives the intended table grants without ownership or BYPASSRLS.
4. Run `audit_rls_coverage --database default` and the PostgreSQL email-verification RLS test using the real runtime login.
5. Start workers and verify new task payloads include both UUIDs.
6. Resume dispatch and observe only safe counters/error codes.

## Rollback

Stop dispatch and workers, use the owner connection to reverse `growth.0050`, then run the complete RLS audit before restarting the previous application version. Reversal removes only the two A1 tables and their own policies; it does not remove the Knowledge tenant helper or change prior Growth migrations. Export or retain verification history according to the deployment's retention policy before intentionally reversing in an environment that contains A1 results.
