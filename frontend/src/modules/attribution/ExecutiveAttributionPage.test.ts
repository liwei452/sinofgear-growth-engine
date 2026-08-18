import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import type { GrowthMission } from "../missions/api"
import ExecutiveAttributionPage from "./ExecutiveAttributionPage.vue"

const mission: GrowthMission = {
  id: "mission-1",
  title: "South Africa mining pilot",
  objective: "Get replies",
  target_countries: ["ZA"],
  target_industries: ["mining"],
  customer_profile: "",
  primary_product_id: "product-1",
  start_date: "2026-08-20",
  end_date: "2026-09-20",
  target_account_count: 100,
  target_reply_count: 20,
  target_rfq_count: 5,
  budget_micros: 100,
  allowed_channels: ["EMAIL"],
  attribution_code: "gm-test",
  status: "RUNNING",
  health_status: "NORMAL",
  health_reason: "",
  created_by: 1,
  created_at: "2026-08-18T08:00:00Z",
  latest_plan: null,
  lane_counts: { ACQUISITION: 0, OUTREACH: 0, SOCIAL: 0, ATTRIBUTION: 0 },
  available_actions: [],
}

const attribution = {
  outcomes: {
    emails_sent: null,
    confirmed_replies: 2,
    confirmed_rfqs: 1,
    won_revenue: { amount: "12500.00" },
    cost_per_result: null,
  },
  diagnostics: { impressions: 900 },
  availability: { email: "NOT_CONNECTED" },
  traces: [{ confidence: "CONFIRMED", type: "rfq", source_id: "rfq-1" }],
}

afterEach(() => vi.unstubAllGlobals())

it("leads with confirmed outcomes and keeps impressions under diagnostics", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    const body = path.includes("/attribution") ? attribution : [mission]
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
  }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/attribution", component: ExecutiveAttributionPage }],
  })
  await router.push("/attribution")
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(ExecutiveAttributionPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()

  expect(await screen.findByText("有效回复")).toBeVisible()
  expect(screen.getByText("RFQ")).toBeVisible()
  expect(screen.getByText("收入")).toBeVisible()
  expect(screen.getByText("12500.00")).toBeVisible()
  expect(screen.getByText("辅助诊断")).toBeVisible()
  expect(screen.getByText("900")).toBeVisible()
  expect(screen.queryByRole("button", { name: "录入指标" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "API 设置" })).not.toBeInTheDocument()
})
