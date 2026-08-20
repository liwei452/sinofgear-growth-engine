# Business-Outcome Navigation and Information Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SinoFGear's system-object navigation with five business-outcome workspaces while preserving permissions, safety checks, stored records, and legacy deep links; the approved design-spec exceptions permit only the organization-scoped market-recommendation read endpoint and the minimal persisted candidate workflow read model.

**Architecture:** Keep Vue Router, TanStack Query, and existing API modules as the data and behavior owners. Add route-owned presentation pages for Promotion, Opportunities, Content & Publishing, and Results; compose existing mission, growth, content, publishing, and attribution capabilities behind these pages. Keep `/missions` and all current secondary routes as compatible deep links, but remove them from primary navigation.

**Tech Stack:** Vue 3.5, Vue Router 4.5, TanStack Vue Query 5, TypeScript 5.8, Vitest 3, Testing Library Vue, Playwright 1.62, existing CSS tokens and API clients.

**Spec:** `docs/superpowers/specs/2026-08-20-business-outcome-navigation-ia-design.md`

## Global Constraints

- Primary navigation contains exactly: `今日`, `开始推广`, `客户机会`, `内容与发布`, `效果`.
- Sidebar utilities contain `我的公司`, `帮助`, `设置`; identity/session remains in the user menu.
- Preserve all backend models, migrations, permissions, AI behavior, OAuth, publishing, discovery, tracking, CRM, storage, and security behavior. Do not add API surface beyond the two minimal read-only exceptions named in the design spec, and do not expose candidate evidence links through the discovery profile.
- Preserve manual approval before outreach or publication.
- Do not create fake customers, opportunities, contacts, scores, charts, dates, metrics, readiness, notifications, or AI results.
- Missing values render as unavailable or not yet recorded, never as zero unless the stored value is zero.
- Preserve source links, timestamps, provider labels, demo labels, approval states, and unknown-submission safety semantics.
- Keep `/missions` and all secondary routes valid for old links.
- Use Chinese business language in the UI; retain official English platform names.
- All primary touch targets are at least 44 × 44px and every rendered page has one `main` landmark.
- Use TDD for every task and commit only the files owned by that task.
- Do not stage or alter unrelated Buffer safety work already present in the working tree.

## File Structure

### Route and shell ownership

- Modify `frontend/src/app/navigation.ts`: five primary destinations and three utility destinations.
- Modify `frontend/src/app/router.ts`: activate business routes and retain legacy redirects/deep links.
- Modify `frontend/src/app/AppShell.vue`: compact page context, utility navigation, one-main-landmark shell.
- Modify `frontend/src/main.ts`: register new route-owned pages.
- Create `frontend/src/modules/help/HelpPage.vue`: concise task-focused help index.

### Shared presentation contracts

- Create `frontend/src/shared/presentation/businessStatus.ts`: exhaustive translation of UI-visible status enums into Chinese labels, tone, and consequence text.
- Create `frontend/src/shared/components/WorkspaceHeader.vue`: compact Operate-mode page heading.
- Create `frontend/src/shared/components/BusinessState.vue`: loading, empty, blocked, error, success, and unknown-result state presentation.

### Business workspaces

- Modify `frontend/src/modules/dashboard/DashboardPage.vue`: Today confidence dashboard.
- Create `frontend/src/modules/promotion/PromotionWorkspacePage.vue`: persistent promotion progress workspace.
- Create `frontend/src/modules/opportunities/OpportunityWorkspacePage.vue`: account list/detail workspace.
- Create `frontend/src/modules/publishing/ContentPublishingPage.vue`: content status workspace.
- Create `frontend/src/modules/results/ResultsPage.vue`: conversion path and attribution workspace.
- Modify `frontend/src/modules/growth/CompanyPage.vue`: business source-of-truth readiness hub.
- Modify `frontend/src/modules/settings/SettingsCenterPage.vue`: current blockers and four default system groups.

### Tests

- Update each component's adjacent Vitest test.
- Add `frontend/e2e/business-outcome-navigation.spec.ts` for desktop/mobile navigation, history compatibility, state preservation, and permission visibility.
- Extend existing mission/content/publishing E2E tests instead of duplicating external-operation coverage.

---

### Task 1: Activate the Five Business Routes and Shell Navigation

**Files:**
- Modify: `frontend/src/app/navigation.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/AppShell.vue`
- Modify: `frontend/src/main.ts`
- Create: `frontend/src/modules/help/HelpPage.vue`
- Test: `frontend/src/app/AppShell.test.ts`
- Test: `frontend/src/app/router.test.ts`

**Interfaces:**
- Produces: primary routes named `home`, `promotion`, `opportunities`, `content-publishing`, `results`.
- Produces: utility routes named `company`, `help`, `settings`.
- Preserves: `missions`, `mission-detail`, `attribution`, products, assets, knowledge, platform accounts, and settings deep links.

- [ ] **Step 1: Write failing shell navigation tests**

```ts
expect(screen.getAllByRole("link").filter(link =>
  ["今日", "开始推广", "客户机会", "内容与发布", "效果"].includes(link.textContent ?? ""),
)).toHaveLength(5)
expect(screen.getByRole("link", { name: "我的公司" })).toHaveAttribute("href", "/company")
expect(screen.getByRole("link", { name: "帮助" })).toHaveAttribute("href", "/help")
expect(screen.getByRole("link", { name: "设置" })).toHaveAttribute("href", "/settings")
expect(screen.queryByRole("link", { name: "增长任务" })).not.toBeInTheDocument()
```

- [ ] **Step 2: Run the shell test and verify it fails**

Run: `pnpm --dir frontend test -- --run src/app/AppShell.test.ts`

Expected: FAIL because the current shell exposes `增长任务` and `数据归因` instead of the five business destinations.

- [ ] **Step 3: Write failing route tests**

```ts
await router.push("/promotion")
expect(router.currentRoute.value.name).toBe("promotion")
await router.push("/opportunities")
expect(router.currentRoute.value.name).toBe("opportunities")
await router.push("/content-factory")
expect(router.currentRoute.value.name).toBe("content-publishing")
await router.push("/analytics")
expect(router.currentRoute.value.name).toBe("results")
await router.push("/missions/mission-1")
expect(router.currentRoute.value.name).toBe("mission-detail")
```

- [ ] **Step 4: Add route component slots and navigation definitions**

Use this contract in `AppRouteComponents`:

```ts
Promotion: Component
Opportunities: Component
ContentPublishing: Component
Results: Component
Help: Component
```

Define navigation in this exact order:

```ts
export const navigationSections: NavigationSection[] = [{
  items: [
    { label: "今日", to: "/", icon: "calendar-days" },
    { label: "开始推广", to: "/promotion", icon: "send", requiredPermission: "missions.read" },
    { label: "客户机会", to: "/opportunities", icon: "users-round", requiredPermission: "leads.manage" },
    { label: "内容与发布", to: "/content-factory", icon: "clipboard-check", requiredPermission: "publishing.read" },
    { label: "效果", to: "/analytics", icon: "chart-column", requiredPermission: "missions.read" },
  ],
}]
```

All five icon names already exist in `AppIcon.vue`; do not add another icon library.

- [ ] **Step 5: Add a small task-focused Help page and eliminate nested main landmarks**

`HelpPage.vue` exposes links to the five business workspaces and explains that publication and outreach require human approval. Route pages use a top-level `<section>` or `<div>` because `AppShell.vue` owns the single `<main>`.

- [ ] **Step 6: Run route and shell tests**

Run: `pnpm --dir frontend test -- --run src/app/AppShell.test.ts src/app/router.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/navigation.ts frontend/src/app/router.ts frontend/src/app/AppShell.vue frontend/src/main.ts frontend/src/modules/help/HelpPage.vue frontend/src/app/AppShell.test.ts frontend/src/app/router.test.ts
git commit -m "feat: activate business-outcome navigation"
```

### Task 2: Add Shared Operate-Mode Headers and Business Status Language

**Files:**
- Create: `frontend/src/shared/presentation/businessStatus.ts`
- Create: `frontend/src/shared/presentation/businessStatus.test.ts`
- Create: `frontend/src/shared/components/WorkspaceHeader.vue`
- Create: `frontend/src/shared/components/WorkspaceHeader.test.ts`
- Create: `frontend/src/shared/components/BusinessState.vue`
- Create: `frontend/src/shared/components/BusinessState.test.ts`
- Modify: `frontend/src/styles/base.css`

**Interfaces:**
- Produces: `businessStatus(status: string): { label: string; consequence: string; tone: "neutral" | "info" | "warning" | "danger" | "success" }`.
- Produces: `WorkspaceHeader` props `{ title: string; description?: string; status?: string }` and `#actions` slot.
- Produces: `BusinessState` props `{ kind: "loading" | "empty" | "blocked" | "error" | "success" | "unknown"; title: string; message: string; actionLabel?: string }` and emits `action`.

- [ ] **Step 1: Write failing status translation tests**

```ts
expect(businessStatus("RUNNING")).toMatchObject({ label: "正在获客", tone: "info" })
expect(businessStatus("WAITING_APPROVAL")).toMatchObject({ label: "等待人工审核", tone: "warning" })
expect(businessStatus("SUBMISSION_UNKNOWN")).toMatchObject({
  label: "已提交，等待平台确认",
  tone: "warning",
})
expect(businessStatus("CONFIGURATION_REQUIRED").consequence).toContain("暂不能")
expect(businessStatus("UNRECOGNIZED")).toEqual({
  label: "状态待确认",
  consequence: "系统尚未提供可解释的业务状态。",
  tone: "neutral",
})
```

- [ ] **Step 2: Run the translation test and verify it fails**

Run: `pnpm --dir frontend test -- --run src/shared/presentation/businessStatus.test.ts`

Expected: FAIL because `businessStatus` does not exist.

- [ ] **Step 3: Implement exhaustive business labels without changing API values**

Map every enum currently rendered by Dashboard, Missions, Content, Publishing, AI settings, and Platform Accounts. Unknown values use the neutral fallback and remain available in `title` or accessible detail for diagnostics.

- [ ] **Step 4: Test shared header and state semantics**

```ts
expect(screen.getByRole("heading", { level: 1, name: "客户机会" })).toBeInTheDocument()
expect(screen.getByRole("status")).toHaveTextContent("正在读取")
await user.click(screen.getByRole("button", { name: "重新加载" }))
expect(wrapper.emitted("action")).toHaveLength(1)
```

- [ ] **Step 5: Implement compact components and minimum 44px controls**

`WorkspaceHeader` must not render a gradient, eyebrow, score, or decorative chart. `BusinessState` must provide text and icon semantics without relying on color. Update global buttons and icon buttons to a 44px minimum block size.

- [ ] **Step 6: Run shared component tests**

Run: `pnpm --dir frontend test -- --run src/shared/presentation/businessStatus.test.ts src/shared/components/WorkspaceHeader.test.ts src/shared/components/BusinessState.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/shared/presentation frontend/src/shared/components/WorkspaceHeader.vue frontend/src/shared/components/WorkspaceHeader.test.ts frontend/src/shared/components/BusinessState.vue frontend/src/shared/components/BusinessState.test.ts frontend/src/styles/base.css
git commit -m "feat: add business-facing workspace primitives"
```

### Task 3: Recompose Today as a Confidence Dashboard

**Files:**
- Modify: `frontend/src/modules/dashboard/DashboardPage.vue`
- Modify: `frontend/src/modules/dashboard/DashboardPage.test.ts`
- Modify: `frontend/src/modules/workItems/TodayWorkInbox.vue`
- Modify: `frontend/src/modules/workItems/TodayWorkInbox.test.ts`
- Modify: `frontend/src/modules/workItems/WorkItemCard.vue`

**Interfaces:**
- Consumes: existing work-item and mission queries; `businessStatus`, `WorkspaceHeader`, `BusinessState`.
- Produces: four regions with accessible names `今日最重要机会`, `当前阻塞`, `最新证据`, `今日待办`.
- Preserves: every current work-item action and permission check.

- [ ] **Step 1: Write failing dashboard composition tests**

```ts
expect(await screen.findByRole("region", { name: "今日最重要机会" })).toBeInTheDocument()
expect(screen.getByRole("region", { name: "当前阻塞" })).toBeInTheDocument()
expect(screen.getByRole("region", { name: "最新证据" })).toBeInTheDocument()
expect(screen.getByRole("region", { name: "今日待办" })).toBeInTheDocument()
expect(screen.queryByText("TODAY'S WORKSPACE")).not.toBeInTheDocument()
```

- [ ] **Step 2: Run the dashboard tests and verify they fail**

Run: `pnpm --dir frontend test -- --run src/modules/dashboard/DashboardPage.test.ts src/modules/workItems/TodayWorkInbox.test.ts`

Expected: FAIL because Today is currently a hero plus inbox.

- [ ] **Step 3: Derive honest summary regions from existing records**

Selection rules are deterministic and presentation-only:

```ts
const primaryDecision = computed(() => workItems.value.find(item => item.priority === "URGENT")
  ?? workItems.value.find(item => item.priority === "HIGH")
  ?? null)
const primaryBlocker = computed(() => workItems.value.find(item => item.action_type === "OPEN_SETTINGS") ?? null)
```

- [ ] **Step 4: Implement honest empty and completion states**

When no opportunity or evidence exists, render `BusinessState` with one contextual route action. After an item mutation succeeds, announce `已完成；相关任务和机会状态已更新。` via `aria-live="polite"` before invalidating queries.

- [ ] **Step 5: Run dashboard and work-item tests**

Run: `pnpm --dir frontend test -- --run src/modules/dashboard/DashboardPage.test.ts src/modules/workItems/TodayWorkInbox.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/dashboard frontend/src/modules/workItems
git commit -m "feat: turn today into a confidence dashboard"
```

### Task 4: Build the Persistent Promotion Workspace

**Files:**
- Create: `frontend/src/modules/promotion/PromotionWorkspacePage.vue`
- Create: `frontend/src/modules/promotion/PromotionWorkspacePage.test.ts`
- Create: `frontend/src/modules/promotion/promotionProgress.ts`
- Create: `frontend/src/modules/promotion/promotionProgress.test.ts`
- Modify: `frontend/src/main.ts`

**Interfaces:**
- Consumes: `missionsQueryOptions`, company fact queries, product/assets queries, `listSocialAccounts`, existing mission plan actions.
- Produces: `promotionSteps(input): PromotionStep[]` where `PromotionStep` is `{ id: "company" | "market" | "icp" | "discovery" | "content" | "channels" | "approval"; label: string; state: "complete" | "current" | "blocked" | "upcoming"; summary: string; route?: string }`.

- [ ] **Step 1: Write failing progress derivation tests**

```ts
expect(promotionSteps(emptyInput).map(step => step.state)).toEqual([
  "current", "blocked", "blocked", "blocked", "blocked", "blocked", "blocked",
])
expect(promotionSteps(configuredInput).find(step => step.id === "channels")?.state).toBe("current")
expect(promotionSteps(configuredInput).filter(step => step.state === "current")).toHaveLength(1)
```

- [ ] **Step 2: Run the progress tests and verify they fail**

Run: `pnpm --dir frontend test -- --run src/modules/promotion/promotionProgress.test.ts`

Expected: FAIL because the progress model does not exist.

- [ ] **Step 3: Implement deterministic seven-step derivation**

The function accepts only existing query results and booleans. It never invents progress percentages. The first incomplete valid step is `current`; later steps are `blocked` when prerequisites are missing and `upcoming` when prerequisites exist but work has not started.

- [ ] **Step 4: Write and run the page test**

```ts
expect(await screen.findByRole("heading", { name: "开始推广" })).toBeInTheDocument()
expect(screen.getAllByRole("listitem")).toHaveLength(7)
expect(screen.getByText("当前步骤")).toBeInTheDocument()
expect(screen.getByRole("link", { name: /继续/ })).toHaveAttribute("href", expect.stringMatching(/^\//))
```

Run: `pnpm --dir frontend test -- --run src/modules/promotion/PromotionWorkspacePage.test.ts`

Expected before implementation: FAIL. Expected after implementation: PASS.

- [ ] **Step 5: Implement the page using existing actions only**

Completed steps collapse to label and summary. Only the current step exposes its action. Account/API costs and restrictions appear only inside `channels`; approval safety appears only inside `approval`. Route the user into existing company, mission detail, assets, platform accounts, and review actions.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/promotion frontend/src/main.ts
git commit -m "feat: add persistent promotion workspace"
```

### Task 5: Build the Customer Opportunities Master-Detail Workspace

**Files:**
- Create: `frontend/src/modules/opportunities/OpportunityWorkspacePage.vue`
- Create: `frontend/src/modules/opportunities/OpportunityWorkspacePage.test.ts`
- Create: `frontend/src/modules/opportunities/opportunityFilters.ts`
- Create: `frontend/src/modules/opportunities/opportunityFilters.test.ts`
- Modify: `frontend/src/main.ts`

**Interfaces:**
- Consumes: existing `TargetAccount`, evidence, review, enrichment, follow-up, and draft functions from `growth/api.ts`.
- Produces URL query keys: `q`, `stage`, `sort`, `selected`.
- Preserves distinction among target accounts, contacts, intent signals, and inbound leads.

- [ ] **Step 1: Write failing URL-state tests**

```ts
expect(parseOpportunityFilters(new URLSearchParams("q=gear&stage=FOLLOW_UP&sort=newest"))).toEqual({
  q: "gear", stage: "FOLLOW_UP", sort: "newest", selected: null,
})
expect(serializeOpportunityFilters({ q: "", stage: "ALL", sort: "score", selected: "acct-1" }))
  .toBe("stage=ALL&sort=score&selected=acct-1")
```

- [ ] **Step 2: Run the filter tests and verify they fail**

Run: `pnpm --dir frontend test -- --run src/modules/opportunities/opportunityFilters.test.ts`

Expected: FAIL because the parser and serializer do not exist.

- [ ] **Step 3: Implement canonical filter parsing**

Unknown stages fall back to `ALL`; unknown sort values fall back to `score`; empty search is omitted. Route state is updated with `router.replace` so selection and filters survive refresh and browser Back.

- [ ] **Step 4: Write the master-detail page test**

```ts
expect(await screen.findByRole("searchbox", { name: "搜索客户机会" })).toBeInTheDocument()
expect(screen.getByRole("list", { name: "客户机会列表" })).toBeInTheDocument()
await user.click(screen.getByRole("button", { name: /查看 .* 的证据/ }))
expect(router.currentRoute.value.query.selected).toBe("acct-1")
expect(screen.getByRole("region", { name: "客户机会详情" })).toHaveTextContent("推荐原因")
expect(screen.getByRole("region", { name: "客户机会详情" })).toHaveTextContent("公开联系路径")
```

- [ ] **Step 5: Implement desktop master-detail and mobile route state**

The list shows company, country, need, source, observed time, evidence state, and follow-up stage. The detail shows score explanation, evidence links, company profile, public contact paths, enrichment, activity, and only currently valid actions. Mobile renders list and detail as separate visual states keyed by `selected`, with a labeled Back action that preserves filters.

- [ ] **Step 6: Run opportunities tests**

Run: `pnpm --dir frontend test -- --run src/modules/opportunities/OpportunityWorkspacePage.test.ts src/modules/opportunities/opportunityFilters.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/opportunities frontend/src/main.ts
git commit -m "feat: add customer opportunity workspace"
```

### Task 6: Build the Content and Publishing Status Workspace

**Files:**
- Create: `frontend/src/modules/publishing/ContentPublishingPage.vue`
- Create: `frontend/src/modules/publishing/ContentPublishingPage.test.ts`
- Create: `frontend/src/modules/publishing/contentWorkflow.ts`
- Create: `frontend/src/modules/publishing/contentWorkflow.test.ts`
- Modify: `frontend/src/main.ts`
- Reuse: `frontend/src/modules/content/ContentReviewDialog.vue`

**Interfaces:**
- Consumes: `listMasterContents`, `listPlatformContents`, existing publishing package/task data already used by mission details.
- Produces tabs `PREPARE`, `AI_DRAFT`, `REVIEW`, `SCHEDULED`, `SUBMITTED`, `PUBLISHED`, `NEEDS_ATTENTION`.
- Maps `SUBMISSION_UNKNOWN` to `SUBMITTED`, never `NEEDS_ATTENTION` with an immediate retry action.

- [ ] **Step 1: Write failing workflow mapping tests**

```ts
expect(contentWorkflowStage({ contentStatus: "DRAFT", publishStatus: null })).toBe("AI_DRAFT")
expect(contentWorkflowStage({ contentStatus: "IN_REVIEW", publishStatus: null })).toBe("REVIEW")
expect(contentWorkflowStage({ contentStatus: "APPROVED", publishStatus: "SCHEDULED" })).toBe("SCHEDULED")
expect(contentWorkflowStage({ contentStatus: "APPROVED", publishStatus: "SUBMISSION_UNKNOWN" })).toBe("SUBMITTED")
expect(canOfferRetry("SUBMISSION_UNKNOWN")).toBe(false)
expect(canOfferRetry("FAILED")).toBe(true)
```

- [ ] **Step 2: Run the workflow tests and verify they fail**

Run: `pnpm --dir frontend test -- --run src/modules/publishing/contentWorkflow.test.ts`

Expected: FAIL because the mapper does not exist.

- [ ] **Step 3: Implement exhaustive content/publish state mapping**

Use exhaustive `switch` statements and a neutral unknown state. Preserve platform, provider, source facts, approval state, and submission ID where available.

- [ ] **Step 4: Write the page test**

```ts
expect(await screen.findByRole("tab", { name: /待人工审核/ })).toBeInTheDocument()
expect(screen.getByRole("tab", { name: /已提交/ })).toBeInTheDocument()
await user.click(screen.getByRole("button", { name: /查看内容/ }))
expect(screen.getByRole("dialog")).toHaveTextContent("LinkedIn")
expect(screen.getByRole("dialog")).toHaveTextContent("证据")
```

- [ ] **Step 5: Implement status-first navigation and platform detail**

Do not split the top level by platform. Open `ContentReviewDialog` or a detail drawer for per-platform variants. Distinguish manual export, direct official API, and Buffer in text. Preserve every existing review and publication safeguard.

- [ ] **Step 6: Run content and publishing tests**

Run: `pnpm --dir frontend test -- --run src/modules/publishing/ContentPublishingPage.test.ts src/modules/publishing/contentWorkflow.test.ts src/modules/content/api.test.ts src/modules/missions/GrowthMissionDetailPage.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/publishing frontend/src/main.ts
git commit -m "feat: organize content by publishing outcome"
```

### Task 7: Reframe Results, My Company, and Settings

**Files:**
- Create: `frontend/src/modules/results/ResultsPage.vue`
- Create: `frontend/src/modules/results/ResultsPage.test.ts`
- Modify: `frontend/src/modules/attribution/ExecutiveAttributionPage.vue`
- Modify: `frontend/src/modules/attribution/ExecutiveAttributionPage.test.ts`
- Modify: `frontend/src/modules/growth/CompanyPage.vue`
- Modify: `frontend/src/modules/growth/CompanyPage.test.ts`
- Modify: `frontend/src/modules/settings/SettingsCenterPage.vue`
- Modify: `frontend/src/modules/settings/SettingsCenterPage.test.ts`
- Modify: `frontend/src/main.ts`

**Interfaces:**
- Results conversion steps: `发现公司`, `人工确认`, `找到联系路径`, `创建跟进`, `获得回复`, `形成询盘`, `成交`.
- Company regions: `公司事实`, `产品事实`, `素材与资料`, `内容准备`, `渠道准备`.
- Default settings groups: `当前阻塞`, `AI 模型`, `推广与发布连接`, `通知与 CRM`; advanced groups remain permission-gated.

- [ ] **Step 1: Write failing Results tests**

```ts
const steps = ["发现公司", "人工确认", "找到联系路径", "创建跟进", "获得回复", "形成询盘", "成交"]
for (const step of steps) expect(await screen.findByText(step)).toBeInTheDocument()
expect(screen.getByText("尚未记录")).toBeInTheDocument()
expect(screen.queryByText(/^0$/)).not.toBeInTheDocument()
```

- [ ] **Step 2: Write failing Company and Settings tests**

```ts
expect(screen.getByRole("region", { name: "公司事实" })).toBeInTheDocument()
expect(screen.getByRole("region", { name: "内容准备" })).toBeInTheDocument()
expect(screen.getByRole("region", { name: "渠道准备" })).toBeInTheDocument()

expect(screen.getAllByTestId("settings-primary-group")).toHaveLength(4)
expect(screen.getByRole("button", { name: "展开高级设置" })).toHaveAttribute("aria-expanded", "false")
```

- [ ] **Step 3: Run the three page suites and verify they fail**

Run: `pnpm --dir frontend test -- --run src/modules/results/ResultsPage.test.ts src/modules/growth/CompanyPage.test.ts src/modules/settings/SettingsCenterPage.test.ts`

Expected: FAIL because the new composition is absent.

- [ ] **Step 4: Implement Results as funnel first, attribution second**

Reuse `MissionAttribution`. Render stored zeros only when the API explicitly returns zero; render `尚未记录` for null or absent values. Provide a table/text alternative for every visual comparison. Keep `AttributionEvidenceDrawer` as the evidence detail.

- [ ] **Step 5: Recompose Company and Settings without moving data ownership**

Company links to existing products, assets, knowledge, and platform accounts contextually. Settings computes the existing AI/channel states but shows their business consequence next to the affected destination. Advanced sections start collapsed and remain role/permission gated.

- [ ] **Step 6: Run page tests**

Run: `pnpm --dir frontend test -- --run src/modules/results/ResultsPage.test.ts src/modules/attribution/ExecutiveAttributionPage.test.ts src/modules/growth/CompanyPage.test.ts src/modules/settings/SettingsCenterPage.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/results frontend/src/modules/attribution frontend/src/modules/growth/CompanyPage.vue frontend/src/modules/growth/CompanyPage.test.ts frontend/src/modules/settings/SettingsCenterPage.vue frontend/src/modules/settings/SettingsCenterPage.test.ts frontend/src/main.ts
git commit -m "feat: align results company and settings with business outcomes"
```

### Task 8: Responsive, Accessibility, Compatibility, and Full Regression

**Files:**
- Create: `frontend/e2e/business-outcome-navigation.spec.ts`
- Modify: `frontend/e2e/zz-growth-workspace-persistence.spec.ts`
- Modify: route/component CSS files touched by Tasks 1–7 only when a failing browser assertion proves the need.

**Interfaces:**
- Verifies desktop at 1440 × 900 and mobile at 390 × 844.
- Verifies old deep links, permission-aware visibility, Back/refresh persistence, one main landmark, focus, and 44px targets.

- [ ] **Step 1: Write failing end-to-end navigation tests**

```ts
await expect(page.getByRole("navigation", { name: "主导航" }).getByRole("link")).toHaveCount(5)
await page.getByRole("link", { name: "客户机会" }).click()
await expect(page).toHaveURL(/\/opportunities/)
await expect(page.getByRole("heading", { name: "客户机会" })).toBeVisible()
await expect(page.locator("main")).toHaveCount(1)
```

Add authenticated tests for:

- desktop five-item navigation;
- mobile drawer open, Escape close, and focus restoration;
- `/missions/:id` remains accessible;
- opportunity `q`, `stage`, `sort`, and `selected` survive refresh and Back;
- unauthorized primary destinations are absent;
- `SUBMISSION_UNKNOWN` content has no ordinary retry action;
- no live external publish or outreach request is executed.

- [ ] **Step 2: Run the focused E2E file and verify it fails**

Run: `pnpm --dir frontend test:e2e -- --grep "business outcome navigation"`

Expected: FAIL until all five routes and responsive states are implemented.

- [ ] **Step 3: Fix only evidenced responsive and accessibility defects**

Keep sidebar focus trapping and reduced-motion behavior. Ensure 44px touch targets, visible focus, text-plus-icon state cues, and one main landmark. Do not add a global CSS rewrite.

- [ ] **Step 4: Run all frontend quality gates**

Run:

```bash
pnpm --dir frontend test -- --run
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend api:check
pnpm --dir frontend build
pnpm --dir frontend test:e2e
```

Expected: all commands succeed; E2E must not perform real external publication, outreach, paid API calls, or account authorization.

- [ ] **Step 5: Run backend compatibility tests without changing backend code**

Run from the repository root:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend -q
```

Expected: no API contract, permission, publishing-state, or persistence regressions.

- [ ] **Step 6: Perform bounded visual verification**

Capture desktop and mobile screenshots for Today, Promotion, Opportunities, Content & Publishing, Results, Company, and Settings in one batch. Fix all P0/P1 presentation defects in one batch, then perform one confirmation batch and stop.

- [ ] **Step 7: Commit**

```bash
git add frontend/e2e frontend/src
git commit -m "test: verify business-outcome workspace flows"
```

## Final Acceptance

- Five primary destinations are present and permission-aware.
- Today answers opportunity, blocker, evidence, and next action without fake data.
- Promotion resumes existing progress and exposes one current step.
- Opportunities preserves filters and selection across refresh and Back.
- Content is organized by workflow status and unknown submissions cannot be ordinarily retried.
- Results starts with the true discovery-to-order path and explains missing records.
- Company owns business facts; Settings owns system behavior.
- Legacy deep links work.
- No backend, independent website, real account, real external write, or paid service is touched.
- Full frontend tests, API check, typecheck, lint, build, browser flows, and backend compatibility tests pass.
