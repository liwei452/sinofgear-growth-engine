import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import AgentCenterPage from "./AgentCenterPage.vue"

const user = {
  user: { id: 1, username: "administrator" },
  organization: { id: "org-1", name: "SinofGear", slug: "sinofgear" },
  membership: {
    id: "membership-1", role: "ADMINISTRATOR", status: "ACTIVE",
    permissions: [
      "director.read", "content.read", "content.manage", "campaigns.read", "campaigns.manage",
      "sources.read", "sources.manage", "leads.read", "leads.analyze", "tracking.read", "credentials.manage",
    ],
  },
}

function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } })
}

async function renderPage(options: {
  connected?: boolean
  analyticsCount?: number
  permissions?: string[]
  fail?: "provider" | "director" | "analytics"
} = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    ...user, membership: { ...user.membership, permissions: options.permissions ?? user.membership.permissions },
  })
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url
    if (path === "/api/v1/ai-provider-configuration") return options.fail === "provider" ? response({}, 503) : response({
      provider_code: "deepseek", connection_state: options.connected === false ? "NOT_CONFIGURED" : "CONNECTED",
      key_suffix: "1234", credential_revision: 1, last_tested_at: "2026-08-12T08:00:00Z", last_tested_by_id: 1,
      daily_budget_usd: "5.00", flash_max_output_tokens: 4096, pro_max_output_tokens: 8192,
      timeout_seconds: 60, updated_at: "2026-08-12T08:00:00Z",
    })
    if (path === "/api/v1/director/cockpit") return options.fail === "director" ? response({}, 503) : response({ decisions: [], active_work: [], recent_outcomes: [], generated_at: "2026-08-12T08:00:00Z" })
    if (path.startsWith("/api/v1/analytics/channel-summary")) return options.fail === "analytics" ? response({}, 503) : response({
      count: options.analyticsCount ?? 1, total_clicks: 5, next: null, previous: null,
      results: options.analyticsCount === 0 ? [] : [{ date: "2026-08-12", campaign_id: "c", platform_id: "p", country: "DE", product_id: "g", clicks: 5 }],
    })
    return response({}, 404)
  }))
  const view = render(AgentCenterPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient }]], stubs: { RouterLink: { template: "<a :href='to'><slot /></a>", props: ["to"] } } },
  })
  return { ...view, queryClient }
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it("shows exactly the five approved agents and no fake scheduler controls", async () => {
  await renderPage()
  expect(await screen.findByRole("heading", { level: 1, name: "AI Agent 中心" })).toBeInTheDocument()
  const cards = await screen.findAllByRole("article")
  expect(cards.map((card) => within(card).getByRole("heading", { level: 2 }).textContent)).toEqual([
    "Growth Director", "Content Agent", "Lead Agent", "AIEO Agent", "Analytics Agent",
  ])
  expect(screen.queryByRole("switch")).not.toBeInTheDocument()
  expect(screen.queryByText(/运行中|自动调度已开启/)).not.toBeInTheDocument()
})

it("derives readiness from real connection, permissions and records", async () => {
  await renderPage()
  const cards = await screen.findAllByRole("article")
  await within(cards[0]).findByText("可用")
  expect(within(cards[0]).getByText("可用")).toBeInTheDocument()
  expect(within(cards[1]).getByText("可用")).toBeInTheDocument()
  expect(within(cards[2]).getByText("可用")).toBeInTheDocument()
  expect(within(cards[3]).getByText("后续批次接入")).toBeInTheDocument()
  expect(within(cards[3]).getByText("设计已确认，后续批次接入")).toBeInTheDocument()
  expect(within(cards[4]).getByText("可用")).toBeInTheDocument()
})

it("does not claim AI agents or analytics are ready when configuration is absent", async () => {
  await renderPage({ connected: false, analyticsCount: 0 })
  const cards = await screen.findAllByRole("article")
  expect(await within(cards[1]).findByText("需要配置")).toBeInTheDocument()
  expect(within(cards[2]).getByText("需要配置")).toBeInTheDocument()
  expect(within(cards[4]).getByText("需要配置")).toBeInTheDocument()
  expect(within(cards[4]).getByText(/还没有可确认的效果记录/)).toBeInTheDocument()
})

it("does not call protected capability endpoints without permission", async () => {
  await renderPage({ permissions: ["director.read"] })
  await screen.findAllByRole("article")
  const paths = vi.mocked(fetch).mock.calls.map(([input]) => String(input))
  expect(paths).toContain("/api/v1/director/cockpit")
  expect(paths).not.toContain("/api/v1/ai-provider-configuration")
  expect(paths.some((path) => path.startsWith("/api/v1/analytics/channel-summary"))).toBe(false)
  const cards = screen.getAllByRole("article")
  expect(within(cards[1]).getByText("无权核对")).toBeInTheDocument()
  expect(within(cards[1]).getByText(/请联系管理员确认 DeepSeek/)).toBeInTheDocument()
  expect(within(cards[1]).queryByText(/需要连接 DeepSeek/)).not.toBeInTheDocument()
})

it("requires the exact executable permissions before content or lead agents are usable", async () => {
  await renderPage({
    permissions: [
      "director.read", "content.read", "campaigns.read", "sources.read", "sources.manage",
      "leads.read", "tracking.read", "credentials.manage",
    ],
  })
  const cards = await screen.findAllByRole("article")
  expect(await within(cards[1]).findByText("需要配置")).toBeInTheDocument()
  expect(within(cards[1]).getByText(/content.manage.*campaigns.manage/)).toBeInTheDocument()
  expect(within(cards[2]).getByText("需要配置")).toBeInTheDocument()
  expect(within(cards[2]).getByText(/leads.analyze/)).toBeInTheDocument()
})

it("gates and clears same-organization Director and analytics evidence after permission revocation", async () => {
  const { queryClient } = await renderPage()
  const cards = await screen.findAllByRole("article")
  expect(await within(cards[0]).findByText("驾驶舱接口已可读取。")).toBeInTheDocument()
  expect(within(cards[4]).getByText("已找到可用于分析的真实效果记录。")).toBeInTheDocument()

  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    ...user, membership: { ...user.membership, permissions: ["credentials.manage"] },
  })

  await waitFor(() => expect(within(cards[0]).getByText("无权核对")).toBeInTheDocument())
  expect(within(cards[0]).queryByText("驾驶舱接口已可读取。")).not.toBeInTheDocument()
  expect(within(cards[4]).getByText("无权核对")).toBeInTheDocument()
  expect(within(cards[4]).queryByText(/真实效果记录/)).not.toBeInTheDocument()
  await waitFor(() => expect(queryClient.getQueryData(["director", "org-1", "cockpit"])).toBeUndefined())
  expect(queryClient.getQueryData(["analytics", "org-1", "summary", {}])).toBeUndefined()
})

it.each([
  ["provider", 1], ["director", 0], ["analytics", 4],
] as const)("reports a transient %s failure as temporarily unverifiable", async (failure, cardIndex) => {
  await renderPage({ fail: failure })
  const cards = await screen.findAllByRole("article")
  expect(await within(cards[cardIndex]).findByText("暂时无法核对")).toBeInTheDocument()
  expect(within(cards[cardIndex]).queryByText("需要配置")).not.toBeInTheDocument()
})
