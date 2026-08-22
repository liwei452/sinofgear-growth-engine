# Knowledge A3.2 Unified Agent Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan inline, task by task, with test-driven development. Do not dispatch subagents for this unattended run.

**Goal:** Make lead judgment, outreach, content strategy, master generation, and platform variants consume one immutable, tenant-validated `KnowledgeContextSnapshot` for a Mission.

**Architecture:** Add one `apps.knowledge.agent_context` boundary that loads or builds a Mission snapshot, validates ownership and integrity, and returns immutable purpose-scoped DTOs. Mission entry points freeze the snapshot once; downstream records inherit its FK, while Job/AIRun/provenance JSON carry only the compact ID/hash/schema/builder tuple plus the restricted projection needed for generation.

**Tech stack:** Django 5.2, frozen dataclasses, canonical JSON/SHA-256, pytest-django, existing `tenant_atomic`, Job, AIRun, and content lifecycle services.

**Spec:** User-provided Knowledge A3.2 task brief dated 2026-08-22; this file records the audited design and executable plan requested by that brief.

## Global constraints

- Start from `ea7e66a1a108e8f2279ad72f115bf4cce294d5e5` in `feature/knowledge-context-a3-2`; never alter the main worktree or protected branches.
- Do not modify `apps/common/rls_manifest.py`, RLS-2A.2 policy/migration/tests/docs/infrastructure, or published knowledge migrations `0004` through `0008`.
- No real LLM, email, Buffer/createPost, force push, or formal-branch merge.
- ORM work stays inside trusted tenant transactions; provider calls stay outside database transactions using prepare/call/finalize.
- Missing knowledge configuration, mismatches, corrupt payloads, invalid citations, prohibited claims, and missing verified pages fail closed with structured safe codes.
- New tests stay within 25–30 collected cases and focus on high-risk boundaries; no repeated local full-suite, frontend build, or E2E runs.

## Audited context and provenance map

| Chain | Current source | Snapshot load or inheritance | Provenance target |
|---|---|---|---|
| Lead judgment | Candidate/enrichment/website facts plus a hard-coded industrial-gear buyer prompt and deterministic fallback | Mission acquisition start loads/builds once; `LEAD_JUDGMENT` projection clearly separates seller company/product/ICP/Mission from target-company evidence | `AgentRun.knowledge_context_snapshot`; compact tuple in frozen call metadata |
| Outreach | TargetAccount + latest intent signal + generic capability-summary template | Reuse the acquisition AgentRun snapshot; `OUTREACH` exposes public claims/product public context, ICP guidance, prohibited claims, and one verified CTA/page | `OutreachDraft.knowledge_context_snapshot`; same AgentRun FK |
| Content strategy / Brief | Mutable Mission fields, opportunity signals, caller overrides, default CTA, blank landing page | Mission strategy run loads/builds once; `CONTENT_STRATEGY` deterministically derives Mission-bound fields and rejects EMAIL-only or incomplete configuration | `AgentRun.knowledge_context_snapshot`; `ContentBrief.knowledge_context_snapshot` |
| Master content | Mutable Brief links, Product snapshots, ontology, assets, and verified product evidence | Validate the Brief's exact snapshot and project `MASTER_CONTENT`; keep bounded assets/platform/ontology alongside restricted immutable knowledge | Job/AIRun input snapshot; `MasterContent.knowledge_context_snapshot`; provenance tuple |
| Platform variant | Child Job has only master/actor and reads master/brief | Inherit the Master's exact snapshot and compact provenance; load it for validation only, never build it or query mutable company/fact/ICP/page sources | Child Job input/result metadata; `PlatformContent.knowledge_context_snapshot`; provenance tuple |

## Data boundary

| Data class | Lead judgment / strategy reasoning | Outreach / master / platform external copy |
|---|---:|---:|
| Company profile and product public fields | allowed | allowed through bounded snapshot projection |
| `public_claims` with fact ID and evidence citation | allowed | allowed; cited IDs must be in the projection |
| `internal_context` | allowed | forbidden as copy or cited external evidence |
| `prohibited_claims` | hard constraint | hard constraint plus deterministic post-generation rejection |
| Target-company evidence | allowed in a separately labelled section | personalization only; never seller-capability evidence |
| Credentials, tokens, Authorization, raw provider response/error | forbidden | forbidden |

Landing-page selection accepts only canonical or CTA URLs present in the snapshot's verified `website_pages`. No domain/path concatenation or product `landing_page_url` fallback is allowed. After a snapshot is loaded, consumers must not query CompanyFact, ICPProfile, or WebsitePage to supplement it.

## Task 1: Unified immutable consumer

**Files:** create `backend/apps/knowledge/agent_context.py`; extend `backend/apps/knowledge/tests/test_agent_context.py`.

- [ ] Keep the existing RED consumer/security tests failing specifically because the module/API is absent.
- [ ] Implement `AgentContextPurpose`, frozen DTOs, structured `KnowledgeContextError`, `load_or_build_agent_context`, `load_agent_context`, purpose projection, and compact provenance.
- [ ] Validate tenant, Mission, primary product, supported schema, canonical payload hash/size, forbidden nested keys, stable ordering, bounded output size, verified pages, public citations, internal-source exclusion, and prohibited text.
- [ ] Run `uv run pytest -q apps/knowledge/tests/test_agent_context.py apps/knowledge/tests/test_knowledge_context_snapshot.py` and keep the new cases green.

## Task 2: Strong provenance links

**Files:** modify `backend/apps/growth/models.py`, `backend/apps/campaigns/models.py`, `backend/apps/content/models.py`; create `growth/0049_*`, `campaigns/0004_*`, and `content/0006_*` migrations.

- [ ] First add failing model/service tests for cross-tenant and parent-chain Snapshot mismatch plus revision inheritance.
- [ ] Add nullable, legacy-compatible `PROTECT` FKs named `knowledge_context_snapshot` to AgentRun, OutreachDraft, ContentBrief, MasterContent, and PlatformContent.
- [ ] Validate organization/Mission/product and parent-chain equality in service writes; copy the FK through revisions instead of copying payloads.
- [ ] Make each new migration depend on that app's current leaf and `knowledge.0008`; do not edit historical migrations or RLS manifests.

## Task 3: Ground lead judgment and outreach

**Files:** modify `backend/apps/growth/lead_judgment.py`, `backend/apps/growth/services.py`, `backend/apps/growth/agent/acquisition.py`, and focused growth tests.

- [ ] Add failing tests showing a Mission run freezes one Snapshot, seller/target inputs are separated, provider calls occur outside transactions, generic Mission fallback is rejected, only verified URLs are selected, citations survive, prohibited/internal claims fail closed, and AgentRun/OutreachDraft share the FK.
- [ ] Load/build the snapshot before AgentRun creation and pass the immutable projections into judgment and outreach tools.
- [ ] Preserve non-Mission legacy APIs, but prevent legacy fields from overriding Mission knowledge.
- [ ] Preserve DRAFT/human-review/no-send behavior; never send email.

## Task 4: Ground content strategy and ContentBrief

**Files:** modify `backend/apps/growth/agent/content_tools.py`, `backend/apps/campaigns/services.py`, and focused campaign/growth tests.

- [ ] Add failing tests for deterministic Brief fields, EMAIL-only behavior, missing product/ICP/platform/page failure, idempotency, and Snapshot provenance.
- [ ] Replace `_mission_context` and caller-controlled Mission defaults with `CONTENT_STRATEGY` output for country, customer type, objective, language, CTA/page, prohibited claims, public selling points/advantages, keywords, product, ICP, and allowed social channels.
- [ ] Preserve platform mapping, `platform_links`, Mission links, and non-Mission legacy behavior.

## Task 5: Ground master and platform generation

**Files:** modify `backend/apps/campaigns/services.py`, `backend/apps/campaigns/generation_schema.py`, `backend/apps/ai/orchestration.py`, `backend/apps/content/tasks.py`, `backend/apps/content/services.py`, `backend/apps/growth/agent/content_creation_tools.py`, and focused content/AI tests.

- [ ] Add failing tests that Job/AIRun prompts carry the restricted Snapshot projection and compact tuple, mock providers run outside atomic blocks, invalid cited IDs/prohibited text/page URLs fail the Job without creating content, and platform variants inherit the exact Snapshot without rebuilding.
- [ ] Extend `ContentGenerationInput` and schema with knowledge provenance and restricted master context; validate organization/product/hash before Job creation and prompt rendering.
- [ ] Validate generated cited fact IDs against public claims and normalized prohibited claims before MasterContent creation.
- [ ] Copy the same FK/provenance through Master and Platform revisions and child Job input/result metadata; keep independent child Job retry/idempotency and master/platform status isolation.
- [ ] Do not change Publishing/Buffer state machines, approval/publish behavior, or call createPost.

## Task 6: Review and delivery

- [ ] Review the complete diff for tenant isolation, actual Snapshot consumption, hard-coded seller/domain/gear defaults, public/internal/prohibited leakage, provenance gaps, platform rebuilding, provider-in-transaction calls, unsafe fallbacks, secret/provider leakage, and lifecycle regressions.
- [ ] Fix all Critical/Important findings with the smallest failing regression test first.
- [ ] Run new and directly affected tests, Ruff on changed Python files, `makemigrations --check --dry-run`, and `git diff --check`. Run OpenAPI/frontend checks only if their contracts changed.
- [ ] Commit in 3–5 logical commits; fetch and normally merge an advanced `origin/feature/database-rls-phase2`; push without force; create a Draft PR targeting `feature/database-rls-phase2`; wait for CI and fix only task-related failures.

## Test budget and baseline note

- Consumer/security: 8–10 collected cases.
- Growth judgment/outreach/strategy: 8–10 collected cases.
- Master/platform/provenance/transaction: 8–10 collected cases.
- Total new collected cases: 25–30 maximum, using parametrization where it improves clarity.
- Baseline on 2026-08-22: 46 direct tests passed and one pre-existing `test_retry_redispatches_platform_variants_job` failed because `dispatch_task_on_commit` defers eager retry until the request transaction commits. This Jobs/RLS-2A.1 test issue predates A3.2 and is outside the allowed modification scope.
