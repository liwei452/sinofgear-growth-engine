# SinofGear DeepSeek V4 Provider Design

**Date:** 2026-08-12  
**Status:** Approved design  
**Scope:** Add a production DeepSeek provider to the existing audited AI execution layer. This design does not add live social-platform connectors, CRM transmission, or a free-form chatbot.

## 1. Goals

- Replace deterministic AI with a real provider for explicitly configured production work.
- Keep the existing `PromptVersion`, `AIRun`, `Job`, ontology snapshot, evidence, human-review, retry, and organization-isolation boundaries.
- Default to a fast, economical model and escalate only work that benefits from deeper reasoning.
- Make first-time configuration understandable to a non-technical Windows user.
- Prevent API keys, chain-of-thought, or provider secrets from entering Git, application data, logs, audit payloads, exports, or installer artifacts.
- Fail honestly. A provider failure must never be reported as successful work and must never silently fall back to a fake model.

## 2. Model Policy

The provider uses DeepSeek's current V4 model identifiers rather than the retired legacy aliases.

| Work class | Model | Thinking | Typical use |
| --- | --- | --- | --- |
| Standard | `deepseek-v4-flash` | disabled | Content generation, translation, summaries, routine lead analysis |
| Complex | `deepseek-v4-pro` | enabled | Low-confidence leads, conflicting evidence, difficult market reasoning |

Routing is deterministic and auditable. A versioned server-side policy chooses the work class from task type, evidence quality, confidence thresholds, and explicit administrator override. The model cannot promote its own request to a more expensive route.

Reasoning effort for complex requests is bounded by policy. Internal reasoning content is discarded immediately and is never stored or returned through the product API. Only the final structured result and verifiable evidence are persisted.

## 3. Provider Boundary

Add a `DeepSeekProvider` behind the existing `AIProvider.generate(prompt, schema)` contract. The orchestration layer remains provider-independent.

The provider will:

1. receive a rendered prompt and JSON Schema from existing orchestration;
2. select model and thinking mode from an immutable routing decision;
3. send a non-streaming Chat Completions request to `https://api.deepseek.com`;
4. explicitly request JSON output and include a direct instruction to return JSON;
5. apply connection and response timeouts;
6. parse only the final `content` field;
7. reject empty, truncated, non-JSON, or schema-invalid responses;
8. return a Python dictionary to the existing orchestration layer.

Transport code must not know about products, leads, campaigns, or organizations. Grounding, ontology snapshots, schema validation, evidence checks, and finalization remain in their existing domain services.

## 4. Credential Storage and First-Run Setup

The Windows application presents a Chinese first-run setup wizard to administrators:

1. paste the DeepSeek API key into a masked field;
2. run a low-cost connection test;
3. save only after the test succeeds;
4. show `已连接` and the final four characters afterward;
5. allow administrators to replace, retest, or delete the credential.

The key is stored per Windows user in Windows Credential Manager. The database stores only non-secret connection metadata: provider code, connection state, masked suffix, last successful test time, and the user who changed the configuration.

The complete key must never be:

- written to `.env`, source files, Git, SQLite/PostgreSQL, Redis, job arguments, audit records, exception text, HTTP responses, analytics, exports, or installer files;
- exposed through the ordinary or advanced UI;
- returned to the frontend after it has been submitted;
- copied automatically when the application is moved to another computer.

Each Windows computer requires the administrator to enter the key again. Credential reads occur only inside the trusted local backend process. Logs and persisted errors pass through the existing redaction and size limits, extended with DeepSeek-specific token patterns and authorization-header removal.

## 5. Connection Test

The connection test is an explicit administrator action and may incur a very small charge. It sends a minimal structured request using `deepseek-v4-flash` with thinking disabled and a strict low output limit.

Success requires:

- an authenticated response;
- a non-empty JSON object matching the test schema;
- no secret material in provider metadata or logs.

The UI distinguishes invalid key, insufficient balance, rate limit, provider overload, network failure, and timeout. It never saves an unverified key. Retesting an already saved key does not reveal the key to the frontend.

## 6. Routing and Overrides

The routing policy is versioned and stored by code/version, not arbitrary user-authored JSON.

Standard tasks use V4 Flash. Complex routing is allowed when one of these conditions applies:

- lead evidence is conflicting or below the configured confidence threshold;
- an existing domain evaluator marks the case as ambiguous;
- the task type is explicitly designated for complex market reasoning;
- an administrator selects `使用增强分析` before submission.

The final routing decision is frozen into the job input snapshot and `AIRun` metadata before the provider call. Retrying a job reuses that frozen decision unless an administrator explicitly creates a new attempt with a new policy version. Ordinary users cannot select a model directly.

## 7. Cost, Token, and Time Controls

Configuration has safe server-side defaults and administrator-editable ceilings:

- daily organization spending ceiling;
- maximum input size per task;
- maximum output tokens by work class;
- request timeout;
- maximum paid attempts per idempotent business intent;
- permission required for complex-model override.

Usage accounting records provider request ID when safe, model, thinking mode, input tokens, output tokens, cache-hit tokens when reported, finish reason, duration, and estimated cost. It never records authorization headers or internal reasoning.

The backend reserves estimated budget atomically before a paid call and reconciles it with actual usage afterward. When the daily ceiling is reached, new calls stop with a recoverable Chinese message. Concurrent workers cannot exceed the ceiling through a check-then-call race.

## 8. Structured Output and Grounding

Every production call remains schema-first:

- the prompt explicitly requires JSON;
- the API requests `json_object` output;
- JSON is parsed with size and nesting limits;
- the existing JSON Schema is applied;
- domain validators check organization ownership, ontology codes, evidence identifiers, and allowed claims;
- lead conclusions must cite frozen visible evidence;
- capability claims must retain the existing supporting knowledge-evidence requirement.

If the first response is syntactically or structurally invalid, the provider may make one repair request using the same frozen input, model, and budget intent. The repair prompt contains only the validation summary and the original safe input; it does not include secrets or raw exception traces. A second invalid response fails the `AIRun` and `Job`.

## 9. Error and Retry Policy

| Condition | Automatic action | User guidance |
| --- | --- | --- |
| Invalid or revoked key | No retry | Ask administrator to replace and test the key |
| Insufficient balance | No retry | Ask administrator to recharge the DeepSeek account |
| Rate limited | Up to 2 delayed retries | Show waiting state and next attempt |
| Provider overload or 5xx | Up to 2 delayed retries | Allow later manual retry |
| Network failure or timeout | Up to 2 delayed retries when safe | Check network, then retry |
| Invalid JSON/schema | One bounded repair request | Escalate to human review if repair fails |
| Budget ceiling reached | No paid call | Ask administrator to raise the ceiling or wait for reset |
| Canceled job | Stop and do not finalize | Allow a new explicit attempt |

Retries use bounded exponential backoff with jitter and the existing idempotency identity. The system must not charge twice because a client repeated a submission. Provider requests that may have completed after a local timeout are reconciled conservatively; ambiguous outcomes are not reported as success.

## 10. Audit and Privacy

Each `AIRun` records:

- provider `deepseek`;
- actual model and thinking-mode flag;
- routing-policy code and version;
- prompt version;
- frozen safe input snapshot;
- ontology snapshot;
- final structured output;
- confidence and human correction;
- usage, estimated cost, timing, finish reason, and safe provider metadata;
- normalized error and recovery action when failed.

Internal reasoning content is intentionally neither persisted nor displayed. Audit answers “what data, rule, model, evidence, result, usage, and human correction were involved” without exposing private chain-of-thought or credentials.

## 11. User Experience

Ordinary mode does not expose model names during normal work. It shows understandable states such as:

- `正在生成推广内容`;
- `正在分析客户机会`;
- `需要增强分析，等待管理员批准`;
- `AI服务繁忙，系统将在稍后重试`;
- `今日AI费用已达到上限`.

Administrators get a provider settings page containing connection status, masked key suffix, last test, default/complex model policy, daily ceiling, recent usage, and safe recovery actions. It contains no raw prompt editor and no complete credential display.

## 12. Test Strategy

Automated tests remain free and deterministic. Unit, integration, backend, frontend, and browser suites use fake HTTP transports or the existing gated deterministic provider. They never read a developer's real credential and never call a paid endpoint.

Coverage includes:

- V4 Flash and V4 Pro request shapes;
- thinking disabled/enabled behavior;
- JSON-output instruction and parsing;
- invalid key, balance, rate limit, overload, timeout, truncated output, invalid JSON, and schema failure;
- retry and single-repair limits;
- atomic daily budget reservation under concurrency;
- idempotent duplicate submission;
- secret redaction from logs, errors, jobs, audits, APIs, exports, and UI;
- organization and permission isolation;
- Windows credential create/read/replace/delete through an adapter with a fake test implementation;
- setup wizard, masked status, administrator-only controls, and accessible recovery messages.

A separate manual smoke test, run only after explicit confirmation, uses the saved real key to test connectivity and one representative content-generation task. The result records real model and usage metadata but never the key or reasoning content.

## 13. Installation Boundary

The future Windows installer bundles application code and the credential adapter, but no DeepSeek key. First-run setup occurs after installation. Uninstalling offers a clear choice to remove the locally stored credential and application data. Moving or reinstalling the software never silently exports the credential.

## 14. Out of Scope

- Free-form general chatbot behavior.
- Autonomous model selection without deterministic policy.
- Storing or displaying chain-of-thought.
- Live social-platform connectors or browser scraping.
- CRM transmission.
- Cloud synchronization of Windows credentials.
- Provider fallback to another paid model.

## 15. Acceptance Criteria

The integration is ready for installer work when:

1. an administrator can securely configure, test, replace, and delete a DeepSeek key;
2. production content generation and lead analysis use the expected V4 route;
3. structured output, ontology, and evidence validation remain enforced;
4. retry, repair, idempotency, cancellation, and budget controls pass automated tests;
5. no secret or reasoning content appears in persistent state or user-visible APIs;
6. all existing free deterministic suites remain green;
7. the explicit paid smoke test succeeds and its actual provider/model/usage are visible in the audit record;
8. failure scenarios display truthful Chinese recovery guidance and never report fake success.
