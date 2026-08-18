# Core UI Phase One Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing admin-style frontend into a task-oriented SinofGear growth cockpit for daily work, customer discovery, content production, and human approval.

**Architecture:** Keep the current Vue 3 routes, APIs, and business behavior, but introduce a small shared visual layer (`AppIcon`, `WorkspaceHeader`, `EmptyState`) and use it across the first-batch workspaces. Navigation remains permission-aware; route permissions and visible entry permissions share the same capability names. Large business pages are reorganized through clear workspace sections and progressive disclosure instead of changing backend contracts.

**Tech Stack:** Vue 3, TypeScript, Vue Router, TanStack Vue Query, Vitest, Testing Library, project-local SVG icons, CSS custom properties.

## Global Constraints

- Base work on `origin/feature/phase-a` commit `2314ba0e51332af3422a2262828643e19f9ff428` or newer.
- Do not add real-email integration, CRM, quotation, order, or payment scope.
- Do not fabricate dashboard, lead, content, publishing, or metric data.
- Keep every AI-generated or externally published action behind the existing human-review rules.
- Use one project-local SVG icon system; do not use emoji, Chinese-character glyphs, icon fonts, or mixed icon libraries.
- Preserve keyboard navigation, focus trapping, reduced-motion support, and permission-based route protection.
- Use `RouterLink` for internal navigation.
- Body copy must remain at least 14px; 12px is reserved for metadata and captions.

---

### Task 1: Navigation permissions and icon system

**Files:**
- Create: `frontend/src/shared/components/AppIcon.vue`
- Create: `frontend/src/shared/components/AppIcon.test.ts`
- Create: `frontend/src/app/navigation.ts`
- Modify: `frontend/src/app/AppShell.vue`
- Modify: `frontend/src/app/AppShell.test.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/router.test.ts`

**Interfaces:**
- Produces: `IconName`, `AppIcon` props `{ name: IconName; size?: number; strokeWidth?: number }`.
- Produces: `navigationSections` and `utilityNavigation` consumed by `AppShell.vue`.
- Route permissions: content factory uses `content.manage`; approval center uses `agents.approve`.

- [ ] **Step 1: Write failing icon and permission tests**

```ts
it("renders a real decorative SVG for a named icon", () => {
  const { container } = render(AppIcon, { props: { name: "calendar-days" } })
  expect(container.querySelector('svg[data-icon="calendar-days"]')).toBeInTheDocument()
  expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true")
})

it("lets an approver open the approval center without campaign permission", async () => {
  const client = queryClient()
  client.setQueryData(["auth", "me"], {
    user: {}, organization: {}, membership: { role: "OPERATOR", permissions: ["agents.approve"] },
  })
  const appRouter = router(client)
  await appRouter.push("/agent-approvals")
  expect(appRouter.currentRoute.value.name).toBe("agent-approvals")
})
```

- [ ] **Step 2: Run focused tests and confirm failures are caused by missing SVG icons and mismatched permissions**

Run: `./node_modules/.bin/vitest run src/shared/components/AppIcon.test.ts src/app/AppShell.test.ts src/app/router.test.ts`

- [ ] **Step 3: Implement `AppIcon`, typed navigation data, stable approval entry, and matching permissions**

```ts
export type IconName = "calendar-days" | "users-round" | "map-pinned" | "sparkles"
  | "clipboard-check" | "calendar-clock" | "share-2" | "chart-column"
  | "package-search" | "book-open" | "images" | "building-2" | "settings"
  | "circle-check" | "panel-left" | "chevron-down" | "log-out"
```

- [ ] **Step 4: Run the focused tests until green, then refactor duplicate menu markup**

- [ ] **Step 5: Commit the independently testable navigation and icon change**

### Task 2: Shared workspace visual primitives

**Files:**
- Create: `frontend/src/shared/components/WorkspaceHeader.vue`
- Create: `frontend/src/shared/components/EmptyState.vue`
- Create: `frontend/src/shared/components/WorkspacePrimitives.test.ts`
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/src/styles/base.css`

**Interfaces:**
- `WorkspaceHeader`: props `eyebrow`, `title`, `description`; slots `actions`, `meta`.
- `EmptyState`: props `icon`, `title`, `description`; default slot for one primary and optional secondary action.

- [ ] **Step 1: Write failing behavior tests for semantic heading, description, actions, and SVG empty state**

```ts
it("renders one page heading and keeps actions discoverable", () => {
  render(WorkspaceHeader, {
    props: { eyebrow: "今天", title: "今天先做这三件事", description: "按优先级处理。" },
    slots: { actions: '<button type="button">处理全部</button>' },
  })
  expect(screen.getByRole("heading", { level: 1, name: "今天先做这三件事" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "处理全部" })).toBeInTheDocument()
})
```

- [ ] **Step 2: Verify the tests fail because the primitives do not exist**

- [ ] **Step 3: Implement the primitives and industrial visual tokens**

```css
:root {
  --sg-canvas: #f5f6f3;
  --sg-surface: #ffffff;
  --sg-ink: #17212b;
  --sg-brand: #164f7a;
  --sg-accent: #b86738;
  --sg-space-1: 4px;
  --sg-space-2: 8px;
  --sg-space-3: 12px;
  --sg-space-4: 16px;
  --sg-space-6: 24px;
}
```

- [ ] **Step 4: Run primitive tests and existing shell tests until green**

- [ ] **Step 5: Commit the shared visual layer**

### Task 3: Today action cockpit

**Files:**
- Create: `frontend/src/modules/dashboard/TodayActionList.vue`
- Create: `frontend/src/modules/dashboard/TodayActionList.test.ts`
- Modify: `frontend/src/modules/dashboard/DashboardPage.vue`
- Modify: `frontend/src/modules/dashboard/DashboardPage.test.ts`

**Interfaces:**
- `TodayActionList` consumes literal `items: Array<{ id; icon; title; description; count?; to; tone }>`.
- The dashboard derives actions only from persisted workspace data; empty collections yield truthful setup actions.

- [ ] **Step 1: Write failing tests for an action-first heading and truthful empty actions**

```ts
expect(screen.getByRole("heading", { level: 1, name: "今天先做这三件事" })).toBeInTheDocument()
expect(screen.getByRole("link", { name: /发现客户/ })).toHaveAttribute("href", "/opportunities")
expect(screen.getByRole("link", { name: /补充公司事实/ })).toHaveAttribute("href", "/company")
expect(screen.queryByText(/模拟|Demo Buyer|72 \/ 100/)).not.toBeInTheDocument()
```

- [ ] **Step 2: Run `DashboardPage.test.ts` and verify the new assertions fail**

- [ ] **Step 3: Implement the priority action strip, compact opportunity list, and secondary performance panels**

- [ ] **Step 4: Run dashboard tests until green without weakening the existing no-demo assertions**

- [ ] **Step 5: Commit the dashboard workspace**

### Task 4: Customer opportunity master-detail workspace

**Files:**
- Create: `frontend/src/modules/growth/OpportunityWorkspaceNav.vue`
- Create: `frontend/src/modules/growth/OpportunityWorkspaceNav.test.ts`
- Modify: `frontend/src/modules/growth/OpportunitiesPage.vue`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`
- Modify: `frontend/src/modules/growth/growth-pages.css`

**Interfaces:**
- `OpportunityWorkspaceNav` exposes local tabs `机会队列`, `客户发现`, `名单导入`, `老客激活` using buttons and emits `select`.
- Existing opportunity selection, evidence, draft, and follow-up APIs remain unchanged.

- [ ] **Step 1: Write failing tests for local workspace navigation and a master-detail customer layout**

```ts
expect(screen.getByRole("navigation", { name: "客户工作区" })).toBeInTheDocument()
expect(screen.getByRole("button", { name: "机会队列" })).toHaveAttribute("aria-current", "page")
expect(screen.getByRole("region", { name: "客户列表" })).toBeInTheDocument()
expect(screen.getByRole("region", { name: "客户详情" })).toBeInTheDocument()
```

- [ ] **Step 2: Verify focused tests fail on the current stacked-card page**

- [ ] **Step 3: Reorganize existing components into tabs and the list/detail workspace without changing API calls**

- [ ] **Step 4: Run opportunity and growth-workspace tests until green**

- [ ] **Step 5: Commit the customer workspace**

### Task 5: Content and review workflow navigation

**Files:**
- Create: `frontend/src/modules/content/ContentWorkspaceNav.vue`
- Create: `frontend/src/modules/content/ContentWorkspaceNav.test.ts`
- Modify: `frontend/src/modules/content/ContentFactoryPage.vue`
- Modify: `frontend/src/modules/content/ReviewCenterPage.vue`
- Modify: `frontend/src/modules/content/ContentReviewDialog.vue`
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`
- Modify: `frontend/src/modules/content/ReviewCenterPage.test.ts`

**Interfaces:**
- `ContentWorkspaceNav` uses RouterLinks for `创建内容`, `审核内容`, `发布日历`, `平台账户` and marks the active route.
- Review dialogs present content and evidence first; raw provenance remains in a collapsed `details` element.

- [ ] **Step 1: Write failing tests for workflow navigation and human-language review hierarchy**

```ts
expect(screen.getByRole("navigation", { name: "内容与发布工作区" })).toBeInTheDocument()
expect(screen.getByRole("link", { name: "审核内容" })).toHaveAttribute("href", "/reviews")
expect(screen.getByText("技术与来源详情").closest("details")).not.toHaveAttribute("open")
```

- [ ] **Step 2: Verify the tests fail on missing workspace navigation and exposed technical data**

- [ ] **Step 3: Implement shared workflow navigation, clearer page headers, and progressive disclosure**

- [ ] **Step 4: Run content factory and review tests until green**

- [ ] **Step 5: Commit the content workflow**

### Task 6: Human approval workspace

**Files:**
- Create: `frontend/src/modules/growth/AgentApprovalCard.vue`
- Create: `frontend/src/modules/growth/AgentApprovalCard.test.ts`
- Modify: `frontend/src/modules/growth/AgentApprovalsPage.vue`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`
- Modify: `frontend/src/modules/growth/growth-pages.css`

**Interfaces:**
- `AgentApprovalCard` receives an `AgentRun` and emits `approve` or `reject` with the run id.
- Primary view shows goal, requested action, affected object, risk explanation, and human decision; `tool_name`, args, step outcome, and reasoning live under collapsed technical details.

- [ ] **Step 1: Write failing tests for human-language approval cards and collapsed technical details**

```ts
expect(screen.getByRole("heading", { name: "等待你决定" })).toBeInTheDocument()
expect(screen.getByRole("button", { name: "批准执行" })).toBeInTheDocument()
expect(screen.getByRole("button", { name: "拒绝" })).toBeInTheDocument()
expect(screen.getByText("技术执行记录").closest("details")).not.toHaveAttribute("open")
```

- [ ] **Step 2: Verify the tests fail against the current developer-console layout**

- [ ] **Step 3: Extract the approval card and simplify page sections without changing approval API semantics**

- [ ] **Step 4: Run approval and growth-workspace tests until green**

- [ ] **Step 5: Commit the approval workspace**

### Task 7: Internal links, responsive behavior, and release verification

**Files:**
- Modify: first-batch Vue files containing internal `<a href>` navigation
- Modify: `frontend/src/styles/base.css`
- Modify: `frontend/src/modules/growth/growth-pages.css`
- Modify: affected focused tests

**Interfaces:**
- All internal routes use `RouterLink` and preserve SPA navigation.
- Layout breakpoints support 1440px, 1024px, and 390px viewports without horizontal page overflow.

- [ ] **Step 1: Add failing interaction assertions for internal navigation and narrow-screen workspace access**

- [ ] **Step 2: Verify the new assertions fail for raw anchors or inaccessible compact layouts**

- [ ] **Step 3: Replace internal anchors, finish responsive CSS, and preserve visible focus states**

- [ ] **Step 4: Run focused tests, then the complete release gate**

Run:

```bash
./node_modules/.bin/eslint .
./node_modules/.bin/vue-tsc --noEmit
./node_modules/.bin/vitest run
./node_modules/.bin/vite build
node scripts/generate-api.mjs check
```

- [ ] **Step 5: Inspect `git diff --check`, review the requirements line by line, and commit the verified first batch**
