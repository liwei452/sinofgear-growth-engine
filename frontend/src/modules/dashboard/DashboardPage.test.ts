import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, within } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import DashboardPage from "./DashboardPage.vue"

const workItems = [
  {
    id: "high-item", mission_id: "mission-1", mission_title: "Pilot", kind: "REVIEW",
    title: "高优先级机会", summary: "需要尽快处理", priority: "HIGH", source_type: "agent_run",
    source_id: "run-1", source_ids: ["run-1"], action_type: "APPROVE_AGENT_RUN",
    action_label: "批准", preview: {}, created_at: "2026-08-18T08:00:00Z",
  },
  {
    id: "urgent-item", mission_id: "mission-1", mission_title: "Pilot", kind: "REVIEW",
    title: "紧急机会", summary: "需要立即处理", priority: "URGENT", source_type: "agent_run",
    source_id: "run-2", source_ids: ["run-2"], action_type: "APPROVE_AGENT_RUN",
    action_label: "立即批准", preview: {}, created_at: "2026-08-18T08:01:00Z",
  },
  {
    id: "blocker-item", mission_id: null, mission_title: "未归属", kind: "CONFIGURATION_BLOCK",
    title: "邮箱连接失效", summary: "渠道尚未接通", priority: "NORMAL", source_type: "agent_run",
    source_id: "run-3", source_ids: ["run-3"], action_type: "OPEN_SETTINGS",
    action_label: "前往设置", preview: {}, created_at: "2026-08-18T08:02:00Z",
  },
]

const missions = [
  {
    id: "older", title: "较早的任务记录", objective: "", target_countries: [], target_industries: [],
    customer_profile: "", primary_product_id: "", start_date: "", end_date: "", target_account_count: 0,
    target_reply_count: 0, target_rfq_count: 0, budget_micros: 0, allowed_channels: [], attribution_code: "",
    status: "RUNNING", health_status: "RUNNING", health_reason: "", created_by: 1,
    created_at: "2026-08-18T08:00:00Z", latest_plan: null,
    lane_counts: { ACQUISITION: 0, OUTREACH: 0, SOCIAL: 0, ATTRIBUTION: 0 }, available_actions: [],
  },
  {
    id: "newer", title: "最新的任务记录", objective: "", target_countries: [], target_industries: [],
    customer_profile: "", primary_product_id: "", start_date: "", end_date: "", target_account_count: 0,
    target_reply_count: 0, target_rfq_count: 0, budget_micros: 0, allowed_channels: [], attribution_code: "",
    status: "RUNNING", health_status: "RUNNING", health_reason: "", created_by: 1,
    created_at: "2026-08-19T08:00:00Z", latest_plan: null,
    lane_counts: { ACQUISITION: 0, OUTREACH: 0, SOCIAL: 0, ATTRIBUTION: 0 }, available_actions: [],
  },
]

async function renderDashboard(fetchImpl: typeof fetch): Promise<void> {
  vi.stubGlobal("fetch", vi.fn(fetchImpl))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: DashboardPage },
      { path: "/missions", component: { template: "<p>missions</p>" } },
      { path: "/settings", component: { template: "<p>settings</p>" } },
      { path: "/opportunities", component: { template: "<p>opportunities</p>" } },
    ],
  })
  await router.push("/")
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(DashboardPage, { global: { plugins: [router, [VueQueryPlugin, { queryClient }]] } })
  await router.isReady()
}

afterEach(() => vi.unstubAllGlobals())

it("selects the urgent opportunity, settings blocker, and newest mission record", async () => {
  await renderDashboard((input) => Promise.resolve(new Response(JSON.stringify(
    String(input).includes("/missions") ? missions : workItems,
  ), { status: 200, headers: { "Content-Type": "application/json" } })))

  expect(await screen.findByRole("region", { name: "今日最重要机会" })).toBeInTheDocument()
  expect(await within(screen.getByRole("region", { name: "今日最重要机会" })).findByText("紧急机会")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "当前阻塞" })).getByText("邮箱连接失效")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "最新证据" })).getByText("最新的任务记录")).toBeVisible()
  expect(screen.getByRole("region", { name: "今日待办" })).toBeInTheDocument()
  expect(screen.queryByText("TODAY'S WORKSPACE")).not.toBeInTheDocument()
})

it("keeps opportunity, blocker, and evidence unknown while their records are loading", async () => {
  await renderDashboard(() => new Promise<Response>(() => {}))

  expect(within(screen.getByRole("region", { name: "今日最重要机会" })).getByText("正在读取待办")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "当前阻塞" })).getByText("正在读取待办")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "最新证据" })).getByText("正在读取增长记录")).toBeVisible()
})

it("does not convert ordinary request failures into absence conclusions", async () => {
  await renderDashboard(() => Promise.resolve(new Response(JSON.stringify({ detail: "offline" }), {
    status: 500, headers: { "Content-Type": "application/json" },
  })))

  expect(await within(screen.getByRole("region", { name: "今日最重要机会" })).findByText("待办暂时无法读取")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "当前阻塞" })).getByText("待办暂时无法读取")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "最新证据" })).getByText("增长记录暂时无法读取")).toBeVisible()
})

it("identifies forbidden records as inaccessible instead of empty", async () => {
  await renderDashboard(() => Promise.resolve(new Response(JSON.stringify({ detail: "forbidden" }), {
    status: 403, headers: { "Content-Type": "application/json" },
  })))

  expect(await within(screen.getByRole("region", { name: "今日最重要机会" })).findByText("无权查看待办")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "当前阻塞" })).getByText("无权查看待办")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "最新证据" })).getByText("无权查看增长记录")).toBeVisible()
})

it("uses explicit empty states only after both record lists resolve empty", async () => {
  await renderDashboard(() => Promise.resolve(new Response(JSON.stringify([]), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))

  expect(await within(screen.getByRole("region", { name: "今日最重要机会" })).findByText("暂无可确认的机会")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "当前阻塞" })).getByText("暂无已记录阻塞")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "最新证据" })).getByText("暂无增长记录")).toBeVisible()
})
