# Phase B1 lead-intelligence acceptance

Updated: 2026-08-11

## Outcome

Phase B1 is accepted for local, offline public-signal intake and evidence-based lead review. The accepted path uses the ordinary product UI and the normal production orchestration interfaces with an isolated deterministic provider. It makes no third-party crawl, paid AI request, outreach request, or CRM handoff.

The acceptance environment uses a temporary SQLite database, temporary object storage, eager jobs, dynamic localhost ports, and synthetic `example.com` / `example.invalid` data. The launcher removes only the marked temporary directory and processes that it created.

## Reproduce the focused acceptance

Backend, from `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest apps\leads\tests\test_lead_evaluation.py apps\common\tests\test_seed_phase_b1.py integrations\ai\tests\test_schema_fake_provider.py tests\test_openapi.py tests\test_openapi_contract.py apps\leads\tests\test_lead_openapi.py -q
```

Expected result: `18 passed`. The seed idempotence test invokes `seed_phase_b1` twice against the same named organization and user and asserts that every scoped row count remains unchanged.

Frontend and browser, from `frontend`:

```powershell
pnpm api:generate
pnpm api:check
pnpm typecheck
pnpm test:e2e -- phase-b1-lead-intelligence.spec.ts
```

The launcher currently runs the complete browser collection. Expected result: `7 passed`, including the two Phase B1 scenarios and the five preserved Phase A / Task 11D scenarios.

## Offline evaluation fixture

`backend/apps/leads/tests/fixtures/lead_evaluation.json` contains 100 fully labeled public industrial examples:

- 50 English and 50 Chinese examples;
- 20 explicit needs;
- 10 each for vague need, ordinary engagement, advertisement, recruitment, job seeker, competitor/supplier pitch, academic/student, and company page without comments;
- stable IDs, language, source text, category, explicit-need label, expected score band, expected company-confidence class, and required evidence spans;
- no private contact details.

The deterministic evaluator produces the same result on repeated calls. The accepted metrics are:

| Metric | Required | Result |
| --- | ---: | ---: |
| Explicit-need recall | at least 0.90 | 1.00 (20/20) |
| High-value precision | at least 0.80 | 1.00 (20/20) |
| Evidence-reference coverage | exactly 1.00 | 1.00 (100/100) |

This fixture is an offline regression baseline, not a claim that a deterministic heuristic replaces the audited analysis pipeline.

## Seeded demonstration contract

The command requires a named organization slug and username with an active membership:

```powershell
python manage.py seed_phase_b1 --organization-slug <slug> --username <username>
```

It idempotently creates one monitoring target, one mixed paste batch with three accepted rows and one failed row, three immutable evidence records, four low/watch/high candidates, five insights, one reviewed correction, six jobs including one intentionally failed analysis job, and four completed AI runs.

It also publishes the immutable `phase-b1-lead-analyze-v1` prompt. That prompt is executed through the ordinary `LEAD_ANALYZE` job service, frozen analysis snapshot, provider registry, output-schema validation, audit run, binding, and candidate finalization. The `schema-fake` provider is network-free and credential-free; it materializes and validates arbitrary nested JSON schemas deterministically and has separate generic-schema and lead-grounding tests.

Creation of the second browser identity is guarded by `PHASE_A_E2E_SEED_ALLOWED`. It is unavailable under normal settings and uses only a synthetic `.invalid` address and the documented test-only password.

## Supported intake modes and platform boundary

The UI and API support:

- public HTTP/HTTPS URL plus supplied public text;
- screenshot plus public URL/text and an organization-owned screenshot asset;
- UTF-8 CSV;
- JSON with a `rows` list;
- tab-separated paste rows.

Rows are normalized independently, so a mixed batch can finish with `PARTIAL_SUCCESS`; valid rows remain available and invalid rows retain recoverable errors. Unsafe URLs, cross-organization assets/evidence, unknown fields, malformed dates, duplicate headers, and invalid row shapes fail closed.

Phase B1 does not log in to social platforms, bypass access controls, solve challenges, rotate proxies, scrape private content, collect hidden contact details, or send messages. Live platform collection remains limited by public availability, terms, rate limits, and future approved connectors.

## Browser proof

The primary Phase B1 browser journey performs this sequence through visible controls:

1. log in as the ordinary operator;
2. open Customer Opportunities and import the seeded public-signal bridge using the paste UI;
3. wait for the real ingestion job to complete;
4. open the linked real candidate and inspect its exact immutable evidence text and source URL;
5. start a real `LEAD_ANALYZE` job through the UI and wait for `SUCCEEDED`;
6. inspect the resulting evidence and audit-backed explanation;
7. log in as the reviewer, choose “确认值得跟进”, enter a reason, and submit through the UI;
8. verify the persisted `REVIEWED` state, success message, advanced audit view, and review history.

A second isolated organization owns a real user, candidate, and evidence. The primary organization cannot see that candidate in its list, receives `404` for its detail, and receives `404` when attempting a schema-valid analysis mutation using the foreign evidence. The response does not leak candidate, company, or evidence content and is not an unknown-field `400` shortcut.

The same run preserves the Task 11D acceptance for exactly five ordinary navigation entries, mobile focus trapping/restoration, beginner promotion, advanced-mode persistence, and permission-hidden mutation controls.

## Retention behavior

New public evidence starts as `TRANSIENT_30D`. Expired transient evidence is redacted through the retention job while immutable hashes, audit history, and safe tombstones remain. Evidence promoted to `CONFIRMED`, protected by handoff state, referenced by review history or a completed immutable analysis snapshot, or involved in active work fails closed against deletion/redaction. Shared raw assets and rows are handled atomically so one protected member protects the shared component.

## Full verification record

| Gate | Result |
| --- | --- |
| Focused Task 12 backend suite | 18 passed |
| Complete backend pytest | 1185 passed, 1 skipped |
| OpenAPI generate then drift check | passed; no tracked temporary JSON and no schema drift |
| OpenAPI atomic/lifecycle tests | 3 passed |
| Complete frontend Vitest suite | 34 files, 308 passed |
| Vue TypeScript check | passed |
| ESLint | passed |
| Vite production build | passed; 150 modules transformed |
| Browser suite | 7 passed |
| `docker compose config` | not runnable on this machine: the `docker` executable is not installed or available on `PATH` |

The one backend skip is the repository's existing Windows platform-dependent skip. The first complete-backend attempt was stopped by a 124-second command runner limit with no failure output; the verification was immediately repeated with a longer window and completed successfully in 194.19 seconds.

## Ownership boundary after acceptance

Phase B1 ends at explainable, evidence-grounded human review of public signals. Phase B2 owns company enrichment, contact recommendation, outreach drafting/sending, and handoff/CRM behavior. None of those capabilities is implied by this acceptance or enabled by its seed/provider.
