# DeepSeek V4 Provider Acceptance

Date: 2026-08-12
Scope: DeepSeek V4 provider, administrator configuration, audited orchestration, and isolated browser acceptance.

## Acceptance status

The free, deterministic acceptance suite exercises the same provider and orchestration contracts as normal content generation and lead analysis. The browser run uses an owned temporary database, an in-memory credential adapter, and an `httpx.MockTransport`. All three are enabled only when the generated ownership secret and the DeepSeek E2E gate match. Ordinary and production settings fail closed.

No real DeepSeek credential was read, no public endpoint was contacted, and no paid request was made during automated acceptance.

| Area | Result |
| --- | --- |
| DeepSeek settings: success, safe invalid-key/balance/rate-limit errors, deletion | PASS |
| Organization isolation and permission denial | PASS |
| Content generation through DeepSeek orchestration | PASS |
| Lead analysis through DeepSeek orchestration | PASS |
| Provider identity, model, usage and audit visibility | PASS |
| API key and reasoning-content non-disclosure | PASS |
| Production rejection of E2E adapters | PASS |
| Reservation mismatch anomaly persisted to provider-call and AIRun audit | PASS |
| Paid real-provider smoke | PENDING explicit user approval |

Automated counts and exact commands are recorded in `.superpowers/sdd/2026-08-12-deepseek-v4-provider/task-9-report.md`.

## Security boundary

- Credentials are submitted only to the configuration endpoint and never returned by the API or UI.
- Normal Windows operation uses Windows Credential Manager. The E2E memory store is unavailable without the owned-run gate.
- Mock HTTP responses are unavailable unless the same ownership gate is active.
- The fake transport emits a reasoning field deliberately; acceptance verifies it is discarded and never shown or audited.
- Test fixtures construct credential-shaped placeholders at runtime instead of committing a usable or real-looking key.
- Provider errors are mapped to safe categories; upstream bodies and secrets are not exposed.

## Manual paid smoke record

Leave this record blank until the user is present, has entered the credential through the UI, and explicitly approves the paid call. Never record the API key, credential suffix, raw prompt, raw provider response, or reasoning content here.

| Field | Value |
| --- | --- |
| Status | PENDING |
| Date/time |  |
| Operator |  |
| Organization |  |
| AIRun ID |  |
| Model |  |
| Thinking enabled |  |
| Input tokens |  |
| Output tokens |  |
| Estimated cost |  |
| Outcome / controlled error category |  |

The approved command is documented in `docs/operations/deepseek-windows.md`. Stop after a controlled failure; do not silently substitute the fake provider or the Pro model.

## Handoff decision

The integration is ready for an explicit real-provider smoke test and, after that result is reviewed, Windows installer planning. It is not evidence that a paid DeepSeek call has succeeded yet.
