# Agent Workbench Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize SinofGear into a bright, task-first AI growth workbench with a visible Agent center, administrator-managed DeepSeek configuration, discoverable five-channel social operations, and a concise executive effectiveness page.

**Architecture:** Preserve the existing Vue 3/Django domain services and route compatibility, but add focused presentation components and an organization-scoped AI configuration boundary. Agent runs persist their execution mode and model identity so the UI never infers historical behavior from current settings. Secret handling remains server-only and encrypted; all external actions retain existing permission and approval gates.

**Tech Stack:** Vue 3.5, TypeScript 5.8, Vue Router 4.5, TanStack Vue Query 5, Vitest 3, Django 5.2, Django REST Framework 3.16, PostgreSQL, AES-GCM via `cryptography`, pytest.

## Global Constraints

- Use the approved bright palette: `#1687FF` primary, `#0875EB` active, `#EAF4FF` soft blue, `#F5F9FE` page background, `#FFFFFF` cards, `#102A56` primary text, and `#66809F` secondary text.
- Do not add a live-email connection or activate outbound email.
- Never expose, log, serialize, cache, or echo an AI API key.
- Keep `/promotion` as a compatible route while presenting it as “社媒运营”.
- Always show Facebook, Instagram, LinkedIn, TikTok, and YouTube readiness; never hide unconfigured providers.
- Label `AI Agent`, `AI 生成任务`, and `自动化流程` truthfully and separately.
- Real publishing and customer outreach remain behind explicit human approval and existing permissions.
- Fake mode must remain visibly labeled `离线演示`; it must not be described as a real model decision.
- Empty states show one useful next action and do not synthesize zero-value performance.
- Use existing `AppIcon` SVGs or add matching inline SVG symbols; do not use Emoji as product icons.
- Preserve organization isolation, CSRF protection, audit redaction, daily budget reservation, and existing publishing safety gates.

---

### Task 1: Bright Theme and Discoverable Workspace Navigation

**Files:**
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/src/styles/base.css`
- Modify: `frontend/src/app/navigation.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/shared/components/AppIcon.vue`
- Test: `frontend/src/app/AppShell.test.ts`
- Test: `frontend/src/app/router.test.ts`

**Interfaces:**
- Consumes: existing `NavigationSection`, `NavigationItem`, route permission metadata, and `AppIcon`.
- Produces: `/agent-workspace` route named `agent-workspace`; visible navigation labels `Agent 工作台` and `社媒运营`; bright CSS tokens consumed by all later UI tasks.

- [ ] **Step 1: Write failing navigation tests**

Add assertions that an operator with `agents.run`, `publishing.read`, and `metrics.read` sees direct links to the Agent workspace, social operations, and effectiveness page:

```ts
expect(screen.getByRole("link", { name: "Agent 工作台" })).toHaveAttribute("href", "/agent-workspace")
expect(screen.getByRole("link", { name: "社媒运营" })).toHaveAttribute("href", "/promotion")
expect(screen.getByRole("link", { name: "经营效果" })).toHaveAttribute("href", "/analytics")
```

Add a router assertion that `/agent-workspace` requires `agents.run`, while `/promotion` retains its route name and now reports the title `社媒运营`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd frontend && pnpm test --run src/app/AppShell.test.ts src/app/router.test.ts
```

Expected: FAIL because `Agent 工作台` and `社媒运营` are absent from `navigationSections`, and the `agent-workspace` route does not exist.

- [ ] **Step 3: Implement the navigation and theme tokens**

Add navigation entries with explicit permissions:

```ts
{ label: "Agent 工作台", to: "/agent-workspace", icon: "bot", requiredPermission: "agents.run" }
{ label: "社媒运营", to: "/promotion", icon: "send", requiredPermission: "publishing.read" }
```

Add `bot` and `send` to `IconName` and render them with the same stroke width and view box used by existing icons. Add `AgentWorkspace` to `AppRouteComponents` and register `/agent-workspace`; for this independently buildable slice, bind it to the existing `AgentApprovalsPage` component. Task 6 replaces that binding with the async `AgentWorkspacePage` after the new page exists. Change the `/promotion` route title to `社媒运营` and the `/analytics` title to `经营效果`.

Replace the core visual tokens with:

```css
:root {
  --sg-brand: #1687ff;
  --sg-brand-strong: #0875eb;
  --sg-brand-soft: #eaf4ff;
  --sg-canvas: #f5f9fe;
  --sg-surface: #fff;
  --sg-ink: #102a56;
  --sg-muted: #66809f;
  --sg-success: #28b887;
  --sg-warning: #ffaa3d;
  --sg-danger: #ef5b5b;
  --sg-line: #dceafd;
  --sg-shadow: 0 12px 34px rgb(44 126 206 / 10%);
}
```

Keep body text contrast at WCAG AA and remove large dark-blue blocks from shared shell styles.

- [ ] **Step 4: Run focused tests, lint the touched files, and verify GREEN**

Run:

```bash
cd frontend && pnpm test --run src/app/AppShell.test.ts src/app/router.test.ts && pnpm lint
```

Expected: PASS with no ESLint warnings.

- [ ] **Step 5: Commit the theme and navigation slice**

```bash
git add frontend/src/styles/tokens.css frontend/src/styles/base.css frontend/src/app/navigation.ts frontend/src/app/router.ts frontend/src/main.ts frontend/src/shared/components/AppIcon.vue frontend/src/app/AppShell.test.ts frontend/src/app/router.test.ts
git commit -m "feat: expose bright growth workspace navigation"
```

---

### Task 2: Task-First Today Dashboard and Side Rail

**Files:**
- Create: `frontend/src/modules/dashboard/DashboardKpiStrip.vue`
- Create: `frontend/src/modules/dashboard/DashboardSideRail.vue`
- Create: `frontend/src/modules/dashboard/DashboardTrendCard.vue`
- Modify: `frontend/src/modules/dashboard/DashboardPage.vue`
- Modify: `frontend/src/modules/dashboard/TodayActionList.vue`
- Modify: `frontend/src/modules/dashboard/DashboardPage.test.ts`
- Create: `frontend/src/modules/dashboard/DashboardSideRail.test.ts`

**Interfaces:**
- Consumes: `growthWorkspaceQueryOptions()`, `agentRunsQueryOptions()`, `getProductAIStatus()`, and the existing current-user query.
- Produces: `DashboardKpiStrip` props `{ opportunities, approvals, readyToPublish, inquiries }`; `DashboardSideRail` props `{ modelStatus, pendingRuns, channelIssues, completedRuns }`; compact `DashboardTrendCard` for seven-day recorded activity.

- [ ] **Step 1: Write failing dashboard behavior tests**

Assert that the dashboard shows exactly four top-level KPI labels and a right-rail region:

```ts
expect(await screen.findByRole("region", { name: "今日核心状态" })).toBeVisible()
expect(screen.getByText("新机会")).toBeVisible()
expect(screen.getByText("等待审批")).toBeVisible()
expect(screen.getByText("待发布")).toBeVisible()
expect(screen.getByText("有效询盘")).toBeVisible()
expect(screen.getByRole("complementary", { name: "工作台状态" })).toBeVisible()
```

Add an empty-state assertion proving that absent metrics render `无数据` and a single setup link rather than four fabricated zeros.

- [ ] **Step 2: Run dashboard tests and verify RED**

Run:

```bash
cd frontend && pnpm test --run src/modules/dashboard/DashboardPage.test.ts src/modules/dashboard/DashboardSideRail.test.ts
```

Expected: FAIL because the KPI strip, complementary rail, and compact trend component do not exist.

- [ ] **Step 3: Implement focused dashboard components**

Use a desktop 8:4 grid and collapse to one column below 1100px:

```css
.dashboard-workbench {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
  gap: 20px;
}
@media (max-width: 1100px) {
  .dashboard-workbench { grid-template-columns: 1fr; }
}
```

Limit `TodayActionList` to five actions. Derive KPI values only from non-demo persisted records. In the side rail, show model mode, the first three pending approvals, five-channel connection issues, and the last three completed Agent runs. Every empty section must link to the one relevant setup page.

- [ ] **Step 4: Run dashboard tests and verify GREEN**

Run:

```bash
cd frontend && pnpm test --run src/modules/dashboard/DashboardPage.test.ts src/modules/dashboard/DashboardSideRail.test.ts
```

Expected: PASS, including the no-fabricated-zero assertion.

- [ ] **Step 5: Commit the dashboard slice**

```bash
git add frontend/src/modules/dashboard
git commit -m "feat: turn today into a task-first workbench"
```

---

### Task 3: Organization-Scoped Encrypted DeepSeek Configuration

**Files:**
- Modify: `backend/apps/ai/models.py`
- Create: `backend/apps/ai/migrations/0006_organizationaiproviderconfig.py`
- Create: `backend/apps/ai/provider_config.py`
- Modify: `backend/integrations/ai/providers.py`
- Modify: `backend/apps/ai/runtime.py`
- Modify: `backend/apps/ai/serializers.py`
- Modify: `backend/apps/ai/views.py`
- Modify: `backend/apps/ai/urls.py`
- Modify: `backend/apps/ai/services.py`
- Modify: `backend/apps/ai/orchestration.py`
- Create: `backend/apps/ai/tests/test_provider_config_api.py`
- Test: `backend/integrations/ai/tests/test_deepseek_provider.py`
- Test: `backend/apps/ai/tests/test_ai_budget.py`

**Interfaces:**
- Consumes: `integrations.secrets.encrypt_secret/decrypt_secret`, `CanManageCredentials`, existing `AIRun.provider_metadata`, and organization token-budget locking.
- Produces: `OrganizationAIProviderConfig`, `resolve_product_ai(organization) -> ProductAIRuntime`, `GET/PUT/DELETE /api/v1/ai/provider-config`, and `POST /api/v1/ai/provider-config/test`.

- [ ] **Step 1: Write failing model, permission, redaction, and isolation tests**

Create tests proving:

```python
response = admin_client.put("/api/v1/ai/provider-config", {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "api_key": "fixture-secret-key",
    "enabled": True,
    "daily_budget_micros": 500_000,
}, format="json")
assert response.status_code == 200
assert response.data["configured"] is True
assert "api_key" not in response.data
assert "fixture-secret-key" not in str(response.data)
```

Also assert that a non-administrator or user without `credentials.manage` receives 403, a second organization cannot read the first configuration, DELETE clears ciphertext, invalid model values return 400, and API errors never contain the submitted key.

- [ ] **Step 2: Run provider configuration tests and verify RED**

Run:

```bash
cd backend && python -m pytest apps/ai/tests/test_provider_config_api.py integrations/ai/tests/test_deepseek_provider.py -q
```

Expected: FAIL because the model, resolver, and endpoints do not exist and `DeepSeekAIProvider` only reads environment variables.

- [ ] **Step 3: Add the encrypted configuration model and resolver**

Add one row per organization:

```python
class OrganizationAIProviderConfig(models.Model):
    organization = models.OneToOneField(
        "identity.Organization", on_delete=models.PROTECT, related_name="ai_provider_config"
    )
    provider = models.CharField(max_length=32, default="deepseek")
    model = models.CharField(max_length=64, default="deepseek-chat")
    encrypted_api_key = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=False)
    daily_budget_micros = models.PositiveBigIntegerField(null=True, blank=True)
    daily_spent_micros = models.PositiveBigIntegerField(default=0)
    daily_reserved_micros = models.PositiveBigIntegerField(default=0)
    spent_on = models.DateField(null=True, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

`resolve_product_ai()` must prefer an enabled organization row, decrypt only inside the server process, and return a provider instance constructed with explicit `api_key` and `model`. If no organization row exists, preserve the existing environment/Fake compatibility behavior.

- [ ] **Step 4: Refactor DeepSeek provider injection and add fixed-host connection testing**

Change construction to:

```python
DeepSeekAIProvider(api_key=secret_value, model=model, opener=urlopen)
```

Keep `https://api.deepseek.com/chat/completions` fixed in code. Do not accept a Base URL from request data. The connection test sends a bounded JSON request with `max_tokens=1`, validates HTTP/JSON shape, records only safe status/latency, and never persists response content.

- [ ] **Step 5: Add conservative cost estimation and daily reservation**

Create a versioned price table for the approved identifiers, using cache-miss input pricing so the estimate is conservative:

```python
DEEPSEEK_USD_PER_MILLION = {
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
}
PRICE_TABLE_VERSION = "deepseek-usd-2026-08-18"
```

`reserve_ai_cost()` locks the organization configuration row, resets daily counters when the date changes, reserves a maximum per-request estimate, and raises `AIBudgetExceeded` before network access. `settle_ai_cost()` replaces the reservation with actual token-based estimated cost from provider usage. Persist `price_table_version` and `estimated_cost_micros` in sanitized provider metadata. Label all UI values as estimated because DeepSeek prices may change.

Keep the existing `Organization.ai_daily_token_budget` and `reserve_ai_budget()` token guard intact. A request must pass both limits: the existing token/concurrency guard and the new administrator-configured estimated USD guard. Settlement releases both reservations in `finally` paths so a provider failure cannot strand budget.

- [ ] **Step 6: Implement safe serializers and endpoints**

GET returns only:

```json
{
  "provider": "deepseek",
  "model": "deepseek-chat",
  "configured": true,
  "enabled": true,
  "daily_budget_micros": 500000,
  "daily_spent_micros": 1200,
  "daily_reserved_micros": 0,
  "price_table_version": "deepseek-usd-2026-08-18",
  "last_tested_at": null,
  "last_success_at": null,
  "last_error_code": ""
}
```

PUT replaces the key only when a non-empty `api_key` is supplied; omitting it retains the existing encrypted value. DELETE clears the ciphertext and disables the row. POST `/test` requires a configured key and updates safe connection metadata.

- [ ] **Step 7: Run backend tests and verify GREEN**

Run:

```bash
cd backend && python -m pytest apps/ai/tests/test_provider_config_api.py integrations/ai/tests/test_deepseek_provider.py apps/ai/tests/test_ai_budget.py apps/ai/tests/test_ai_orchestration.py -q
```

Expected: PASS with no secret text in captured logs or serialized output.

- [ ] **Step 8: Commit the encrypted provider slice**

```bash
git add backend/apps/ai backend/integrations/ai
git commit -m "feat: add encrypted organization AI configuration"
```

---

### Task 4: Administrator AI Model Settings Page

**Files:**
- Create: `frontend/src/modules/settings/AIModelSettingsPage.vue`
- Create: `frontend/src/modules/settings/AIModelSettingsPage.test.ts`
- Modify: `frontend/src/modules/settings/api.ts`
- Modify: `frontend/src/modules/settings/SettingsCenterPage.vue`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/app/router.test.ts`

**Interfaces:**
- Consumes: Task 3 provider configuration endpoints and current-user role/permissions.
- Produces: administrator route `/settings/ai-model`; `getAIProviderConfig`, `saveAIProviderConfig`, `testAIProviderConfig`, and `deleteAIProviderConfig` API functions.

- [ ] **Step 1: Write failing settings-page tests**

Cover the safe configuration states:

```ts
expect(await screen.findByRole("heading", { name: "AI 模型" })).toBeVisible()
expect(screen.getByLabelText("Provider")).toHaveValue("deepseek")
expect(screen.getByLabelText("模型")).toHaveValue("deepseek-chat")
expect(screen.getByLabelText("API Key")).toHaveValue("")
expect(screen.queryByDisplayValue("fixture-secret-key")).not.toBeInTheDocument()
expect(screen.getByRole("button", { name: "测试连接" })).toBeEnabled()
```

Add cases for configuration-required, configured, invalid-key, disabled, budget-exceeded, and non-administrator route rejection.

- [ ] **Step 2: Run focused settings tests and verify RED**

Run:

```bash
cd frontend && pnpm test --run src/modules/settings/AIModelSettingsPage.test.ts src/app/router.test.ts
```

Expected: FAIL because the page, route, and API functions do not exist.

- [ ] **Step 3: Implement the administrator configuration UI**

Render a bright two-column desktop layout: configuration form on the left and safe status/estimated usage on the right. Provider is fixed to DeepSeek. The model selector contains the backend allowlist. The password input always initializes empty and clears after every mutation.

The form actions are:

- `保存配置`
- `测试连接`
- `停用真实模型` / `启用真实模型`
- `删除密钥`

Require a confirmation dialog before deletion. Show budget values as estimated USD and include the price-table version. Never put API Key data into Vue Query keys, mutation results, error text, or persisted browser storage.

- [ ] **Step 4: Run settings tests, typecheck, and verify GREEN**

Run:

```bash
cd frontend && pnpm test --run src/modules/settings/AIModelSettingsPage.test.ts src/modules/settings/SettingsCenterPage.test.ts src/app/router.test.ts && pnpm typecheck
```

Expected: PASS with no TypeScript errors.

- [ ] **Step 5: Commit the model settings slice**

```bash
git add frontend/src/modules/settings frontend/src/app/router.ts frontend/src/app/router.test.ts frontend/src/main.ts
git commit -m "feat: add administrator AI model settings"
```

---

### Task 5: Truthful Agent Execution Metadata and Bounded LLM Planning

**Files:**
- Modify: `backend/apps/growth/models.py`
- Create: `backend/apps/growth/migrations/0045_agentrun_execution_metadata.py`
- Create: `backend/apps/growth/agent/execution.py`
- Modify: `backend/apps/growth/agent/acquisition.py`
- Modify: `backend/apps/growth/agent/content_tools.py`
- Modify: `backend/apps/growth/agent/content_creation_tools.py`
- Modify: `backend/apps/growth/agent/publishing_tools.py`
- Modify: `backend/apps/growth/agent/resume.py`
- Modify: `backend/apps/growth/agent_views.py`
- Test: `backend/apps/growth/tests/test_agent_persistence.py`
- Test: `backend/apps/growth/tests/test_content_agent.py`
- Test: `backend/apps/growth/tests/test_publishing_agent.py`
- Test: `backend/apps/growth/tests/test_agent_api.py`

**Interfaces:**
- Consumes: Task 3 `resolve_product_ai(organization)`, `LLMPlanner`, `DeterministicPlanner`, and existing tool registries.
- Produces: persisted `execution_mode`, `planner_provider`, and `planner_model` on `AgentRun`; safe serializer fields used by the frontend Agent workspace.

- [ ] **Step 1: Write failing execution-truth tests**

Add tests proving:

```python
assert run.execution_mode == "AI_AGENT"
assert run.planner_provider == "deepseek"
assert run.planner_model == "deepseek-chat"
```

for a configured acquisition or social-strategy run, while Fake/offline content creation reports `AI_GENERATION` only for its generation stage and fixed platform variants report `AUTOMATION`. Assert that resuming an approved run uses the persisted planner identity and cannot silently switch from AI to deterministic planning.

Add API assertions for `agent_type`, `execution_mode`, `planner_provider`, and `planner_model`, with no key or raw secret fields.

- [ ] **Step 2: Run Agent backend tests and verify RED**

Run:

```bash
cd backend && python -m pytest apps/growth/tests/test_agent_persistence.py apps/growth/tests/test_content_agent.py apps/growth/tests/test_publishing_agent.py apps/growth/tests/test_agent_api.py -q
```

Expected: FAIL because execution metadata is not persisted, content/social strategy always use deterministic planners, and resume currently reconstructs a different planner for some runs.

- [ ] **Step 3: Add execution metadata and one resolver**

Add fields with safe defaults:

```python
execution_mode = models.CharField(max_length=24, default="AUTOMATION")
planner_provider = models.CharField(max_length=32, blank=True, default="")
planner_model = models.CharField(max_length=64, blank=True, default="")
```

Implement:

```python
@dataclass(frozen=True)
class AgentExecution:
    mode: str
    provider: str
    model: str
    planner: Planner

def resolve_agent_execution(*, organization, fallback: Planner, allow_llm: bool) -> AgentExecution:
    ...
```

The resolver returns `AI_AGENT` only when the organization has an enabled, configured real provider and `allow_llm=True`; otherwise it returns `AUTOMATION` and the supplied deterministic planner.

- [ ] **Step 4: Enable bounded LLM planning only where it adds judgment**

Use `allow_llm=True` for acquisition, content strategy, and social strategy. Keep content brief writes, platform variant creation, scheduling, and publication as deterministic tools behind approval. Content generation runs are labeled `AI_GENERATION` because the model creates output but does not control the workflow.

Persist execution metadata when the run is first created. On resume, reconstruct the same provider/model or fail safely with `planner_configuration_unavailable`; never silently change modes.

- [ ] **Step 5: Run Agent backend tests and verify GREEN**

Run:

```bash
cd backend && python -m pytest apps/growth/tests/test_agent_persistence.py apps/growth/tests/test_content_agent.py apps/growth/tests/test_publishing_agent.py apps/growth/tests/test_agent_api.py -q
```

Expected: PASS, including approval-resume mode preservation.

- [ ] **Step 6: Commit truthful Agent execution**

```bash
git add backend/apps/growth
git commit -m "feat: persist truthful agent execution modes"
```

---

### Task 6: Agent Workspace, Capability Cards, and Business Timeline

**Files:**
- Create: `frontend/src/modules/agents/AgentWorkspacePage.vue`
- Create: `frontend/src/modules/agents/AgentCapabilityCard.vue`
- Create: `frontend/src/modules/agents/AgentRunTimeline.vue`
- Create: `frontend/src/modules/agents/ModelStatusCard.vue`
- Create: `frontend/src/modules/agents/AgentWorkspacePage.test.ts`
- Create: `frontend/src/modules/agents/AgentRunTimeline.test.ts`
- Modify: `frontend/src/modules/growth/agentApi.ts`
- Modify: `frontend/src/modules/growth/AgentApprovalsPage.vue`
- Modify: `frontend/src/app/AppShell.vue`
- Modify: `frontend/src/main.ts`

**Interfaces:**
- Consumes: Task 5 Agent serializer metadata, Task 3 provider status/config summary, and existing start/approve endpoints.
- Produces: primary `/agent-workspace` experience and reusable `AgentRunTimeline` that maps technical steps to business-language states.

- [ ] **Step 1: Write failing Agent workspace tests**

Assert the page exposes four role cards and honest badges:

```ts
expect(await screen.findByRole("heading", { name: "Agent 工作台" })).toBeVisible()
expect(screen.getByRole("heading", { name: "获客 Agent" })).toBeVisible()
expect(screen.getByRole("heading", { name: "内容 Agent" })).toBeVisible()
expect(screen.getByRole("heading", { name: "社媒 Agent" })).toBeVisible()
expect(screen.getByRole("heading", { name: "客户激活 Agent" })).toBeVisible()
expect(screen.getByText("AI Agent")).toBeVisible()
expect(screen.getByText("自动化流程")).toBeVisible()
```

For the timeline, assert business steps are visible by default while tool args and JSON appear only after opening `技术记录`.

- [ ] **Step 2: Run Agent frontend tests and verify RED**

Run:

```bash
cd frontend && pnpm test --run src/modules/agents/AgentWorkspacePage.test.ts src/modules/agents/AgentRunTimeline.test.ts
```

Expected: FAIL because the Agent module and timeline do not exist.

- [ ] **Step 3: Implement the Agent workspace**

Use a bright header with model/estimated budget/approval summary, a four-card capability grid, and a two-column run area. Map tool outcomes to business labels:

```ts
const outcomeLabels = {
  succeeded: "已完成",
  blocked_approval: "等待你批准",
  failed: "需要处理",
}
```

Use `execution_mode` for badges; never infer from the Agent name. Place task-start forms in a focused modal or drawer instead of a collapsed `<details>` at the bottom. Keep approval buttons attached to the pending timeline step. Retain the technical record as a collapsed disclosure.

Replace the temporary `AgentWorkspace: AgentApprovalsPage` binding from Task 1 with `defineAsyncComponent(() => import("./modules/agents/AgentWorkspacePage.vue"))` in `main.ts`.

- [ ] **Step 4: Redirect the old approval route without breaking links**

Keep `/agent-approvals` routable but render or redirect to `/agent-workspace?view=approvals`. The top badge should link to that filtered view. Tests must prove old bookmarked URLs remain usable.

- [ ] **Step 5: Run Agent frontend tests and verify GREEN**

Run:

```bash
cd frontend && pnpm test --run src/modules/agents src/modules/growth/AgentApprovalsPage.test.ts src/app/AppShell.test.ts && pnpm typecheck
```

Expected: PASS with no raw JSON visible until disclosure opens.

- [ ] **Step 6: Commit the Agent workspace**

```bash
git add frontend/src/modules/agents frontend/src/modules/growth/agentApi.ts frontend/src/modules/growth/AgentApprovalsPage.vue frontend/src/app/AppShell.vue frontend/src/main.ts
git commit -m "feat: add visible agent workbench"
```

---

### Task 7: Restore and Simplify Five-Channel Social Operations

**Files:**
- Create: `frontend/src/modules/social/SocialOperationsPage.vue`
- Create: `frontend/src/modules/social/SocialChannelCard.vue`
- Create: `frontend/src/modules/social/SocialOperationsPage.test.ts`
- Modify: `frontend/src/modules/content/ContentWorkspaceNav.vue`
- Modify: `frontend/src/modules/growth/PromotionPage.vue`
- Modify: `frontend/src/modules/growth/SocialReadinessPanel.vue`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Consumes: existing promotion workspace APIs, platform connection readiness, approved content, publish tasks, manual export packages, and OAuth connection actions.
- Produces: `SocialOperationsPage` at the compatible `/promotion` route; five-state `SocialChannelCard`; five-item content workspace navigation.

- [ ] **Step 1: Write failing social discoverability and readiness tests**

Assert all five providers remain visible even when disabled:

```ts
for (const name of ["Facebook", "Instagram", "LinkedIn", "TikTok", "YouTube"]) {
  expect(await screen.findByRole("heading", { name })).toBeVisible()
}
expect(screen.getByText("需要管理员完成平台配置")).toBeVisible()
expect(screen.getByRole("navigation", { name: "内容与发布工作区" }))
  .toHaveTextContent("社媒运营")
```

Add cases for connected, reauthorization-required, waiting-platform-review, private-only, and manual-package states.

- [ ] **Step 2: Run social tests and verify RED**

Run:

```bash
cd frontend && pnpm test --run src/modules/social/SocialOperationsPage.test.ts src/modules/growth/GrowthWorkspacePages.test.ts
```

Expected: FAIL because `/promotion` is not represented in the content workspace navigation and the existing page presents too many unrelated sections before channel readiness.

- [ ] **Step 3: Build the social operations composition**

Compose existing services into this order:

1. five-channel readiness strip;
2. today’s ready-to-publish items;
3. waiting-review items;
4. schedule and recent tasks;
5. recorded outcomes;
6. manual-package action.

Each channel card contains only channel name, status, one-sentence capability, one recovery message, and one primary action. OAuth-disabled cards link administrators to configuration guidance and never ask for a platform password.

Keep the old `PromotionPage` as a compatibility wrapper or move its focused subcomponents into `SocialOperationsPage`; do not duplicate network queries.

- [ ] **Step 4: Run social tests, existing publishing tests, and verify GREEN**

Run:

```bash
cd frontend && pnpm test --run src/modules/social src/modules/growth/GrowthWorkspacePages.test.ts src/modules/platformAccounts/PlatformAccountsPage.test.ts src/modules/publishing/PublishingCalendarPage.test.ts
```

Expected: PASS, including all five provider cards in configuration-required mode.

- [ ] **Step 5: Commit the social operations slice**

```bash
git add frontend/src/modules/social frontend/src/modules/content/ContentWorkspaceNav.vue frontend/src/modules/growth/PromotionPage.vue frontend/src/modules/growth/SocialReadinessPanel.vue frontend/src/modules/growth/GrowthWorkspacePages.test.ts frontend/src/app/router.ts frontend/src/main.ts
git commit -m "feat: restore five-channel social operations"
```

---

### Task 8: Concise Executive Effectiveness and Moved Detail Workflows

**Files:**
- Create: `frontend/src/modules/analytics/EffectivenessOverview.vue`
- Create: `frontend/src/modules/analytics/EffectivenessKpis.vue`
- Create: `frontend/src/modules/analytics/ChannelComparison.vue`
- Create: `frontend/src/modules/analytics/MetricEntryDrawer.vue`
- Create: `frontend/src/modules/analytics/EffectivenessOverview.test.ts`
- Modify: `frontend/src/modules/growth/EffectivenessPage.vue`
- Modify: `frontend/src/modules/growth/AccountAttributionPanel.vue`
- Modify: `frontend/src/modules/growth/OpportunitiesPage.vue`
- Modify: `frontend/src/modules/growth/OpportunityWorkspaceNav.vue`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`
- Modify: `frontend/src/main.ts`

**Interfaces:**
- Consumes: existing growth workspace, metric receipt, account attribution, publishing, and tracking data.
- Produces: executive `/analytics` overview; opportunity workspace `funnel` view; secondary metric-entry drawer; existing `/admin/analytics` technical tracking page remains unchanged.

- [ ] **Step 1: Write failing effectiveness-scope tests**

Assert the main page includes only executive content by default:

```ts
expect(await screen.findByRole("heading", { name: "经营效果" })).toBeVisible()
expect(screen.getByText("有效客户")).toBeVisible()
expect(screen.getByText("已批准内容")).toBeVisible()
expect(screen.getByText("已发布内容")).toBeVisible()
expect(screen.getByText("有效询盘")).toBeVisible()
expect(screen.queryByRole("form", { name: "手工回填渠道结果" })).not.toBeInTheDocument()
expect(screen.queryByRole("heading", { name: "账户获客漏斗" })).not.toBeInTheDocument()
```

Add an opportunity-page assertion that selecting `转化漏斗` renders `AccountAttributionPanel`. Add a drawer test showing manual metric fields only after pressing `录入数据`.

- [ ] **Step 2: Run effect and opportunity tests and verify RED**

Run:

```bash
cd frontend && pnpm test --run src/modules/analytics/EffectivenessOverview.test.ts src/modules/growth/GrowthWorkspacePages.test.ts
```

Expected: FAIL because the effect page embeds the full account funnel and always-visible manual backfill form.

- [ ] **Step 3: Implement executive overview selectors and components**

Derive four KPIs strictly from persisted non-demo records. Use `null` for unavailable metrics and render `无数据`, never numeric zero unless a real denominator exists. Show a compact 30-day trend and channel comparison only when recorded data exists. Display one next action derived from the strongest real gap, such as unreviewed content or disconnected channels; label deterministic suggestions `系统建议`, not `AI 建议`, unless a real AI run produced them.

- [ ] **Step 4: Move the account funnel and data-entry form**

Add `funnel` to `OpportunityWorkspace` and render `AccountAttributionPanel` there. Move manual metric fields into `MetricEntryDrawer`, opened by `录入数据`. Keep tracking/short-link management solely under `/admin/analytics`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
cd frontend && pnpm test --run src/modules/analytics/EffectivenessOverview.test.ts src/modules/growth/GrowthWorkspacePages.test.ts src/modules/analytics/AnalyticsPage.test.ts
```

Expected: PASS, with the main effect page free of account records and manual forms until explicitly opened.

- [ ] **Step 6: Commit the effectiveness slice**

```bash
git add frontend/src/modules/analytics frontend/src/modules/growth/EffectivenessPage.vue frontend/src/modules/growth/AccountAttributionPanel.vue frontend/src/modules/growth/OpportunitiesPage.vue frontend/src/modules/growth/OpportunityWorkspaceNav.vue frontend/src/modules/growth/GrowthWorkspacePages.test.ts frontend/src/main.ts
git commit -m "feat: simplify executive effectiveness"
```

---

### Task 9: Responsive Polish, Contract Regeneration, and End-to-End Acceptance

**Files:**
- Modify: `frontend/src/styles/base.css`
- Modify: `frontend/src/modules/growth/growth-pages.css`
- Modify: `frontend/src/api/generated/schema.ts`
- Create: `backend/openapi.json`
- Create: `frontend/e2e/agent-workbench.spec.ts`
- Create: `frontend/e2e/ai-model-settings.spec.ts`
- Create: `frontend/e2e/social-operations.spec.ts`
- Modify: `docs/deepseek-product-ai-provider.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: all previous tasks and the existing OpenAPI generation/check scripts.
- Produces: responsive, keyboard-usable workbench; synchronized API contract; E2E proof of primary user journeys; updated provider runbook.

- [ ] **Step 1: Add failing E2E acceptance scenarios**

Implement three fixture-owned flows:

1. operator opens `Agent 工作台`, starts an automation-mode task, opens a run timeline, and sees technical details only after disclosure;
2. administrator opens `AI 模型`, saves a fixture-injected key through the no-network test transport, tests connection, and sees configured status without the key in DOM or browser storage;
3. operator opens `社媒运营`, sees five channels, follows an unconfigured recovery action, and downloads a manual package without any publish endpoint call.

Add viewport checks at 1440px, 1024px, and 390px widths.

- [ ] **Step 2: Run E2E specs and verify RED**

Run:

```bash
cd frontend && pnpm test:e2e -- agent-workbench.spec.ts ai-model-settings.spec.ts social-operations.spec.ts
```

Expected: FAIL on missing final responsive and contract wiring.

- [ ] **Step 3: Regenerate and validate the OpenAPI client**

Run:

```bash
cd backend && python manage.py spectacular --file openapi.json
cd ../frontend && pnpm api:generate && pnpm api:check
```

Review the generated diff and confirm no secret field is present in any response schema. Request payload may contain write-only `api_key`; generated response types must not.

- [ ] **Step 4: Complete responsive and accessibility polish**

At 1440px use the 8:4 grid. Below 1100px stack the rail after main content. Below 860px retain the existing focus-trapped drawer navigation. Ensure status badges contain text, icon buttons have accessible names, tables have headings, timeline order is semantic, and focus returns correctly after drawers/modals close.

- [ ] **Step 5: Update safe configuration documentation**

Document:

- the administrator UI path;
- that API keys are encrypted and never returned;
- environment Fake mode and organization-config precedence;
- the versioned estimated-cost price table;
- the fixed official DeepSeek host;
- the fact that real email remains disconnected;
- the need for separate external platform application review before social publishing becomes available.

`.env.example` keeps `DEEPSEEK_API_KEY=` only as a development compatibility option and explains that production organizations should use the administrator UI.

- [ ] **Step 6: Run full backend verification**

Run:

```bash
cd backend && python -m pytest -q && python -m ruff check .
```

Expected: all backend tests PASS and Ruff reports no violations.

- [ ] **Step 7: Run full frontend verification**

Run:

```bash
cd frontend && pnpm lint && pnpm typecheck && pnpm test --run && pnpm build && pnpm api:check
```

Expected: ESLint PASS, vue-tsc PASS, all Vitest tests PASS, Vite production build PASS, and API contract check PASS.

- [ ] **Step 8: Run the new E2E acceptance suite and verify GREEN**

Run:

```bash
cd frontend && pnpm test:e2e -- agent-workbench.spec.ts ai-model-settings.spec.ts social-operations.spec.ts
```

Expected: all three specs PASS at their declared desktop/tablet/mobile viewports with no external provider request.

- [ ] **Step 9: Commit the acceptance slice**

```bash
git add frontend/src/styles frontend/src/api/generated/schema.ts frontend/e2e backend/openapi.json docs/deepseek-product-ai-provider.md .env.example
git commit -m "test: verify reorganized agent workbench"
```

## Plan Self-Review Results

- Spec coverage: navigation, bright palette, dashboard, Agent truthfulness, encrypted model configuration, five-channel social operations, concise effectiveness, error states, responsive behavior, permissions, and full verification are each covered by a dedicated task.
- Scope boundary: live email is explicitly excluded; social provider app review and real credentials are not activated by tests.
- Secret boundary: `api_key` appears only as a write-only request field; no response, query key, log, audit object, DOM assertion, or generated response type contains it.
- Budget boundary: the new estimated USD limit supplements rather than replaces the existing organization token/concurrency reservation, and both are settled on success or failure.
- Type consistency: backend exposes `execution_mode`, `planner_provider`, and `planner_model`; frontend Agent types consume the same names. Provider configuration uses `daily_budget_micros`, `daily_spent_micros`, and `daily_reserved_micros` consistently.
- Compatibility: `/promotion`, `/agent-approvals`, `/analytics`, and `/admin/analytics` retain routable compatibility while their presentation responsibilities are clarified.
