# Evidence-Grade Opportunity Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every customer opportunity explain its evidence score, provenance, uncertainty, and saved follow-up history without adding real collection or outbound delivery.

**Architecture:** Extend the organization-owned `IntentSignal` record with structured evidence metadata and a versioned score breakdown, expose those fields through the existing read-only growth workspace API, then render them in the current two-column opportunity page. Existing follow-up and outreach draft records provide the lightweight timeline; no CRM state machine or sending endpoint is added.

**Tech Stack:** Django 5.2, Django REST Framework, SQLite/PostgreSQL-compatible migrations, Vue 3, TypeScript, TanStack Vue Query, Vitest, Testing Library, Playwright.

## Global Constraints

- Only modify `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`.
- Do not access, modify, build, or test `C:\Users\Administrator\Documents\网站\app`.
- Do not fetch external sources, scrape LinkedIn, buy data, send messages, or expose a sending control.
- All current opportunity fixtures remain visibly labeled `Demo / Fake` and use `example.invalid` URLs.
- A score is “优先跟进” only when total score is at least 80 and `evidence_coverage` is at least 15.
- Outreach drafts remain `NEVER_SENT`; CRM remains an optional later export.

---

### Task 1: Persist structured evidence and scoring

**Files:**
- Modify: `backend/apps/growth/models.py`
- Create: `backend/apps/growth/migrations/0003_intentsignal_evidence_metadata.py`
- Modify: `backend/apps/common/management/commands/seed_phase_a.py`
- Test: `backend/apps/growth/tests/test_opportunity_evidence.py`

**Interfaces:**
- Produces: `IntentSignal.collection_method`, `content_hash`, `score_breakdown`, `scoring_rule_version`, and `uncertainty_notes`.
- Score keys: `icp_fit`, `intent_strength`, `recency`, `role_relevance`, `evidence_coverage`, `risk_penalty`.

- [ ] **Step 1: Write failing model tests**

```python
def test_seeded_signal_has_versioned_evidence_metadata(seeded_signal):
    assert seeded_signal.collection_method == "DEMO_FIXTURE"
    assert re.fullmatch(r"[0-9a-f]{64}", seeded_signal.content_hash)
    parts = seeded_signal.score_breakdown
    assert sum(parts[key] for key in POSITIVE_KEYS) - parts["risk_penalty"] == seeded_signal.confidence
    assert seeded_signal.scoring_rule_version == "opportunity-v1"
    assert seeded_signal.uncertainty_notes
```

- [ ] **Step 2: Run the test and verify missing fields fail**

Run: `.\.venv\Scripts\python.exe -m pytest apps\growth\tests\test_opportunity_evidence.py -q`

- [ ] **Step 3: Add fields and migration**

```python
collection_method = models.CharField(max_length=32, default="DEMO_FIXTURE")
content_hash = models.CharField(max_length=64, blank=True)
score_breakdown = models.JSONField(default=dict)
scoring_rule_version = models.CharField(max_length=64, default="opportunity-v1")
uncertainty_notes = models.JSONField(default=list)
```

Seed each signal with `hashlib.sha256(evidence.encode("utf-8")).hexdigest()` and an exact score breakdown whose positive components minus `risk_penalty` equal `confidence`.

- [ ] **Step 4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest apps\growth\tests\test_opportunity_evidence.py apps\common\tests\test_seed_phase_a.py -q`

- [ ] **Step 5: Commit**

```text
feat: persist opportunity evidence scoring
```

### Task 2: Expose safe, validated evidence details

**Files:**
- Modify: `backend/apps/growth/serializers.py`
- Test: `backend/tests/test_growth_workspace_api.py`

**Interfaces:**
- Consumes: Task 1 `IntentSignal` fields.
- Produces: API fields `collection_method`, `collection_method_label`, `content_hash`, `score_breakdown`, `scoring_rule_version`, `uncertainty_notes`, and `priority_label`.

- [ ] **Step 1: Write failing API assertions**

```python
signal = response.data["intent_signals"][0]
assert signal["collection_method_label"] == "本地演示样本"
assert signal["priority_label"] in {"优先跟进", "继续观察"}
assert signal["score_breakdown"]["evidence_coverage"] >= 0
assert len(signal["content_hash"]) == 64
```

Add a low-evidence score-90 fixture and assert `priority_label == "继续观察"`.

- [ ] **Step 2: Run the API tests and verify missing fields fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_growth_workspace_api.py -q`

- [ ] **Step 3: Implement serializer methods**

```python
def get_priority_label(self, obj):
    coverage = int((obj.score_breakdown or {}).get("evidence_coverage", 0))
    return "优先跟进" if obj.confidence >= 80 and coverage >= 15 else "继续观察"
```

Map collection methods to Chinese labels and return stored evidence fields without generating replacements for missing values.

- [ ] **Step 4: Run growth backend tests**

Run: `.\.venv\Scripts\python.exe -m pytest apps\growth tests\test_growth_workspace_api.py -q`

- [ ] **Step 5: Commit**

```text
feat: expose explainable opportunity evidence
```

### Task 3: Render evidence explanation and saved timeline

**Files:**
- Modify: `frontend/src/modules/growth/api.ts`
- Modify: `frontend/src/modules/growth/OpportunitiesPage.vue`
- Modify: `frontend/src/modules/growth/growth-pages.css`
- Test: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Consumes: Task 2 API fields and existing `follow_ups` / `outreach_drafts`.
- Produces: score breakdown panel, safe evidence link, uncertainty list, and per-account follow-up timeline.

- [ ] **Step 1: Add failing component tests**

```typescript
expect(await screen.findByText("评分依据")).toBeInTheDocument()
expect(screen.getByText("证据覆盖 18")).toBeInTheDocument()
expect(screen.getByText("从未发送")).toBeInTheDocument()
expect(screen.getByText("采购时间仍需人工确认")).toBeInTheDocument()
```

Also assert an `http://` source is rendered without a link and a score of 90 with evidence coverage 10 displays “继续观察”.

- [ ] **Step 2: Run the focused component test and verify it fails**

Run: `node node_modules/vitest/vitest.mjs --run src/modules/growth/GrowthWorkspacePages.test.ts`

- [ ] **Step 3: Add typed API fields and UI sections**

Define `OpportunityScoreBreakdown` and extend `IntentSignal`. Use the API `priority_label`; do not derive priority from total score alone. Render English draft and Chinese explanation in separate blocks, choose the newest saved draft for the active account, and format dates with `Intl.DateTimeFormat("zh-CN")`.

- [ ] **Step 4: Add focused styles**

Keep the current card hierarchy. Use a compact six-cell score grid at desktop widths and a single column below the existing mobile breakpoint. Evidence links use `target="_blank" rel="noopener noreferrer"` only when `source_url` starts with `https://`.

- [ ] **Step 5: Run focused tests, typecheck, and lint**

Run: `node node_modules/vitest/vitest.mjs --run src/modules/growth/GrowthWorkspacePages.test.ts`

Run: `node node_modules/vue-tsc/bin/vue-tsc.js --noEmit`

Run: `node node_modules/eslint/bin/eslint.js .`

- [ ] **Step 6: Commit**

```text
feat: explain customer opportunity evidence
```

### Task 4: Browser persistence and full verification

**Files:**
- Modify: `frontend/e2e/zz-growth-workspace-persistence.spec.ts`
- Modify: `docs/acceptance/2026-08-14-growth-workspace.md`

**Interfaces:**
- Consumes: completed API and UI behavior.
- Produces: browser evidence that details switch per company and follow-up/draft state survives reload.

- [ ] **Step 1: Extend the browser test**

```typescript
await page.getByRole("button", { name: /PackTech GmbH/ }).click()
await page.getByRole("button", { name: "查看证据" }).click()
await expect(page.getByText("评分依据")).toBeVisible()
await expect(page.getByText("从未发送")).toBeVisible()
await page.reload()
await expect(page.getByRole("button", { name: "已加入跟进" })).toBeDisabled()
```

- [ ] **Step 2: Run focused browser acceptance**

Run the owned launcher for `zz-growth-workspace-persistence.spec.ts`; expect one passing test and automatic cleanup of its temporary directory.

- [ ] **Step 3: Run full verification**

Run backend pytest, Ruff, Django check, and migration drift checks. Run frontend Vitest, TypeScript, ESLint, and Vite build. Verify `http://127.0.0.1:3001/opportunities` and `/api/v1/health` both return 200.

- [ ] **Step 4: Update acceptance evidence and commit**

Record exact test counts, browser result, known Demo-only boundary, and the new evidence scoring fields.

```text
test: verify evidence-grade opportunity flow
```
