import { render, screen, within } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { expect, it } from "vitest"

import type { AgentRun } from "../growth/agentApi"
import DashboardSideRail from "./DashboardSideRail.vue"

function run(id: string, status: AgentRun["status"]): AgentRun {
  return {
    id,
    goal: `任务 ${id}`,
    status,
    terminal_reason: null,
    created_at: `2026-08-18T0${id}:00:00Z`,
    updated_at: `2026-08-18T0${id}:30:00Z`,
    steps: [],
    pending_approval: status === "WAITING_APPROVAL"
      ? { tool_name: "review", tool_args: {}, reasoning: "需要人工批准" }
      : null,
  }
}

it("caps actionable rail lists and explains the real model mode", async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<p>今天</p>" } },
      { path: "/settings", component: { template: "<p>设置</p>" } },
      { path: "/agent-workspace", component: { template: "<p>Agent</p>" } },
      { path: "/platform-accounts", component: { template: "<p>平台</p>" } },
    ],
  })
  await router.push("/")
  await router.isReady()
  render(DashboardSideRail, {
    props: {
      modelStatus: {
        mode: "CONFIGURED_AI",
        provider_label: "DeepSeek 官方 API",
        model: "deepseek-chat",
        configured: true,
        real_requests_enabled: true,
      },
      pendingRuns: [run("1", "WAITING_APPROVAL"), run("2", "WAITING_APPROVAL"), run("3", "WAITING_APPROVAL"), run("4", "WAITING_APPROVAL")],
      channelIssues: ["Facebook", "Instagram", "LinkedIn", "TikTok", "YouTube", "Extra"].map((name, index) => ({
        code: String(index), name, status: "未连接", recovery: "完成管理员配置",
      })),
      completedRuns: [run("5", "COMPLETED"), run("6", "COMPLETED"), run("7", "COMPLETED"), run("8", "COMPLETED")],
    },
    global: { plugins: [router] },
  })

  const rail = screen.getByRole("complementary", { name: "工作台状态" })
  expect(within(rail).getByText("DeepSeek 官方 API · deepseek-chat")).toBeVisible()
  expect(within(rail).getAllByText(/任务 [1-4]/)).toHaveLength(3)
  expect(within(rail).queryByText("Extra")).not.toBeInTheDocument()
  expect(within(rail).getAllByText(/任务 [5-8]/)).toHaveLength(3)
})
