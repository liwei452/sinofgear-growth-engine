import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import DashboardPage from "./DashboardPage.vue"

afterEach(() => vi.unstubAllGlobals())

async function renderDashboard() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: DashboardPage },
      { path: "/products", component: { template: "<p>产品页</p>" } },
      { path: "/promotion", component: { template: "<p>推广页</p>" } },
      { path: "/opportunities", component: { template: "<p>机会页</p>" } },
      { path: "/content-factory", component: { template: "<p>内容工厂</p>" } },
      { path: "/reviews", component: { template: "<p>审核页</p>" } },
      { path: "/company", component: { template: "<p>公司资料页</p>" } },
      { path: "/analytics", component: { template: "<p>效果页</p>" } },
      { path: "/agent-workspace", component: { template: "<p>Agent 工作台</p>" } },
      { path: "/platform-accounts", component: { template: "<p>平台账户页</p>" } },
      { path: "/settings", component: { template: "<p>设置页</p>" } },
    ],
  })
  await router.push("/")
  await router.isReady()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(DashboardPage, {
    global: { plugins: [router, [VueQueryPlugin, { queryClient }]] },
  })
}

it("shows real next steps without fabricated dashboard content in an empty workspace", async () => {
  const { container } = await renderDashboard()

  expect(screen.getByRole("heading", { level: 1, name: /今天先处理最重要的增长任务/ })).toBeInTheDocument()
  const priorities = screen.getByRole("region", { name: "今日优先事项" })
  expect(within(priorities).getByRole("link", { name: /发现潜在客户/ })).toHaveAttribute("href", "/opportunities")
  expect(within(priorities).getByRole("link", { name: /创建第一批专业内容/ })).toHaveAttribute("href", "/content-factory")
  expect(within(priorities).getByRole("link", { name: /补充公司事实/ })).toHaveAttribute("href", "/company")
  expect(screen.queryByText(/SinofGear 团队/)).not.toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "今天发现的采购机会" })).toBeInTheDocument()
  expect(screen.getByText("今天还没有已验证的采购机会")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "选择市场或导入合法名单" })).toHaveAttribute("href", "/opportunities")
  expect(screen.getByText("还没有近七天业务记录")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "查看经营效果" })).toHaveAttribute("href", "/analytics")
  expect(screen.queryByText(/PackTech|ISO 9001|72 \/ 100|6,820/)).not.toBeInTheDocument()
  expect(container.querySelector(".sparkline")).not.toBeInTheDocument()
})

it("organizes today around four honest KPIs and a compact status rail", async () => {
  await renderDashboard()

  const coreStatus = screen.getByRole("region", { name: "今日核心状态" })
  for (const label of ["新机会", "等待审批", "待发布", "有效询盘"]) {
    expect(within(coreStatus).getByText(label)).toBeVisible()
  }
  expect(within(coreStatus).getAllByText("无数据")).toHaveLength(4)

  const rail = screen.getByRole("complementary", { name: "工作台状态" })
  expect(within(rail).getByRole("heading", { name: "Agent 与模型" })).toBeVisible()
  expect(within(rail).getByRole("link", { name: "检查模型设置" })).toHaveAttribute(
    "href",
    "/settings",
  )
})

it("does not render Demo API records in the formal dashboard", async () => {
  const workspace = {
    target_accounts: [{ id: "demo-account", name: "Demo Buyer Ltd", country: "Germany", industry: "Machinery", employee_range: "11-50", website: "", is_demo: true, data_label: "Demo / Fake" }],
    intent_signals: [{ id: "demo-signal", account_id: "demo-account", signal_type: "HIRING", source_label: "Demo", source_url: "", evidence_text: "Demo purchase signal", confidence: 99, observed_at: "2026-08-15T08:00:00Z", data_label: "Demo / Fake" }],
    contacts: [], inbound_leads: [], follow_ups: [], outreach_drafts: [], channel_packages: [],
    metric_receipts: [{ id: "demo-metric", channel: "TIKTOK", payload: { views: 99999 }, is_demo: true }],
    field_provenance: [], connectors: [],
  }
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    const payload = path === "/api/v1/growth/workspace" ? workspace
      : path === "/api/v1/growth/agent/runs" ? []
        : { mode: "FAKE_OFFLINE", provider_label: "Fake / 离线演示", model: "fake-v1", configured: false, real_requests_enabled: false }
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } })
  }))
  await renderDashboard()
  expect(await screen.findByText("今天还没有已验证的采购机会")).toBeInTheDocument()
  expect(screen.queryByText(/Demo Buyer|Demo purchase signal|99,999/)).not.toBeInTheDocument()
})

it("loads opportunities and persists follow-up and draft actions through the growth API", async () => {
  document.cookie = "csrftoken=dashboard-test-token"
  const workspace = {
    target_accounts: [{
      id: "10000000-0000-4000-8000-000000001001", name: "API PackTech GmbH",
      country: "Germany", industry: "Packaging machinery", employee_range: "51-200",
      website: "", is_demo: false, data_label: "Licensed / permitted source",
    }],
    contacts: [], inbound_leads: [], follow_ups: [], outreach_drafts: [],
    channel_packages: [], metric_receipts: [], field_provenance: [], connectors: [],
    intent_signals: [{
      id: "10000000-0000-4000-8000-000000001101",
      account_id: "10000000-0000-4000-8000-000000001001", signal_type: "HIRING",
      source_label: "Public careers page", source_url: "https://example.invalid/careers",
      evidence_text: "Hiring a precision transmission buyer", confidence: 88,
      observed_at: "2026-08-14T08:00:00Z", data_label: "Licensed / permitted source",
    }],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/growth/agent/runs") {
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/ai/provider-status") {
      return new Response(JSON.stringify({
        mode: "FAKE_OFFLINE", provider_label: "Fake / 离线演示", model: "fake-v1",
        configured: false, real_requests_enabled: false,
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/follow-up")) {
      return new Response(JSON.stringify({ id: "follow-1", status: "OPEN" }), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/draft")) {
      return new Response(JSON.stringify({
        id: "draft-1", status: "DRAFT", "English draft": "Hello from persisted API draft.",
        "Chinese explanation": "仅生成草稿，不会自动发送。", delivery: "NEVER_SENT",
      }), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path} ${init?.method ?? "GET"}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()

  await renderDashboard()
  const opportunity = await screen.findByRole("article", { name: "API PackTech GmbH 采购机会" })
  await user.click(within(opportunity).getByRole("button", { name: "加入跟进" }))
  await waitFor(() => expect(within(opportunity).getByRole("button", { name: "已加入跟进" })).toBeDisabled())
  await user.click(within(opportunity).getByRole("button", { name: "生成联系草稿" }))

  expect(await screen.findByText("Hello from persisted API draft.")).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/growth/workspace", expect.any(Object))
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/follow-up"))).toBe(true)
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/draft"))).toBe(true)
})
