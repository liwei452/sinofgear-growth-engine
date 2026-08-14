import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { expect, it, vi } from "vitest"

import DashboardPage from "./DashboardPage.vue"

async function renderDashboard() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: DashboardPage },
      { path: "/products", component: { template: "<p>产品页</p>" } },
      { path: "/promotion", component: { template: "<p>推广页</p>" } },
      { path: "/opportunities", component: { template: "<p>机会页</p>" } },
    ],
  })
  await router.push("/")
  await router.isReady()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(DashboardPage, {
    global: { plugins: [router, [VueQueryPlugin, { queryClient }]] },
  })
}

it("shows clearly labeled demo opportunities with decision-ready evidence", async () => {
  await renderDashboard()

  expect(screen.getByRole("heading", { name: "今天发现的采购机会" })).toBeInTheDocument()
  expect(screen.getAllByText("Demo / Fake").length).toBeGreaterThan(0)
  const opportunity = screen.getByRole("article", { name: "PackTech GmbH 采购机会" })
  expect(opportunity).toHaveTextContent("德国")
  expect(opportunity).toHaveTextContent("包装机械 · 51–200 人")
  expect(opportunity).toHaveTextContent("正在寻找高精度斜齿轮供应商")
  expect(opportunity).toHaveTextContent("公司官网 / 公开招聘页")
  expect(opportunity).toHaveTextContent("2 小时前发现")
  expect(opportunity).toHaveTextContent("高意向")
})

it("supports follow-up, bilingual draft, and evidence review without sending anything", async () => {
  const user = userEvent.setup()
  await renderDashboard()
  const opportunity = screen.getByRole("article", { name: "PackTech GmbH 采购机会" })

  await user.click(within(opportunity).getByRole("button", { name: "加入跟进" }))
  expect(within(opportunity).getByRole("button", { name: "已加入跟进" })).toBeDisabled()

  await user.click(within(opportunity).getByRole("button", { name: "生成联系草稿" }))
  const draft = screen.getByRole("dialog", { name: "联系草稿" })
  expect(draft).toHaveTextContent("English draft")
  expect(draft).toHaveTextContent("中文说明")
  expect(draft).toHaveTextContent("草稿不会自动发送")
  await user.click(within(draft).getByRole("button", { name: "关闭" }))

  await user.click(within(opportunity).getByRole("button", { name: "查看证据" }))
  expect(screen.getByRole("region", { name: "PackTech GmbH 原始证据" })).toHaveTextContent(
    "公开招聘页提到新增精密传动采购岗位",
  )
})

it("explains AI visibility and includes the approved channel set", async () => {
  await renderDashboard()

  const visibility = screen.getByRole("region", { name: "AI 品牌与搜索曝光" })
  expect(visibility).toHaveTextContent("72 / 100")
  expect(visibility).toHaveTextContent("评分依据")
  expect(visibility).toHaveTextContent("可验证品牌事实")
  expect(visibility).toHaveTextContent("缺少 DIN 6 精度证据")
  expect(screen.getByRole("heading", { name: "AI 已知道" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "还不清楚" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "建议补充" })).toBeInTheDocument()

  for (const channel of ["LinkedIn", "Facebook", "Instagram", "TikTok", "YouTube"]) {
    expect(screen.getByRole("article", { name: `${channel} 渠道表现` })).toBeInTheDocument()
  }
})

it("loads opportunities and persists follow-up and draft actions through the growth API", async () => {
  document.cookie = "csrftoken=dashboard-test-token"
  const workspace = {
    target_accounts: [{
      id: "10000000-0000-4000-8000-000000001001", name: "API PackTech GmbH",
      country: "Germany", industry: "Packaging machinery", employee_range: "51-200",
      website: "", is_demo: true, data_label: "Demo / Fake",
    }],
    contacts: [], inbound_leads: [], follow_ups: [], outreach_drafts: [],
    channel_packages: [], metric_receipts: [], field_provenance: [], connectors: [],
    intent_signals: [{
      id: "10000000-0000-4000-8000-000000001101",
      account_id: "10000000-0000-4000-8000-000000001001", signal_type: "HIRING",
      source_label: "Public careers page", source_url: "https://example.invalid/careers",
      evidence_text: "Hiring a precision transmission buyer", confidence: 88,
      observed_at: "2026-08-14T08:00:00Z", data_label: "Demo / Fake",
    }],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
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
