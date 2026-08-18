import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import AgentWorkspacePage from "./AgentWorkspacePage.vue"

const runs = [
  {
    id: "run-ai",
    goal: "分析目标市场",
    agent_type: "content_strategy",
    execution_mode: "AI_AGENT",
    planner_provider: "deepseek",
    planner_model: "deepseek-chat",
    status: "COMPLETED",
    terminal_reason: "complete",
    created_at: "2026-08-18T08:00:00Z",
    updated_at: "2026-08-18T08:05:00Z",
    steps: [],
    pending_approval: null,
  },
  {
    id: "run-auto",
    goal: "创建平台内容变体",
    agent_type: "platform_variants",
    execution_mode: "AUTOMATION",
    planner_provider: "",
    planner_model: "",
    status: "COMPLETED",
    terminal_reason: "complete",
    created_at: "2026-08-18T07:00:00Z",
    updated_at: "2026-08-18T07:05:00Z",
    steps: [],
    pending_approval: null,
  },
]

afterEach(() => vi.unstubAllGlobals())

it("presents four agent roles and truthful execution labels", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    const body = path.includes("provider-status") ? {
      mode: "CONFIGURED_AI",
      provider_label: "DeepSeek 官方 API",
      model: "deepseek-chat",
      configured: true,
      real_requests_enabled: true,
    } : runs
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
  }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/agent-workspace", component: AgentWorkspacePage },
      { path: "/opportunities", component: { template: "<p>客户机会</p>" } },
      { path: "/promotion", component: { template: "<p>社媒运营</p>" } },
      { path: "/settings/ai-model", component: { template: "<p>模型设置</p>" } },
    ],
  })
  await router.push("/agent-workspace")
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(AgentWorkspacePage, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })
  await router.isReady()

  expect(await screen.findByRole("heading", { name: "Agent 工作台" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "获客 Agent" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "内容 Agent" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "社媒 Agent" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "客户激活 Agent" })).toBeInTheDocument()
  expect(await screen.findAllByText("AI Agent")).not.toHaveLength(0)
  expect(screen.getByText("AI 生成任务")).toBeInTheDocument()
  expect(screen.getAllByText("自动化流程")).not.toHaveLength(0)
  expect(screen.getByText("DeepSeek 官方 API · deepseek-chat")).toBeInTheDocument()
})
