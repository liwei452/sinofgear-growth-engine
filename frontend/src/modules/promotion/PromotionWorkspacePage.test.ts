import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import PromotionWorkspacePage from "./PromotionWorkspacePage.vue"

afterEach(() => vi.unstubAllGlobals())

it("shows the persisted promotion journey and a route for the current step", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    let body: unknown = []
    if (path.includes("company-facts")) body = [{ id: "fact-1", verification_status: "VERIFIED" }]
    if (path.includes("social-accounts")) body = { results: [] }
    if (path.includes("growth/missions")) body = [{
      id: "mission-1", title: "矿业试点", objective: "获得有效询盘", target_countries: ["ZA"],
      target_industries: ["mining"], customer_profile: "OEM", primary_product_id: "product-1",
      start_date: "2026-08-20", end_date: "2026-09-20", target_account_count: 10,
      target_reply_count: 2, target_rfq_count: 1, budget_micros: 0, allowed_channels: [],
      attribution_code: "test", status: "DRAFT", health_status: "DATA_INSUFFICIENT", health_reason: "",
      created_by: 1, created_at: "2026-08-20T00:00:00Z", latest_plan: null,
      lane_counts: { ACQUISITION: 0, OUTREACH: 0, SOCIAL: 0, ATTRIBUTION: 0 }, available_actions: [],
    }]
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { "Content-Type": "application/json" },
    }))
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "operator" }, organization: { id: "o1", name: "Org", slug: "org" },
    membership: { id: "m1", role: "OPERATOR", status: "ACTIVE", permissions: ["missions.read", "publishing.read"] },
  })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/promotion", component: PromotionWorkspacePage },
    { path: "/company", component: { template: "<p>公司</p>" } },
    { path: "/missions", component: { template: "<p>任务</p>" } },
    { path: "/assets", component: { template: "<p>素材</p>" } },
    { path: "/platform-accounts", component: { template: "<p>渠道</p>" } },
  ] })
  await router.push("/promotion")
  render(PromotionWorkspacePage, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })
  await router.isReady()

  expect(await screen.findByRole("heading", { name: "开始推广" })).toBeInTheDocument()
  expect(screen.getAllByRole("listitem")).toHaveLength(7)
  expect(screen.getByText("当前步骤")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: /继续/ })).toHaveAttribute("href", expect.stringMatching(/^\//))
})
