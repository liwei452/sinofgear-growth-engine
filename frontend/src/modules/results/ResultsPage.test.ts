import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import ResultsPage from "./ResultsPage.vue"

afterEach(() => vi.unstubAllGlobals())

it("shows the outcome funnel with unknown values instead of invented zeros", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
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
      : [{ id: "mission-1", title: "South Africa mining pilot" }]
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
  }))
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
})
