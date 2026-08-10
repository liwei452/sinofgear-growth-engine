# AI Decision Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing single application into a beginner-friendly AI decision cockpit with guided public-signal import, evidence-first customer opportunities, and progressive access to advanced administration pages.

**Architecture:** Keep one Vue application and one backend. Add a typed `leads` frontend module over the generated OpenAPI contract, then compose it into an import dialog, opportunity queue, evidence review dialog, and five-entry ordinary navigation. Advanced mode only changes navigation visibility; both modes share routes, permissions, Vue Query caches, organization isolation, and audit history.

**Tech Stack:** Vue 3, TypeScript, Vue Router, TanStack Vue Query, Vitest, Testing Library, MSW, Playwright, generated OpenAPI types, existing CSS design tokens.

## Global Constraints

- This plan supersedes the UI details in Tasks 10 and 11 of `2026-08-10-phase-b1-lead-intelligence-foundation.md`; Task 12 acceptance work remains after this plan.
- Ordinary navigation labels are exactly `今天`, `推广`, `客户机会`, `效果`, and `公司资料`.
- The existing SinofGear blue `#005BA8` remains the primary brand color; do not add a second UI framework or icon dependency.
- Public-signal collection is user-scoped only: no autonomous third-party login, scraping, or outbound messaging.
- AI scores and evidence sufficiency are displayed separately; inferred company facts are labelled `待确认`.
- Every Vue Query key that holds organization data includes the current organization ID.
- Use generated OpenAPI component types; do not hand-edit `frontend/src/api/generated/schema.ts`.
- Preserve keyboard navigation, focus restoration, `aria-live` progress, safe HTTP(S) external links, and responsive layout.
- All work is test-first. Each task ends with focused tests, typecheck, lint, and a clean commit.

---

### Task 10A: Typed customer-opportunity API boundary

**Files:**
- Create: `frontend/src/modules/leads/api.ts`
- Create: `frontend/src/modules/leads/api.test.ts`

**Interfaces:**
- Consumes: `components["schemas"]["LeadCandidateList"]`, `LeadCandidateDetail`, `LeadCandidatePage`, `IngestionBatchCreate`, `IngestionAccepted`, `Job`, `LeadAnalyzeRequest`, `LeadAnalyzeAccepted`, `LeadReviewCreate`, and `LeadReviewResult` from the generated schema.
- Produces: `leadKeys`, `LeadFilters`, `ImportDraft`, `ImportPreview`, `safeLeadPageUrl`, `safePublicHttpUrl`, `previewImport`, `listLeadCandidates`, `getLeadCandidate`, `createIngestionBatch`, `getJob`, `analyzeLeadCandidate`, and `createLeadReview`.

- [ ] **Step 1: Write failing safety and request-contract tests**

```ts
it("keeps cursors on the lead endpoint", () => {
  expect(safeLeadPageUrl("/api/v1/lead-candidates?cursor=abc")).toBe("/api/v1/lead-candidates?cursor=abc")
  expect(safeLeadPageUrl("https://evil.example/leads")).toBeNull()
})

it("keeps organization data in every query key", () => {
  expect(leadKeys.list("org-a", { score_band: "HIGH" })[1]).toBe("org-a")
  expect(leadKeys.detail("org-b", "lead-1")[1]).toBe("org-b")
  expect(leadKeys.job("org-c", "job-1")[1]).toBe("org-c")
})

it("submits a stable idempotency key inside the guided import", async () => {
  server.use(http.post("/api/v1/ingestion-batches", async ({ request }) => {
    expect(await request.json()).toEqual({
      source_type: "PASTE",
      idempotency_key: "intent-1",
      payload: { text: "https://example.test/post\tNeed replacement gears" },
    })
    return HttpResponse.json({ job_id: "job-1", ingestion_batch_id: "batch-1", status: "QUEUED" }, { status: 202 })
  }))
  await expect(createIngestionBatch({ mode: "PASTE", text: "https://example.test/post\tNeed replacement gears", idempotencyKey: "intent-1" })).resolves.toMatchObject({ job_id: "job-1" })
})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/api.test.ts`

Expected: FAIL because `modules/leads/api.ts` does not exist.

- [ ] **Step 3: Implement generated-type aliases, safe URL helpers, preview parsers, and thin API calls**

```ts
export const leadKeys = {
  all: (organizationId: string) => ["leads", organizationId] as const,
  list: (organizationId: string, filters: LeadFilters) => [...leadKeys.all(organizationId), "list", filters] as const,
  detail: (organizationId: string, candidateId: string) => [...leadKeys.all(organizationId), "detail", candidateId] as const,
  job: (organizationId: string, jobId: string) => [...leadKeys.all(organizationId), "job", jobId] as const,
}

export function safePublicHttpUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null
  } catch { return null }
}
```

`createIngestionBatch` maps `URL`, `SCREENSHOT`, `CSV`, `JSON`, and `PASTE` drafts to the exact `IngestionBatchCreate` schema. Screenshot drafts upload through the existing private asset API before this call; CSV/JSON files also use private assets only when the backend contract requires `import_asset_id`. `previewImport` is pure and returns valid row count, invalid row count, and row-indexed messages without network access.

- [ ] **Step 4: Cover errors, filters, analyze, review, and terminal job polling inputs**

Add tests that reject off-endpoint cursors, non-HTTP(S) public links, unsupported modes, malformed CSV/JSON previews, missing response bodies, and changed request shapes. Verify `expected_version` and idempotency keys are sent for analyze and review.

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/api.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint`

Commit: `feat: add typed customer opportunity API`

---

### Task 10B: Guided public-signal import dialog

**Files:**
- Create: `frontend/src/modules/leads/SourceImportDialog.vue`
- Create: `frontend/src/modules/leads/SourceImportDialog.test.ts`
- Modify: `frontend/src/modules/leads/api.ts`
- Modify: `frontend/src/modules/leads/api.test.ts`

**Interfaces:**
- Consumes: Task 10A `ImportDraft`, `previewImport`, `createIngestionBatch`, `getJob`, `leadKeys.job`, plus the existing private asset upload function.
- Produces: `SourceImportDialog` props `{ organizationId: string; open: boolean }` and emits `close` and `completed: { batchId: string; jobId: string }`.

- [ ] **Step 1: Write failing first-use, mode, and lifecycle tests**

```ts
it("puts link and paste first and moves structured imports under more ways", async () => {
  render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  expect(screen.getByRole("tab", { name: "帖子链接" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "批量粘贴" })).toBeVisible()
  await userEvent.click(screen.getByRole("button", { name: "更多导入方式" }))
  expect(screen.getByRole("tab", { name: "截图" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "CSV 文件" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "JSON 文件" })).toBeVisible()
})

it("announces understandable progress and stops polling after completion", async () => {
  // MSW returns QUEUED, RUNNING, then SUCCEEDED.
  // Assert visible copy changes from 正在接收 to 正在筛选 to 已完成 and no fourth request occurs.
})
```

- [ ] **Step 2: Run the dialog test and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/SourceImportDialog.test.ts`

Expected: FAIL because the dialog is absent.

- [ ] **Step 3: Implement progressive fields and local preview**

Each mode renders only its own inputs and example. URL requires a public URL and optional original text. Paste accepts one `URL<TAB>原文` row per line. Screenshot accepts one image and uploads it privately before submission. CSV/JSON read UTF-8 text, show valid/invalid counts, and block submission while invalid rows remain. The confirmation copy is exactly:

> 系统只保存你提供范围内的公开信息，不会自动登录平台或发送消息。

- [ ] **Step 4: Implement submission, polling, cleanup, and recovery**

Generate one idempotency key per unchanged intent and reuse it after recoverable failures. Poll at a bounded interval only for `QUEUED`, `RUNNING`, and `RETRY_QUEUED`; stop on terminal state, close, and unmount. Revoke every screenshot object URL on replacement, close, and unmount. Map errors to a short explanation and a concrete button such as `检查内容后重试` or `重新上传截图`.

- [ ] **Step 5: Verify accessibility, type safety, and commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/api.test.ts src/modules/leads/SourceImportDialog.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint`

Commit: `feat: add guided public signal imports`

---

### Task 10C: Customer-opportunity queue

**Files:**
- Create: `frontend/src/modules/leads/LeadRadarPage.vue`
- Create: `frontend/src/modules/leads/LeadRadarPage.test.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/router.test.ts`
- Modify: `frontend/src/main.ts`

**Interfaces:**
- Consumes: Task 10A list/query helpers and Task 10B `SourceImportDialog`.
- Produces: authenticated `/lead-radar` route titled `客户机会`, filter state, safe cursor pagination, and a `select-candidate` interaction used by Task 11.

- [ ] **Step 1: Write failing queue behavior tests**

```ts
it("explains collect then filter before showing professional states", async () => {
  render(LeadRadarPage, { global: testApp() })
  expect(await screen.findByRole("heading", { name: "客户机会" })).toBeVisible()
  expect(screen.getByText("先收集指定范围内的公开线索，再由 AI 筛选值得你查看的机会。" )).toBeVisible()
  expect(screen.getByRole("button", { name: "添加公开线索" })).toBeVisible()
})

it("separates value from evidence sufficiency", async () => {
  expect(await screen.findByText("高价值机会")).toBeVisible()
  expect(screen.getByText("证据还不够")).toBeVisible()
  expect(screen.queryByText("已确认高价值")).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/LeadRadarPage.test.ts src/app/router.test.ts`

Expected: FAIL because page and route are absent.

- [ ] **Step 3: Implement plain-language summaries, filters, and cards**

Render four independently understandable summaries: `等待分析`, `高价值待决定`, `需要补证据`, `已经处理`. Filters use user language for value, evidence/review state, platform, and country while mapping to API query parameters. Cards show company/account name or `待确认`, public-platform source, score band, a separate evidence label, one-line AI explanation when available, and `查看依据`.

- [ ] **Step 4: Implement loading, empty, error, pagination, permissions, and import refresh**

Distinguish first-use empty, currently analyzing, and filtered-empty states. Hide `添加公开线索` without `sources.manage`; permit read-only evidence viewing with `leads.read`. Refetch the queue after a completed import without discarding the active filter. Only follow `safeLeadPageUrl` cursors.

- [ ] **Step 5: Wire route and lazy component, verify, and commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/api.test.ts src/modules/leads/SourceImportDialog.test.ts src/modules/leads/LeadRadarPage.test.ts src/app/router.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Commit: `feat: add customer opportunity queue`

---

### Task 11A: Evidence-first opportunity review

**Files:**
- Create: `frontend/src/modules/leads/LeadDetailDialog.vue`
- Create: `frontend/src/modules/leads/LeadDetailDialog.test.ts`
- Modify: `frontend/src/modules/leads/LeadRadarPage.vue`
- Modify: `frontend/src/modules/leads/LeadRadarPage.test.ts`
- Modify: `frontend/src/modules/leads/api.ts`
- Modify: `frontend/src/modules/leads/api.test.ts`

**Interfaces:**
- Consumes: candidate detail, analyze job, review mutation, current permissions, safe public URL helper, and queue query keys.
- Produces: dialog props `{ organizationId: string; candidateId: string | null; open: boolean }`, emit `close`, and review actions `CONFIRM`, `CORRECT`, `DISMISS`, `REOPEN`, `REQUEST_MORE_EVIDENCE`.

- [ ] **Step 1: Write failing evidence-order, uncertainty, and review tests**

```ts
it("shows original evidence before AI explanation and audit details", async () => {
  render(LeadDetailDialog, { props: detailProps(), global: testApp() })
  const original = await screen.findByText("We need replacement helical gears, 200 pcs.")
  const explanation = screen.getByText("为什么值得查看")
  expect(original.compareDocumentPosition(explanation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getByRole("link", { name: "打开公开来源" })).toHaveAttribute("rel", "noopener noreferrer")
})

it("requires a reason before dismissing", async () => {
  await userEvent.click(await screen.findByRole("button", { name: "暂不跟进" }))
  expect(screen.getByRole("button", { name: "确认暂不跟进" })).toBeDisabled()
})
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/LeadDetailDialog.test.ts`

Expected: FAIL because the dialog is absent.

- [ ] **Step 3: Implement the evidence-first progressive layout**

Order sections as opportunity summary, original evidence, AI explanation, requirement/capability matches, uncertainty, human decision, and collapsed advanced audit. Show original text before translation. Display inferred company/domain values with `待确认`. Render score dimensions and AI version only in the advanced disclosure.

- [ ] **Step 4: Implement analyze/review permissions and conflict recovery**

Send `expected_version` and stable idempotency key. Hide analyze/review/handoff controls without their permissions. On 409, retain the typed reason/correction, refetch detail, announce `另一位同事刚刚保存了处理结果`, and enable `按最新版本重新提交`. Successful mutation invalidates organization queue, detail, and job keys and announces completion.

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/api.test.ts src/modules/leads/LeadRadarPage.test.ts src/modules/leads/LeadDetailDialog.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Commit: `feat: add evidence first opportunity review`

---

### Task 11B: Five-entry cockpit shell and decision inbox

**Files:**
- Modify: `frontend/src/app/AppShell.vue`
- Modify: `frontend/src/app/AppShell.test.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/router.test.ts`
- Modify: `frontend/src/modules/dashboard/DashboardPage.vue`
- Modify: `frontend/src/modules/dashboard/DashboardPage.test.ts`
- Create: `frontend/src/modules/company/CompanyProfilePage.vue`
- Create: `frontend/src/modules/company/CompanyProfilePage.test.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/styles/base.css`

**Interfaces:**
- Consumes: existing current-user identity/permissions, Task 10A lead/job queries, existing product/knowledge/asset query functions, and existing content/analytics routes.
- Produces: ordinary navigation with five entries, local `sinofgear-navigation-mode-v1` preference (`ordinary | advanced`), `/company-profile`, and a resilient decision inbox.

- [ ] **Step 1: Write failing ordinary/advanced navigation tests**

```ts
it("shows only five task-oriented entries by default", async () => {
  render(AppShell, { global: testApp() })
  for (const name of ["今天", "推广", "客户机会", "效果", "公司资料"]) {
    expect(await screen.findByRole("link", { name })).toBeVisible()
  }
  expect(screen.queryByRole("link", { name: "知识库" })).not.toBeInTheDocument()
})

it("reveals existing administration routes in advanced mode", async () => {
  await userEvent.click(screen.getByRole("button", { name: "打开高级功能" }))
  expect(screen.getByRole("link", { name: "知识库" })).toBeVisible()
  expect(screen.getByRole("link", { name: "平台账户" })).toBeVisible()
})
```

- [ ] **Step 2: Write failing decision-inbox and company-profile tests**

Verify the home page renders `今天需要你决定`, `AI 正在执行`, `近期结果`, and `公司资料还缺什么`; one failed summary query leaves other regions usable. Verify company profile summarizes real product/knowledge/material counts or honest empty states and links to advanced editors instead of duplicating their forms.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/app/AppShell.test.ts src/app/router.test.ts src/modules/dashboard/DashboardPage.test.ts src/modules/company/CompanyProfilePage.test.ts`

Expected: FAIL because ordinary navigation, decision inbox, and company profile are absent.

- [ ] **Step 4: Implement the ordinary shell and advanced disclosure**

Map ordinary routes: `今天 → /`, `推广 → /content-factory`, `客户机会 → /lead-radar`, `效果 → /analytics`, `公司资料 → /company-profile`. Preserve every existing route in advanced mode. Read the mode once from local storage with defensive parsing, default to ordinary, persist only `ordinary` or `advanced`, and keep mobile focus trapping/close behavior intact.

- [ ] **Step 5: Implement resilient home and company-profile facades**

Compose decisions from real pending/reviewable data and show honest empty guidance when none exists. Show jobs in plain language (`正在筛选公开线索`) rather than raw enum names. Keep queries independent so partial failure displays a local retry. Company profile reports what the AI knows and the shortest missing-data action, then deep-links to existing product, knowledge, or asset editors.

- [ ] **Step 6: Apply clean blue visual hierarchy without changing the token contract**

Use existing tokens, white/light-gray surfaces, generous spacing, restrained shadows, separate evidence-warning and success colors, and responsive single-column fallbacks. Do not add decorative charts or fake metrics.

- [ ] **Step 7: Verify, commit, and update the parent plan ledger**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run`

Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Commit: `feat: add AI decision cockpit navigation`

Record Tasks 10 and 11 complete in the SDD progress ledger only after independent review of Tasks 10A, 10B, 10C, 11A, and 11B.

---

### Task 11C: Cockpit browser acceptance

**Files:**
- Create: `frontend/e2e/ai-decision-cockpit.spec.ts`
- Modify: `frontend/e2e/phase-b1-lead-intelligence.spec.ts` if it exists after parent Task 12 work starts
- Modify: `docs/phase-b1-acceptance.md` if it exists after parent Task 12 work starts

**Interfaces:**
- Consumes: Tasks 10A through 11B and the existing E2E launcher/seed conventions.
- Produces: browser evidence for the beginner journey before the broader parent Task 12 acceptance gate.

- [ ] **Step 1: Write the browser flow**

```ts
test("a beginner adds a public signal and decides from evidence", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "今天需要你决定" })).toBeVisible()
  await page.getByRole("link", { name: "客户机会" }).click()
  await page.getByRole("button", { name: "添加公开线索" }).click()
  await page.getByRole("tab", { name: "批量粘贴" }).click()
  await page.getByLabel("公开内容").fill("https://example.com/post/1\tWe need 200 replacement helical gears")
  await page.getByRole("button", { name: "开始整理并筛选" }).click()
  await expect(page.getByText("已完成")).toBeVisible()
  await page.getByRole("button", { name: "查看依据" }).first().click()
  await expect(page.getByText("We need 200 replacement helical gears")).toBeVisible()
})
```

- [ ] **Step 2: Add mobile and advanced-mode flows**

At a narrow viewport, verify drawer focus, Escape close, and five ordinary entries. Switch to advanced mode, verify legacy routes remain reachable, reload, and verify the validated preference persists.

- [ ] **Step 3: Run browser acceptance and all frontend gates**

Run the repository's existing E2E launcher command, followed by:

`cd frontend && node node_modules/vitest/vitest.mjs --run && npm run typecheck && npm run lint && npm run build`

- [ ] **Step 4: Commit**

Commit: `test: cover beginner decision cockpit flow`
