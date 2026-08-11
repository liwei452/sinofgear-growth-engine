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

## Fix Round 1 (2026-08-11)

### Review findings closed

- Critical — test-provider reachability and semantic grounding: `schema-fake` is no longer registered or retrievable under ordinary settings. `SINO_PHASE_B1_SCHEMA_FAKE_ALLOWED` defaults to false, `.env.example` documents the safe value, and only the isolated E2E settings enable it automatically. `seed_phase_b1` checks the gate before any write. The deterministic provider now emits requirements and capability matches only from explicit source evidence; ordinary thanks is insufficient evidence with empty optional arrays. Output validation independently rejects requirement values/units and recognizable capability codes that are not supported by their cited frozen evidence.
- Important — evidence quality: evaluator references are bounded exact substrings from the original English or Chinese source, never a normalized full-text shortcut. Four held-out/adversarial examples cover unfamiliar procurement wording and a consultant-recruitment negative. The 100-row metric remains an offline fixture-regression claim only.
- Important — seed ownership: a rerun validates the complete owned contract instead of treating existence as success. Candidate/evidence/status, analysis job, frozen snapshot, prompt/run/binding, generated insight, review correction, and intentionally failed job are checked fail closed. Independent candidate, insight, review, and job tampering tests prove collisions are refused and not silently repaired.
- Important — organization isolation: both candidate creation with real foreign evidence and analysis of an owned candidate with real foreign evidence return `404` without leaking organization, company, candidate, or evidence content. Malformed or unlinked same-organization evidence remains `400`, preserving the distinction between invisibility and validation.
- Minor — acceptance and handoff claims now distinguish the isolated fixture from production execution, bound the fake provider's tested JSON Schema shapes, and explain the limited evaluation/held-out evidence.

### TDD record

- Provider gate and grounding RED: 4 failures demonstrated default registry reachability, a seed write path without a gate, invented requirement content, and fabricated optional arrays. GREEN: 9 passed. The provider plus frozen-analysis snapshot set then passed 14/14.
- Evidence-window RED: 5 failures demonstrated full-source evidence, three unfamiliar procurement false negatives, and a consultant-recruitment false positive. GREEN: 6 passed with exact bounded excerpts and all held-out/adversarial cases correct.
- Seed-collision RED: 4 independent tampering cases were silently accepted. GREEN: 8 passed after complete contract validation for candidate, insight, review, and failed job.
- Isolation RED: 2 failures demonstrated that real foreign evidence returned validation `400`. GREEN: 4 focused API cases passed with the required `404` behavior and same-organization `400` controls.
- Broader lead/provider/seed regression set: 79 passed after preserving support for opaque ontology capability codes while validating recognizable `CAP-*` semantics.

### Final verification

| Gate | Exact result |
| --- | --- |
| Focused provider/evaluation/seed-collision/isolation/OpenAPI suite | 73 passed in 10.75s |
| Complete backend pytest | 1200 passed, 1 skipped in 205.42s |
| Django system / migration drift | no issues; no changes detected |
| Full Ruff lint | passed |
| Changed Python file formatting | 10 formatted; 3 already formatted; subsequent focused/full tests passed |
| OpenAPI generate / drift | passed; generated client remained current |
| OpenAPI atomic / lifecycle | 3 passed |
| Complete frontend Vitest | 34 files, 308 passed in 16.79s |
| Frontend typecheck / ESLint | both exit 0 |
| Production build | exit 0; 150 modules transformed |
| E2E launcher unit tests | 6 passed |
| Complete browser suite | 7 passed; Playwright portion 32.0s |
| Docker Compose configuration | unavailable: `docker` executable is not installed or available on `PATH` |

The first direct frontend attempt followed `C:\Users\Administrator\.local\bin\node.cmd`, whose target no longer existed. All recorded successful frontend and browser results used the bundled Codex Node 24.14.0 directory on `PATH`. Docker was probed explicitly and is recorded as unavailable, not passing. No plan or progress-ledger file was modified.

### Supported boundary after the fix

The accepted result is an isolated, disposable local fixture using the product's audited orchestration service interfaces. It does not prove a live production model, a live connector, or broad evaluator generalization. The fake provider covers only schema shapes exercised by its tests and makes no claim for complete JSON Schema features such as `$ref`, compositions, or pattern semantics.
