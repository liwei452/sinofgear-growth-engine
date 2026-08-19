import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import type { GrowthMission } from "./api"
import GrowthMissionDetailPage from "./GrowthMissionDetailPage.vue"

const mission: GrowthMission = {
  id: "mission-1",
  title: "South Africa mining pilot",
  objective: "Obtain qualified replies and RFQs",
  target_countries: ["ZA"],
  target_industries: ["mining equipment"],
  customer_profile: "",
  primary_product_id: "product-1",
  start_date: "2026-08-20",
  end_date: "2026-09-20",
  target_account_count: 100,
  target_reply_count: 20,
  target_rfq_count: 5,
  budget_micros: 100000000,
  allowed_channels: ["EMAIL", "LINKEDIN"],
  attribution_code: "gm-test",
  status: "PENDING_APPROVAL",
  health_status: "ACTION_REQUIRED",
  health_reason: "",
  created_by: 1,
  created_at: "2026-08-18T08:00:00Z",
  latest_plan: {
    id: "plan-1",
    version: 1,
    status: "DRAFT",
    snapshot: {},
    generation_mode: "AUTOMATION",
    provider: "",
    model: "",
    approved_by: null,
    approved_at: null,
    created_at: "2026-08-18T08:01:00Z",
  },
  lane_counts: { ACQUISITION: 0, OUTREACH: 0, SOCIAL: 0, ATTRIBUTION: 0 },
  available_actions: ["generate_plan", "approve_plan"],
}

function renderDetail(permissions: string[]) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    let body: unknown = []
    if (path.includes("/timeline")) body = []
    else if (path.includes("/candidates")) body = []
    else if (path.includes("/content-summary")) body = { platform_contents: [], channel_packages: [] }
    else if (path.includes("/platforms")) body = { results: [] }
    else body = mission
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
  }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/missions/:missionId", component: GrowthMissionDetailPage }],
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

it("shows the two lanes and plan approval actions", async () => {
  const { router, queryClient } = renderDetail(["missions.read", "missions.manage", "missions.review"])
  await router.push("/missions/mission-1")
  render(GrowthMissionDetailPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()

  expect(await screen.findByRole("heading", { name: "客户开发" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "社媒增长" })).toBeVisible()
  expect(screen.getByRole("button", { name: "生成执行计划" })).toBeVisible()
  expect(screen.getByRole("button", { name: "批准并启动" })).toBeVisible()
})

it("hides operational controls from read-only users", async () => {
  const { router, queryClient } = renderDetail(["missions.read"])
  await router.push("/missions/mission-1")
  render(GrowthMissionDetailPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()

  await screen.findByRole("heading", { name: "客户开发" })
  expect(screen.queryByRole("button", { name: "创建增长任务" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "生成执行计划" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "批准并启动" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "暂停" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "终止" })).not.toBeInTheDocument()
})
