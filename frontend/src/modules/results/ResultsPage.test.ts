import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import ResultsPage from "./ResultsPage.vue"

afterEach(() => vi.unstubAllGlobals())

it("requests the selected mission and labels the funnel as cumulative saved results", async () => {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    const body = path.includes("/attribution")
      ? {
        outcomes: {
          emails_sent: null,
          confirmed_replies: null,
          confirmed_rfqs: null,
          cost_per_result: null,
        },
        diagnostics: { impressions: null },
        availability: { email: "NOT_CONNECTED" },
        traces: [],
      }
      : [{ id: "mission-1", title: "South Africa mining pilot" }, { id: "mission-2", title: "Brazil steel pilot" }]
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
  })
  vi.stubGlobal("fetch", fetchMock)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/analytics", component: ResultsPage },
      { path: "/attribution", component: { template: "<div />" } },
    ],
  })
  await router.push("/analytics")
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(ResultsPage, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })
  await router.isReady()

  for (const step of ["发现公司", "人工确认", "找到联系路径", "创建跟进", "获得回复", "形成询盘", "成交"]) {
    expect(await screen.findByText(step)).toBeInTheDocument()
  }
  expect(screen.getAllByText("尚未记录").length).toBeGreaterThan(0)
  expect(screen.queryByText(/^0$/)).not.toBeInTheDocument()
  expect(screen.getByText("当前任务累计（全部已保存记录）")).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes("mission=mission-1"))).toBe(true)
  await userEvent.setup().selectOptions(screen.getByLabelText("增长任务"), "mission-2")
  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).includes("mission=mission-2"))).toBe(true))
})

it("explains an attribution failure and lets the user retry", async () => {
  let attempts = 0
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    if (!path.includes("/attribution")) return Promise.resolve(new Response(JSON.stringify([{ id: "mission-1", title: "South Africa mining pilot" }]), { status: 200, headers: { "Content-Type": "application/json" } }))
    attempts += 1
    if (attempts === 1) return Promise.resolve(new Response(JSON.stringify({ detail: "Forbidden" }), { status: 403, headers: { "Content-Type": "application/json" } }))
    return Promise.resolve(new Response(JSON.stringify({ outcomes: { emails_sent: 0, confirmed_replies: 0, confirmed_rfqs: 0, won_revenue: { amount: "0" }, cost_per_result: null }, diagnostics: { impressions: null }, availability: { email: "NOT_CONNECTED" }, traces: [] }), { status: 200, headers: { "Content-Type": "application/json" } }))
  }))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/analytics", component: ResultsPage }, { path: "/attribution", component: { template: "<div />" } }] })
  await router.push("/analytics")
  render(ResultsPage, { global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }], router] } })
  await router.isReady()

  expect(await screen.findByRole("alert")).toHaveTextContent("效果数据暂时无法读取")
  const retry = screen.getByRole("button", { name: "重新读取效果" })
  expect(retry).toBeEnabled()
  await userEvent.setup().click(retry)
  expect(await screen.findByText("从机会到成交")).toBeInTheDocument()
})
