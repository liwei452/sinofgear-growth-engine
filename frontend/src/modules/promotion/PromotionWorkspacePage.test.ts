import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import { companyFactsQueryOptions } from "../growth/api"
import type { GrowthMission } from "../missions/api"
import PromotionWorkspacePage from "./PromotionWorkspacePage.vue"

const mission = (id: string, overrides: Partial<GrowthMission> = {}): GrowthMission => ({
  id, title: id, objective: "获得有效询盘", target_countries: ["ZA"], target_industries: ["mining"],
  customer_profile: "OEM", primary_product_id: `product-${id}`, start_date: "2026-08-20",
  end_date: "2026-09-20", target_account_count: 10, target_reply_count: 2, target_rfq_count: 1,
  budget_micros: 0, allowed_channels: [], attribution_code: "test", status: "DRAFT",
  health_status: "DATA_INSUFFICIENT", health_reason: "", created_by: 1,
  created_at: "2026-08-20T00:00:00Z", latest_plan: null,
  lane_counts: { ACQUISITION: 0, OUTREACH: 0, SOCIAL: 0, ATTRIBUTION: 0 }, available_actions: [],
  ...overrides,
})

function renderWorkspace(input: {
  missions?: GrowthMission[]
  permissions?: string[]
  role?: string
  route?: string
  companyStatus?: number
  companyFacts?: unknown[]
  assets?: unknown[]
  seedCompanyFacts?: boolean
}) {
  const missions = input.missions ?? [mission("mission-1")]
  vi.stubGlobal("fetch", vi.fn((request: RequestInfo | URL) => {
    const path = String(request)
    const status = path.includes("company-facts") ? (input.companyStatus ?? 200) : 200
    let body: unknown = []
    if (path.includes("company-facts")) body = input.companyFacts ?? [{ id: "fact-1", verification_status: "VERIFIED" }]
    if (path.includes("growth/missions")) body = missions
    if (path.includes("/products")) body = { next: null, previous: null, results: missions.map(item => ({ id: item.primary_product_id, status: "ACTIVE" })) }
    if (path.includes("/assets")) body = { next: null, previous: null, results: input.assets ?? [] }
    if (path.includes("social-accounts")) body = { results: [] }
    return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }))
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (input.seedCompanyFacts) {
    queryClient.setQueryData(companyFactsQueryOptions().queryKey, [{ id: "old", verification_status: "VERIFIED" }], { updatedAt: 0 })
  }
  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "operator" }, organization: { id: "o1", name: "Org", slug: "org" },
    membership: {
      id: "m1", role: input.role ?? "ADMINISTRATOR", status: "ACTIVE",
      permissions: input.permissions ?? ["missions.read", "products.read", "assets.read", "publishing.read"],
    },
  })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/promotion", component: PromotionWorkspacePage },
    { path: "/company", component: { template: "<p>公司</p>" } },
    { path: "/missions", component: { template: "<p>任务</p>" } },
    { path: "/missions/:missionId", component: { template: "<p>任务详情</p>" } },
    { path: "/products", component: { template: "<p>产品</p>" } },
    { path: "/assets", component: { template: "<p>素材</p>" } },
    { path: "/platform-accounts", component: { template: "<p>渠道</p>" } },
  ] })
  return router.push(input.route ?? "/promotion").then(async () => {
    render(PromotionWorkspacePage, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })
    await router.isReady()
  })
}

afterEach(() => vi.unstubAllGlobals())

it.each([403, 500])("does not derive a journey from a failed company read (%i), even when stale facts remain cached", async (companyStatus) => {
  await renderWorkspace({ companyStatus, seedCompanyFacts: true })

  expect(await screen.findByRole("alert")).toHaveTextContent(
    companyStatus === 403 ? "无权读取推广记录" : "推广状态暂时无法读取",
  )
  expect(screen.queryByRole("list")).not.toBeInTheDocument()
  expect(screen.queryByRole("link", { name: /继续/ })).not.toBeInTheDocument()
})

it("keeps the journey unavailable when a required source is not authorized", async () => {
  await renderWorkspace({ permissions: ["missions.read"] })

  expect(await screen.findByRole("alert")).toHaveTextContent("缺少推广所需查看权限")
  expect(screen.queryByRole("list")).not.toBeInTheDocument()
})

it("requires a visible selection for multiple missions and uses the selected mission in the detail link", async () => {
  const missions = [mission("mission-1", { title: "任务一" }), mission("mission-2", {
    title: "任务二", lane_counts: { ACQUISITION: 1, OUTREACH: 0, SOCIAL: 0, ATTRIBUTION: 0 },
  })]
  await renderWorkspace({ missions })
  expect(await screen.findByText("请选择要推进的增长任务")).toBeInTheDocument()

  await renderWorkspace({ missions, route: "/promotion?mission=mission-2" })
  expect(await screen.findByText("当前任务：任务二")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "继续 内容准备" })).toHaveAttribute("href", "/assets")
})

it("accepts content only from a ready asset linked to the selected mission product", async () => {
  const configuredMission = mission("mission-1", { lane_counts: { ACQUISITION: 1, OUTREACH: 0, SOCIAL: 0, ATTRIBUTION: 0 } })
  await renderWorkspace({ missions: [configuredMission], assets: [{ id: "other", status: "READY", products: [{ id: "other-product" }] }] })
  expect(await screen.findByRole("link", { name: "继续 内容准备" })).toBeInTheDocument()

  await renderWorkspace({ missions: [configuredMission], assets: [{ id: "linked", status: "READY", products: [{ id: "product-mission-1" }] }] })
  expect(await screen.findByRole("link", { name: "继续 推广渠道" })).toBeInTheDocument()
})

it("offers a continuation only when its destination is reachable by the current role", async () => {
  await renderWorkspace({ role: "OPERATOR", companyFacts: [] })
  expect(await screen.findByText(/需要管理员权限/)).toBeInTheDocument()
  expect(screen.queryByRole("link", { name: /继续 公司资料/ })).not.toBeInTheDocument()

  await renderWorkspace({ role: "ADMINISTRATOR", companyFacts: [] })
  expect(await screen.findByRole("link", { name: "继续 公司资料" })).toHaveAttribute("href", "/company")
})
