# AI Native UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the current ordinary-mode frontend as a polished, fully Chinese AI workbench that a first-time user can operate without understanding internal domain objects, while preserving honest data, evidence review, permissions, advanced administration, and the future CRM integration boundary.

**Architecture:** Keep the existing Vue application, routes, Django API, generated OpenAPI types, organization isolation, and audit behavior. Add one centralized ordinary-language presentation layer and a small set of reusable visual primitives, then restyle and restructure the five ordinary pages around decisions and outcomes. Advanced pages remain available through progressive disclosure; no backend object is renamed and no fake AI, metric, progress, or CRM success state is introduced.

**Tech Stack:** Vue 3, TypeScript, Vue Router, TanStack Vue Query, Vitest, Testing Library, Playwright, generated OpenAPI types, existing CSS tokens, inline SVG icons, Django REST API.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-08-11-ai-native-ui-redesign-design.md`; implementation must satisfy every acceptance criterion there.
- Ordinary navigation labels are exactly `今天`, `推广`, `客户机会`, `效果`, and `我的公司`.
- Ordinary pages must not expose raw internal object names, raw enum values, permission codes, UUIDs as primary labels, or mixed-language operational copy.
- Keep SinofGear blue `#005BA8` as the primary color, a white/light-gray canvas, restrained status colors, rounded cards, clear hierarchy, and generous whitespace.
- Use inline SVG icons through one reusable component; do not add an icon library or a second UI framework.
- All displayed counts, percentages, trends, activities, and progress come from existing API responses. Missing data produces an honest empty state, not fabricated demo content.
- The CRM boundary remains visible. Until a configured handoff API exists, `交给 CRM` opens an honest configuration/export path and never claims that customer data was sent.
- Ordinary and advanced modes share routes, permissions, caches, organization isolation, and backend records. Navigation mode changes presentation only.
- All organization-scoped Vue Query keys include the organization ID; new requests support cancellation where the existing query layer permits it.
- Preserve keyboard access, visible focus, correct landmarks, dialog focus restoration, `aria-live` status, reduced motion, safe external links, and responsive behavior.
- Use generated OpenAPI component types. Never hand-edit `frontend/src/api/generated/schema.ts`.
- Work test-first. Each task must show RED, implement the minimum production change, run focused verification, and make one intentional commit.

---

### Task 1: Centralize ordinary-language presentation

**Files:**
- Create: `frontend/src/shared/presentation/ordinary.ts`
- Create: `frontend/src/shared/presentation/ordinary.test.ts`
- Modify: `frontend/src/modules/leads/api.ts`
- Modify: `frontend/src/modules/leads/api.test.ts`

**Interfaces:**
- Produces: `ordinaryTerm`, `ordinaryStatus`, `ordinaryPlatform`, `ordinaryScoreBand`, `formatOrdinaryError`, and `assertNeverOrdinaryValue`.
- Consumes: generated schema enum unions where available; accepts `string | null | undefined` only at server-boundary helpers.

- [ ] **Step 1: Write failing translation and safe-fallback tests**

```ts
it.each([
  ["Campaign", "推广计划"],
  ["ContentBrief", "推广要求"],
  ["LeadCandidate", "潜在客户"],
  ["Ontology", "AI 对公司的了解"],
])("translates %s for ordinary users", (input, expected) => {
  expect(ordinaryTerm(input)).toBe(expected)
})

it("never leaks an unknown server enum to ordinary users", () => {
  expect(ordinaryStatus("NEW_SERVER_STATE")).toBe("状态待确认")
  expect(ordinaryStatus("NEW_SERVER_STATE")).not.toContain("NEW_SERVER_STATE")
})
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/shared/presentation/ordinary.test.ts src/modules/leads/api.test.ts`

Expected: FAIL because `shared/presentation/ordinary.ts` does not exist and lead import validation still emits English recovery copy.

- [ ] **Step 3: Implement exhaustive maps and Chinese boundary messages**

```ts
const statuses: Readonly<Record<string, string>> = {
  DRAFT: "草稿",
  GENERATING: "正在生成",
  RUNNING: "正在处理",
  QUEUED: "等待处理",
  RETRY_QUEUED: "等待重试",
  IN_REVIEW: "等待确认",
  APPROVED: "已批准",
  REJECTED: "已退回",
  PUBLISHED: "已发布",
  ARCHIVED: "已归档",
  DISCOVERED: "新发现",
  ANALYZING: "正在判断",
  ANALYZED: "判断完成",
  REVIEWED: "已人工确认",
  FAILED: "处理失败",
  SUCCEEDED: "已完成",
}

export function ordinaryStatus(value: string | null | undefined): string {
  return value ? statuses[value] ?? "状态待确认" : "暂无状态"
}
```

Translate every user-visible validation message in `modules/leads/api.ts`, including URL, CSV, JSON, row-limit, timestamp, signal-type, and screenshot errors. Technical details may remain in the advanced audit view only.

- [ ] **Step 4: Add a contract test for every status currently present in generated schemas**

The test extracts the known values used by ordinary routes and asserts that none render an underscore-separated token. Add explicit tests for LinkedIn, YouTube, Facebook, Instagram, TikTok, manual input, high/watch/low value bands, and unknown fallbacks.

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/shared/presentation/ordinary.test.ts src/modules/leads/api.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint`

Commit: `feat: add ordinary language presentation layer`

---

### Task 2: Build the visual foundation and five-entry application shell

**Files:**
- Create: `frontend/src/shared/components/AppIcon.vue`
- Create: `frontend/src/shared/components/AppIcon.test.ts`
- Create: `frontend/src/shared/components/StatusBadge.vue`
- Create: `frontend/src/shared/components/StatusBadge.test.ts`
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/src/styles/base.css`
- Modify: `frontend/src/app/AppShell.vue`
- Modify: `frontend/src/app/AppShell.test.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/router.test.ts`

**Interfaces:**
- `AppIcon` prop: `name: "home" | "megaphone" | "users" | "chart" | "company" | "settings" | "bell" | "globe" | "chevron" | "check" | "search" | "document" | "sparkles" | "star"`.
- `StatusBadge` exports `StatusTone = "brand" | "success" | "warning" | "danger" | "neutral"` and accepts props `{ tone: StatusTone; label: string }`.
- `AppShell` continues to read and persist `sinofgear-navigation-mode-v1` safely.

- [ ] **Step 1: Write failing shell, icon, navigation, and storage tests**

```ts
it("shows exactly five ordinary work destinations", () => {
  renderShell()
  const nav = screen.getByRole("navigation", { name: "主导航" })
  expect(within(nav).getAllByRole("link").map((item) => item.textContent?.trim())).toEqual([
    "今天", "推广", "客户机会", "效果", "我的公司",
  ])
})

it("keeps ordinary mode usable when browser storage throws", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked") })
  expect(() => renderShell()).not.toThrow()
  expect(screen.getByRole("link", { name: /今天/ })).toBeVisible()
})
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/shared/components/AppIcon.test.ts src/shared/components/StatusBadge.test.ts src/app/AppShell.test.ts src/app/router.test.ts`

Expected: FAIL because shared visual components do not exist and the shell still uses text initials and `公司资料`.

- [ ] **Step 3: Implement design tokens and primitives**

Add semantic tokens for canvas, surface, elevated surface, brand tint, text, muted text, border, focus ring, four status families, 8/12/16/24/32 spacing, 10/14/18 radii, and restrained shadows. `AppIcon` renders decorative inline SVG with `aria-hidden="true"`; adjacent visible text supplies the accessible name. `StatusBadge` has adequate contrast and never communicates status through color alone.

- [ ] **Step 4: Rebuild the responsive shell**

Implement the approved brand lockup, icon navigation, compact organization/user header, bottom advanced-settings control, active-route styling, and mobile drawer. Rename the ordinary route title and label to `我的公司`; keep the URL `/company-profile`. Add `aria-controls="primary-sidebar"` and correct `aria-expanded` to the menu button. Preserve Escape, focus trap, route-change focus, storage fallback, and permission-filtered advanced navigation.

- [ ] **Step 5: Verify responsive and accessibility behavior, then commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/shared/components/AppIcon.test.ts src/shared/components/StatusBadge.test.ts src/app/AppShell.test.ts src/app/router.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Commit: `feat: redesign the AI workbench shell`

---

### Task 3: Recompose Today as a real decision cockpit

**Files:**
- Create: `frontend/src/modules/dashboard/components/DecisionCard.vue`
- Create: `frontend/src/modules/dashboard/components/DecisionCard.test.ts`
- Create: `frontend/src/modules/dashboard/components/ActivityRow.vue`
- Create: `frontend/src/modules/dashboard/components/ActivityRow.test.ts`
- Create: `frontend/src/modules/dashboard/components/MetricCard.vue`
- Create: `frontend/src/modules/dashboard/components/MetricCard.test.ts`
- Modify: `frontend/src/modules/dashboard/DashboardPage.vue`
- Modify: `frontend/src/modules/dashboard/DashboardPage.test.ts`

**Interfaces:**
- `DecisionCard` props: `{ index: number; title: string; explanation: string; statusLabel: string; statusTone: StatusTone; primaryAction: string; secondaryAction?: string }`; emits `primary` and `secondary`.
- Dashboard derives decision cards, AI activity, and metrics only from its existing permission-scoped queries.

- [ ] **Step 1: Write failing information-hierarchy and honesty tests**

```ts
it("leads with decisions and explains what the user should do", async () => {
  renderDashboardWithFixtures()
  expect(await screen.findByRole("heading", { name: /今天有 \d+ 件事需要你决定/ })).toBeVisible()
  expect(screen.getByRole("region", { name: "需要你决定" })).toBeVisible()
  expect(screen.getByRole("region", { name: "AI 正在帮你工作" })).toBeVisible()
  expect(screen.getByRole("region", { name: "最近结果" })).toBeVisible()
})

it("does not invent counts when one source is unavailable", async () => {
  renderDashboardWithLeadFailure()
  expect(await screen.findByText("客户机会暂时没有加载成功")).toBeVisible()
  expect(screen.queryByText("发现 2 个高意向潜客")).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/dashboard/components/DecisionCard.test.ts src/modules/dashboard/components/ActivityRow.test.ts src/modules/dashboard/components/MetricCard.test.ts src/modules/dashboard/DashboardPage.test.ts`

Expected: FAIL because the new components and approved page hierarchy are absent.

- [ ] **Step 3: Implement the three dashboard zones**

Use real pending-review content, lead decisions, job statuses, and analytics summaries. Decision cards show numbered priority, plain-language basis, consequence, and one clear primary action. The activity panel translates jobs to user work such as `正在分析公开线索` and uses indeterminate UI when the API has no true percentage. The result panel shows only available metrics and a conclusion sentence derived from those values.

- [ ] **Step 4: Implement independent loading, empty, permission, and error states**

Each zone remains useful when another query fails. First-use empty state says what to add next and links to the relevant ordinary page. Retry only refetches the failed panel. Add abort signals to dashboard query functions that currently lack them so organization/page changes cannot repaint stale data.

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/dashboard/components/DecisionCard.test.ts src/modules/dashboard/components/ActivityRow.test.ts src/modules/dashboard/components/MetricCard.test.ts src/modules/dashboard/DashboardPage.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Commit: `feat: turn today into a decision cockpit`

---

### Task 4: Turn Promotion into a guided beginner workflow

**Files:**
- Create: `frontend/src/modules/content/components/GuidedStepCard.vue`
- Create: `frontend/src/modules/content/components/GuidedStepCard.test.ts`
- Modify: `frontend/src/modules/content/PromotionPage.vue`
- Modify: `frontend/src/modules/content/PromotionPage.test.ts`
- Modify: `frontend/src/modules/content/ContentFactoryPage.vue`
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`
- Modify: `frontend/src/modules/content/ContentBriefWizard.vue`
- Modify: `frontend/src/modules/content/ContentBriefWizard.test.ts`
- Modify: `frontend/src/modules/content/ContentReviewDialog.vue`
- Modify: `frontend/src/modules/content/ReviewCenterPage.vue`
- Modify: `frontend/src/modules/content/ReviewCenterPage.test.ts`

**Interfaces:**
- `GuidedStepCard` props: `{ number: number; title: string; description: string; state: "current" | "complete" | "locked" }`.
- Existing create, generate, review, and publish API contracts remain unchanged.

- [ ] **Step 1: Write failing ordinary-copy and guided-flow tests**

```ts
it("asks the beginner what to promote before exposing implementation objects", async () => {
  renderPromotion()
  expect(await screen.findByRole("heading", { name: "你今天想推广什么？" })).toBeVisible()
  expect(screen.getByText("选择产品")).toBeVisible()
  expect(screen.getByText("告诉 AI 目标")).toBeVisible()
  expect(screen.getByText("确认方案")).toBeVisible()
  expect(screen.queryByText("ContentBrief")).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/content/components/GuidedStepCard.test.ts src/modules/content/PromotionPage.test.ts src/modules/content/ContentFactoryPage.test.ts src/modules/content/ContentBriefWizard.test.ts src/modules/content/ReviewCenterPage.test.ts`

Expected: FAIL because the page is currently organized around domain objects and administrative tables.

- [ ] **Step 3: Implement a bounded conversational-looking workflow**

Present a vertical sequence of cards: choose a product, choose market/goal, inspect available materials, review AI proposal, generate content, approve. Only the current step is expanded. Use predefined choices plus concise optional text fields; do not display a free-form chat box or imply a live model conversation before the real provider is connected.

- [ ] **Step 4: Localize review and generation states without breaking recovery**

Replace ordinary-facing `Campaign`, `ContentBrief`, `MasterContent`, `PlatformContent`, and raw statuses using Task 1 helpers. Keep conflict recovery, version checks, permissions, review rejection reasons, and advanced links. Give every primary action a consequence-oriented label such as `生成推广方案`, `查看并确认`, or `批准发布`.

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/content/components/GuidedStepCard.test.ts src/modules/content/PromotionPage.test.ts src/modules/content/ContentFactoryPage.test.ts src/modules/content/ContentBriefWizard.test.ts src/modules/content/ReviewCenterPage.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Commit: `feat: guide beginners through promotion work`

---

### Task 5: Polish customer opportunities and retain the honest CRM boundary

**Files:**
- Create: `frontend/src/modules/leads/export.ts`
- Create: `frontend/src/modules/leads/export.test.ts`
- Create: `frontend/src/modules/leads/LeadHandoffPanel.vue`
- Create: `frontend/src/modules/leads/LeadHandoffPanel.test.ts`
- Modify: `frontend/src/modules/leads/LeadRadarPage.vue`
- Modify: `frontend/src/modules/leads/LeadRadarPage.test.ts`
- Modify: `frontend/src/modules/leads/LeadDetailDialog.vue`
- Modify: `frontend/src/modules/leads/LeadDetailDialog.test.ts`

**Interfaces:**
- `buildLeadExport(detail: LeadCandidateDetail): LeadExportV1` produces `{ version, exported_at, candidate, insight, source_evidence }`.
- `downloadLeadJson(detail)` and `downloadLeadCsv(detail)` create local files and revoke their object URLs.
- `LeadHandoffPanel` props: `{ detail: LeadCandidateDetail; canHandoff: boolean; connectorConfigured: boolean }`; emits `close` and `handoff` only when a real connector is configured.

- [ ] **Step 1: Write failing evidence, export, and CRM-honesty tests**

```ts
it("exports the judgment together with immutable source evidence", () => {
  const value = buildLeadExport(leadDetail)
  expect(value.source_evidence[0]).toMatchObject({
    url: "https://example.test/post",
    content: "Need replacement helical gears",
    platform: "YOUTUBE",
  })
})

it("does not claim CRM delivery when no connector exists", async () => {
  renderHandoff({ connectorConfigured: false })
  await userEvent.click(screen.getByRole("button", { name: "交给 CRM" }))
  expect(screen.getByText("CRM 尚未配置，当前不会发送客户资料")).toBeVisible()
  expect(screen.queryByText("交接成功")).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/export.test.ts src/modules/leads/LeadHandoffPanel.test.ts src/modules/leads/LeadRadarPage.test.ts src/modules/leads/LeadDetailDialog.test.ts`

Expected: FAIL because the export module and handoff panel do not exist and the current CRM control is disabled text.

- [ ] **Step 3: Implement safe JSON/CSV export**

Export public evidence, source URL, timestamp, platform, AI conclusion, score/confidence, human correction, company/account identity, and explicit uncertainty. Escape CSV formula prefixes (`=`, `+`, `-`, `@`), quote fields correctly, use a UTF-8 BOM for spreadsheet compatibility, omit private audit payloads, and revoke object URLs after download.

- [ ] **Step 4: Recompose the lead queue and detail view**

Use a desktop list/detail workspace and a mobile stacked flow. Lead cards prioritize company/account, need summary, value, evidence sufficiency, country/platform, and `查看依据`. The detail view orders content as: judgment, reasons, source evidence, uncertainty, human decision, CRM/export. Opening the review form moves focus to its heading and closing/restoring returns focus to the initiating control.

- [ ] **Step 5: Implement the CRM interface state honestly**

Keep `交给 CRM` as the primary future-facing control. With no configured connector endpoint in the current backend, open `LeadHandoffPanel` showing `下载 JSON`, `下载 CSV`, and `前往高级设置了解接入方式`; do not emit a handoff mutation. Define the `connectorConfigured` branch and event contract, but keep it false until a separately tested backend capability endpoint reports a real connector.

- [ ] **Step 6: Verify and commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/export.test.ts src/modules/leads/LeadHandoffPanel.test.ts src/modules/leads/LeadRadarPage.test.ts src/modules/leads/LeadDetailDialog.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Commit: `feat: polish opportunities and preserve CRM handoff`

---

### Task 6: Make Results conclusion-first and My Company gap-first

**Files:**
- Modify: `frontend/src/modules/analytics/AnalyticsPage.vue`
- Modify: `frontend/src/modules/analytics/AnalyticsPage.test.ts`
- Modify: `frontend/src/modules/company/CompanyProfilePage.vue`
- Modify: `frontend/src/modules/company/CompanyProfilePage.test.ts`
- Modify: `frontend/src/shared/components/NextStepPanel.vue`

**Interfaces:**
- Existing analytics, tracking-link, product, asset, and knowledge queries remain authoritative.
- `NextStepPanel` accepts user-facing title, explanation, and one primary route/action without exposing IDs.

- [ ] **Step 1: Write failing result and company-understanding tests**

```ts
it("explains the result before showing operational tracking details", async () => {
  renderAnalytics()
  expect(await screen.findByRole("heading", { name: "效果" })).toBeVisible()
  expect(screen.getByRole("region", { name: "AI 结论" })).toBeVisible()
  expect(screen.getByText(/下一步建议/)).toBeVisible()
})

it("shows what AI knows and what is missing", async () => {
  renderCompanyProfile()
  expect(await screen.findByRole("heading", { name: "AI 对公司的了解" })).toBeVisible()
  expect(screen.getByRole("region", { name: "资料完整度" })).toBeVisible()
  expect(screen.getByRole("region", { name: "建议补充" })).toBeVisible()
})
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/analytics/AnalyticsPage.test.ts src/modules/company/CompanyProfilePage.test.ts`

Expected: FAIL because Results is currently a dense tracking dashboard and My Company is object-centric.

- [ ] **Step 3: Recompose Results**

Order the page as conclusion, key metrics, trend, recommended next action, then collapsible operational tracking details. Resolve campaign/platform/product names when available; otherwise show `名称暂不可用` rather than a UUID as the principal label. Do not infer causality or “best platform” when the response lacks enough comparable data.

- [ ] **Step 4: Recompose My Company**

Show company identity, products, capabilities, industries, processes, standards, evidence coverage, and missing-information tasks in ordinary language. Link each gap to the existing edit/upload flow. Add abort signals to company queries that currently lack them and prevent stale responses after organization changes.

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/analytics/AnalyticsPage.test.ts src/modules/company/CompanyProfilePage.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Commit: `feat: clarify results and company knowledge`

---

### Task 7: Enforce the ordinary-mode language and accessibility contract

**Files:**
- Create: `frontend/src/app/ordinaryMode.contract.test.ts`
- Modify: `frontend/src/app/AppShell.test.ts`
- Modify: `frontend/src/modules/dashboard/DashboardPage.test.ts`
- Modify: `frontend/src/modules/content/PromotionPage.test.ts`
- Modify: `frontend/src/modules/leads/LeadRadarPage.test.ts`
- Modify: `frontend/src/modules/analytics/AnalyticsPage.test.ts`
- Modify: `frontend/src/modules/company/CompanyProfilePage.test.ts`
- Modify: `frontend/src/styles/base.css`

**Interfaces:**
- Contract covers all five ordinary routes with representative API fixtures and a shared forbidden-token list.

- [ ] **Step 1: Write the failing cross-route contract**

```ts
const forbidden = [
  "Campaign", "ContentBrief", "MasterContent", "PlatformContent",
  "LeadCandidate", "LeadInsight", "SourceSignal", "AIRun",
  "PromptVersion", "Ontology", "PERMISSION_DENIED", "IN_REVIEW",
]

it.each(["/", "/promotion", "/lead-radar", "/analytics", "/company-profile"])(
  "%s keeps internal language out of ordinary mode",
  async (path) => {
    const view = await renderOrdinaryRoute(path)
    for (const token of forbidden) expect(view.container).not.toHaveTextContent(token)
  },
)
```

- [ ] **Step 2: Run the contract and verify RED**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/app/ordinaryMode.contract.test.ts`

Expected: FAIL on current English/internal strings and raw states.

- [ ] **Step 3: Remove remaining ordinary-mode leaks**

Route every visible state through Task 1, translate permission/validation/recovery copy, hide IDs under labelled advanced disclosure, and keep API payload fields out of accessible ordinary text. Allow proper nouns such as SinofGear, LinkedIn, YouTube, Facebook, Instagram, TikTok, CRM, CSV, and JSON.

- [ ] **Step 4: Add keyboard, reduced-motion, contrast, and responsive assertions**

Test skip/main landmarks, drawer semantics, dialog focus return, button accessible names, heading order, status text, and no horizontal overflow at 390 CSS pixels. Ensure `prefers-reduced-motion: reduce` disables non-essential transitions.

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/app/ordinaryMode.contract.test.ts src/app/AppShell.test.ts src/modules/dashboard/DashboardPage.test.ts src/modules/content/PromotionPage.test.ts src/modules/leads/LeadRadarPage.test.ts src/modules/analytics/AnalyticsPage.test.ts src/modules/company/CompanyProfilePage.test.ts`

Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Commit: `test: enforce the ordinary mode experience`

---

### Task 8: Browser acceptance, documentation, and clean handoff

**Files:**
- Modify: `frontend/e2e/ai-decision-cockpit.spec.ts`
- Modify: `frontend/e2e/phase-b1-lead-intelligence.spec.ts`
- Modify: `frontend/e2e/phase-a-active-growth.spec.ts`
- Create: `docs/acceptance/ai-native-ui-redesign.md`
- Modify: `README.md`

**Interfaces:**
- Uses the existing isolated E2E launcher and seeded acceptance data.
- Produces an evidence-backed acceptance report with commands, results, limitations, and browser viewport coverage.

- [ ] **Step 1: Write failing browser journeys**

Add Playwright coverage for:

1. Log in and see exactly five ordinary navigation entries.
2. Open Today, inspect a decision, and reach its correct ordinary page.
3. Start a guided promotion and reach review without seeing internal object names.
4. Open a customer opportunity, inspect source evidence, choose `交给 CRM`, and download an export without a false success message.
5. Read a conclusion on Results and a missing-information task on My Company.
6. Switch to advanced settings and back without losing authentication or organization state.
7. Repeat shell/navigation checks at desktop 1440×900, tablet 820×1180, and mobile 390×844.

- [ ] **Step 2: Run E2E and verify RED**

Run: `cd frontend && npm run test:e2e -- --spec ai-decision-cockpit.spec.ts --spec phase-b1-lead-intelligence.spec.ts`

Expected: FAIL until the redesigned journeys and accessible names are implemented.

- [ ] **Step 3: Make browser behavior deterministic and document it**

Use stable seeded records and role/text locators. Do not add pixel-perfect screenshot baselines; verify layout bounds, navigation visibility, modal behavior, downloads, and absence of raw internal tokens. Document that the current acceptance environment uses deterministic AI providers and that CRM export is real while CRM transmission remains unconfigured.

- [ ] **Step 4: Run full frontend and backend verification**

Run: `cd frontend && npm test -- --run`

Run: `cd frontend && npm run typecheck && npm run lint && npm run build && npm run api:check && npm run test:e2e:launcher`

Run: `backend\.venv\Scripts\python.exe -m pytest -q`

Run: `cd frontend && npm run test:e2e`

Expected: all suites pass; browser acceptance reports every seeded scenario passed.

- [ ] **Step 5: Perform a leak and placeholder audit**

Run: `rg -n "Campaign|ContentBrief|MasterContent|PlatformContent|LeadCandidate|LeadInsight|SourceSignal|AIRun|PromptVersion|Ontology|TODO|FIXME|placeholder|lorem" frontend/src docs/acceptance/ai-native-ui-redesign.md`

Review each match. Matches are allowed only in TypeScript/API identifiers, tests proving absence, advanced-only presentation, or documentation that explicitly explains the boundary. There must be no ordinary-facing placeholder text, fake number, or fake completion state.

- [ ] **Step 6: Commit the acceptance closeout**

Run: `git status --short`

Commit: `test: close AI native UI acceptance`

The worktree must be clean after the commit. Do not push, email, package, or shut down in this task; those are final-project operations performed only after whole-branch review and delivery verification.
