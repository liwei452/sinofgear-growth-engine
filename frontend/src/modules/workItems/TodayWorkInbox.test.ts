import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import type { WorkItem } from "./api"
import TodayWorkInbox from "./TodayWorkInbox.vue"

const items: WorkItem[] = [
  {
    id: "OUTREACH_REVIEW:run-1",
    mission_id: "mission-1",
    mission_title: "南非矿山试点",
    kind: "OUTREACH_REVIEW",
    title: "批准南非矿山客户开发信",
    summary: "Agent 已生成个性化开发信，等待人工批准发送。",
    priority: "HIGH",
    source_type: "agent_run",
    source_id: "run-1",
    source_ids: ["run-1"],
    action_type: "APPROVE_AGENT_RUN",
    action_label: "批准并发送",
    preview: { draft: "Hello from SINOF." },
    created_at: "2026-08-18T08:00:00Z",
  },
  {
    id: "SOCIAL_REVIEW:master-1",
    mission_id: "mission-1",
    mission_title: "南非矿山试点",
    kind: "SOCIAL_REVIEW",
    title: "批准社媒内容",
    summary: "一组多平台社媒内容等待统一批准。",
    priority: "HIGH",
    source_type: "channel_package_group",
    source_id: "package-1",
    source_ids: ["package-1", "package-2"],
    action_type: "APPROVE_CHANNEL_PACKAGE_GROUP",
    action_label: "批准并排期",
    preview: { platforms: [{ channel: "LINKEDIN", title: "Gear proof" }] },
    created_at: "2026-08-18T08:01:00Z",
  },
  {
    id: "CONFIGURATION_BLOCK:run-2",
    mission_id: null,
    mission_title: "未归属增长任务",
    kind: "CONFIGURATION_BLOCK",
    title: "平台连接失效",
    summary: "渠道尚未接通。",
    priority: "HIGH",
    source_type: "agent_run",
    source_id: "run-2",
    source_ids: ["run-2"],
    action_type: "OPEN_SETTINGS",
    action_label: "等待管理员连接邮箱",
    preview: {},
    created_at: "2026-08-18T08:02:00Z",
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0"
})

it("shows mixed work items with one primary action each", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify(items), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }))))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: TodayWorkInbox },
      { path: "/missions", component: { template: "<p>missions</p>" } },
    ],
  })
  await router.push("/")
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(TodayWorkInbox, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()

  expect(await screen.findByText("批准南非矿山客户开发信")).toBeVisible()
  expect(screen.getByRole("button", { name: "批准并发送" })).toBeVisible()
  expect(screen.getByRole("button", { name: "批准并排期" })).toBeVisible()
  expect(screen.getByText("平台连接失效")).toBeVisible()
  expect(screen.queryByRole("link", { name: "先去审核中心" })).not.toBeInTheDocument()
})

it("announces a completed work-item action before refreshing the dashboard records", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify(items), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }))))
  document.cookie = "csrftoken=test"
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: TodayWorkInbox },
      { path: "/missions", component: { template: "<p>missions</p>" } },
    ],
  })
  await router.push("/")
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(TodayWorkInbox, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()

  await userEvent.click(await screen.findByRole("button", { name: "批准并发送" }))

  expect(await screen.findByText("已完成；相关任务和机会状态已更新。"))
    .toHaveAttribute("aria-live", "polite")
})
