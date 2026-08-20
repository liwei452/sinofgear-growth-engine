import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import ResultsPage from "./ResultsPage.vue"

afterEach(() => vi.unstubAllGlobals())

async function renderResults(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/analytics", component: ResultsPage },
      { path: "/attribution", component: { template: "<div />" } },
    ],
  })
  await router.push("/analytics")
  render(ResultsPage, {
    global: {
      plugins: [[VueQueryPlugin, {
        queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
      }], router],
    },
  })
  await router.isReady()
}

it("renders only verifiable mission outcomes and does not invent unsupported funnel stages", async () => {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    const body = path.includes("/attribution")
      ? {
        outcomes: {
          emails_sent: 12,
          confirmed_replies: 3,
          confirmed_rfqs: 2,
          won_revenue: { amount: "12500.00" },
          cost_per_result: null,
        },
        diagnostics: { impressions: 900 },
        availability: { email: "CONNECTED" },
        traces: [
          { confidence: "CONFIRMED", type: "email_reply", source_id: "reply-1" },
          { confidence: "CONFIRMED", type: "rfq", source_id: "rfq-1" },
        ],
      }
      : [
        { id: "mission-1", title: "South Africa mining pilot" },
        { id: "mission-2", title: "Brazil steel pilot" },
      ]
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
  })
  await renderResults(fetchMock)

  expect(within(await screen.findByRole("listitem", { name: "已发送或已提交" })).getByText("12")).toBeVisible()
  expect(within(screen.getByRole("listitem", { name: "有效回复" })).getByText("3")).toBeVisible()
  expect(within(screen.getByRole("listitem", { name: "RFQ" })).getByText("2")).toBeVisible()
  expect(within(screen.getByRole("listitem", { name: "成交金额" })).getByText("12,500.00")).toBeVisible()
  expect(screen.getByText(/当前任务：South Africa mining pilot/)).toBeVisible()
  expect(screen.getByText("2 条已确认归因证据")).toBeVisible()
  for (const unsupported of ["发现公司", "人工确认", "找到联系路径", "创建跟进", "漏斗数据表"]) {
    expect(screen.queryByText(unsupported)).not.toBeInTheDocument()
  }
  expect(screen.queryByText("尚未记录")).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes("mission=mission-1"))).toBe(true)

  await userEvent.setup().selectOptions(screen.getByLabelText("增长任务"), "mission-2")
  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).includes("mission=mission-2"))).toBe(true))
})

it("hides unavailable send metrics and explains the data scope", async () => {
  await renderResults(vi.fn((input: RequestInfo | URL) => {
    const body = String(input).includes("/attribution")
      ? {
        outcomes: {
          emails_sent: null,
          confirmed_replies: 0,
          confirmed_rfqs: 0,
          won_revenue: { amount: "0.00" },
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

  expect(await screen.findByText("邮件渠道未接通，已发送或已提交数量未纳入本页。")).toBeVisible()
  expect(screen.queryByRole("listitem", { name: "已发送或已提交" })).not.toBeInTheDocument()
  expect(within(screen.getByRole("listitem", { name: "有效回复" })).getByText("0")).toBeVisible()
})

it("explains an attribution failure and lets the user retry", async () => {
  let attempts = 0
  await renderResults(vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    if (!path.includes("/attribution")) {
      return Promise.resolve(new Response(JSON.stringify([
        { id: "mission-1", title: "South Africa mining pilot" },
      ]), { status: 200, headers: { "Content-Type": "application/json" } }))
    }
    attempts += 1
    if (attempts === 1) {
      return Promise.resolve(new Response(JSON.stringify({ detail: "Forbidden" }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      }))
    }
    return Promise.resolve(new Response(JSON.stringify({
      outcomes: {
        emails_sent: 0,
        confirmed_replies: 0,
        confirmed_rfqs: 0,
        won_revenue: { amount: "0" },
        cost_per_result: null,
      },
      diagnostics: { impressions: null },
      availability: { email: "CONNECTED" },
      traces: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } }))
  }))

  expect(await screen.findByRole("alert")).toHaveTextContent("效果数据暂时无法读取")
  const retry = screen.getByRole("button", { name: "重新读取效果" })
  expect(retry).toBeEnabled()
  await userEvent.setup().click(retry)
  expect(await screen.findByRole("heading", { name: "已确认成果" })).toBeVisible()
})
