import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import type { GrowthMission } from "./api"
import GrowthMissionsPage from "./GrowthMissionsPage.vue"

const mission: GrowthMission = {
  id: "mission-1",
  title: "South Africa mining pilot",
  objective: "Obtain qualified replies and RFQs",
  target_countries: ["ZA"],
  target_industries: ["mining equipment"],
  customer_profile: "OEM and maintenance",
  primary_product_id: "product-1",
  start_date: "2026-08-20",
  end_date: "2026-09-20",
  target_account_count: 100,
  target_reply_count: 20,
  target_rfq_count: 5,
  budget_micros: 100000000,
  allowed_channels: ["EMAIL", "LINKEDIN"],
  attribution_code: "gm-test",
  status: "DRAFT",
  health_status: "DATA_INSUFFICIENT",
  health_reason: "",
  created_by: 1,
  created_at: "2026-08-18T08:00:00Z",
  latest_plan: null,
  lane_counts: { ACQUISITION: 0, OUTREACH: 0, SOCIAL: 0, ATTRIBUTION: 0 },
  available_actions: ["edit", "generate_plan"],
}

function renderMissions(permissions: string[]) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify([mission]), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }))))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/missions", component: GrowthMissionsPage },
      { path: "/missions/:missionId", component: { template: "<p>详情</p>" } },
    ],
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "op" },
    organization: { id: "o1", name: "Org", slug: "org" },
    membership: { id: "m", role: "OPERATOR", status: "ACTIVE", permissions },
  })
  return { router, queryClient }
}

afterEach(() => vi.unstubAllGlobals())

it("lists growth missions with the two lanes", async () => {
  const { router, queryClient } = renderMissions(["missions.read", "missions.manage"])
  await router.push("/missions")
  render(GrowthMissionsPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()

  expect(await screen.findByRole("heading", { name: "增长任务" })).toBeVisible()
  expect(await screen.findByText("South Africa mining pilot")).toBeVisible()
  expect(screen.getAllByText(/客户开发/).length).toBeGreaterThan(0)
  expect(screen.getAllByText(/社媒增长/).length).toBeGreaterThan(0)
  expect(screen.queryByText("Agent 工作台")).not.toBeInTheDocument()
})

it("hides creation from read-only users", async () => {
  const { router, queryClient } = renderMissions(["missions.read"])
  await router.push("/missions")
  render(GrowthMissionsPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()

  await screen.findByRole("heading", { name: "增长任务" })
  expect(screen.queryByRole("button", { name: "创建增长任务" })).not.toBeInTheDocument()
})
