# Task 12 report — Phase B1 acceptance closure

## Status

Implementation and product verification are complete. The only unavailable environmental check is `docker compose config`, because this Windows host has no `docker` executable on `PATH`. No plan or progress-ledger file was modified.

## Delivered scope

- Added a 100-record, fully labeled English/Chinese industrial evaluation fixture with all nine required categories and no private contact data.
- Added deterministic public-signal normalization, exclusion-aware scoring, company-confidence classification, and evidence-span validation.
- Added an idempotent `seed_phase_b1` command bound to an explicitly named organization/user and active membership.
- Seeded a published immutable `LEAD_ANALYZE` prompt that runs end to end through the normal snapshot, job, provider, schema validation, audit, binding, and finalization path.
- Added a deterministic, network-free, credential-free schema-aware provider with generic nested-schema and lead-grounding coverage. It does not expose a test endpoint or mutate persistence itself.
- Added a guarded second E2E identity/organization plus real foreign candidate/evidence fixtures.
- Added the complete ordinary UI import → analyze → evidence → reviewer decision journey and real-resource organization-isolation challenge.
- Preserved Task 11D's five-entry ordinary navigation, mobile behavior, beginner promotion, advanced-mode persistence, and permission boundaries.
- Expanded backend OpenAPI surface/tag/pagination assertions, regenerated atomically, and proved zero drift.
- Updated acceptance and handoff documentation with exact results, import modes, retention behavior, platform limits, and the B2 boundary.

## TDD record

### Evaluation fixture and scorer

RED 1: `test_lead_evaluation.py` failed during collection because `evaluate_public_signal` did not exist; 0 tests executed, 1 collection error.

GREEN attempt: 2 tests executed and 2 failed. The failures identified one incorrect Chinese required span and one company-confidence rule that conflated personal/vague language with company evidence.

GREEN: 2 passed. Exact quality results: recall 1.00 (20/20 explicit needs), high-value precision 1.00 (20/20 predicted high), evidence coverage 1.00 (100/100). Repeated evaluation output was byte-for-byte equivalent at the asserted data level.

Files:

- `backend/apps/leads/tests/fixtures/lead_evaluation.json`
- `backend/apps/leads/tests/test_lead_evaluation.py`
- `backend/apps/leads/scoring.py`

### Phase B1 seed and provider

RED 1: the initial seed suite reported 2 failed because `seed_phase_b1` did not exist.

GREEN attempt: 1 passed and 1 failed because the requested `schema-fake` provider was not registered.

Provider RED 1: the provider test module could not import `SchemaAwareFakeAIProvider`; 0 tests executed, 1 collection error.

Provider GREEN attempt: 1 passed and 1 failed. A schema property named `intent` exposed a collision between 0–1 confidence fields and 0–30 score dimensions.

Provider GREEN: 2 passed after choosing semantic values from the caller's numeric schema bounds and validating every emitted document with the caller-selected JSON Schema validator.

Seed GREEN: 2 passed. The idempotence case ran the command twice and held exact scoped counts at 1 target, 1 batch, 3 evidence rows, 4 candidates, 5 insights, 1 review, 6 jobs, and 4 AI runs.

Identity RED: the guarded foreign-identity test failed on unknown command arguments.

Identity GREEN: 1 passed. The full seed module now reports 3 passed.

Files:

- `backend/apps/common/management/commands/seed_phase_b1.py`
- `backend/apps/common/tests/test_seed_phase_b1.py`
- `backend/integrations/ai/providers.py`
- `backend/integrations/ai/__init__.py`
- `backend/integrations/ai/tests/__init__.py`
- `backend/integrations/ai/tests/test_schema_fake_provider.py`

### Browser launcher, copy, and acceptance

Launcher RED: the launcher suite failed before test execution because the new named export did not exist; 0 tests executed, process exit 1.

Launcher GREEN: 6 passed. The launcher now seeds both isolated organizations only inside its owned temporary E2E environment.

UI copy RED: the focused lead-detail suite reported 10 failed and 20 passed because the UI still exposed “确认机会”.

UI copy GREEN: 30 passed after the visible action, confirmation, and audit-history labels became “确认值得跟进”.

Browser acceptance was written after the lower-level launcher, seed, orchestration, and UI contracts were green. Its first real-stack run passed 7/7: five preserved Phase A / Task 11D tests plus the two new Phase B1 tests. The first new test uses visible UI for all product writes and reaches persisted `REVIEWED`; the second uses a real foreign candidate/evidence and schema-valid mutation to prove `404` isolation without content leakage. Direct request access is limited to this hostile cross-organization challenge.

Files:

- `frontend/e2e/launcher.mjs`
- `frontend/e2e/launcher.test.mjs`
- `frontend/e2e/phase-b1-lead-intelligence.spec.ts`
- `frontend/src/modules/leads/LeadDetailDialog.vue`
- `frontend/src/modules/leads/LeadDetailDialog.test.ts`

### OpenAPI and generated client

The Phase B1 endpoint implementations and atomic generator predated Task 12, so the new acceptance assertions were characterization coverage rather than a fabricated product RED. The focused backend OpenAPI set passed 11/11. `pnpm api:generate` followed by `pnpm api:check` passed; the regenerated `schema.ts` was identical, so Git correctly contains no generated-artifact diff. Atomic replacement and Node lifecycle tests passed 3/3, and typecheck passed. No tracked schema JSON or temporary file remains.

Files:

- `backend/tests/test_openapi.py`
- `backend/tests/test_openapi_contract.py`

## Final verification

| Gate | Exact result |
| --- | --- |
| Task 12 focused backend combination | 18 passed in 7.54s |
| Complete backend | 1185 passed, 1 skipped in 194.19s |
| Complete frontend | 34 files, 308 passed |
| Frontend typecheck | exit 0 |
| Frontend lint | exit 0 |
| Production build | exit 0; 150 modules transformed |
| OpenAPI generate/check | both exit 0; zero drift |
| OpenAPI atomic/lifecycle | 3 passed |
| E2E launcher unit tests | 6 passed |
| Django system / migration drift checks | no issues; no changes detected |
| Ruff on Task 12 Python files | check passed; 10 files formatted |
| Browser acceptance | 7 passed; Playwright portion 31.9s |
| Docker Compose configuration | unavailable: `docker` command not found |

The first complete-backend invocation hit the command runner's 124-second timeout with no test-failure output. It was rerun under a 360-second window and completed green. Docker was not silently skipped or reported as passing.

## Limits and ownership

- Supported intake is public URL/text, screenshot, UTF-8 CSV, JSON rows, and tab-separated paste.
- The acceptance performs no third-party crawling, authentication bypass, paid-model call, outreach, private-contact discovery, or CRM mutation.
- Transient public evidence follows `TRANSIENT_30D`; protected/reviewed/completed-analysis evidence fails closed against cleanup, and redaction retains safe tombstone/audit identity.
- Phase B2 owns company enrichment, outreach, and handoff.
