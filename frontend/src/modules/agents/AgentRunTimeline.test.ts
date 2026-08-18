import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it } from "vitest"

import type { AgentRun } from "../growth/agentApi"
import AgentRunTimeline from "./AgentRunTimeline.vue"

const run: AgentRun = {
  id: "run-1",
  goal: "分析重点市场并准备内容方向",
  agent_type: "content_strategy",
  execution_mode: "AI_AGENT",
  planner_provider: "deepseek",
  planner_model: "deepseek-chat",
  status: "WAITING_APPROVAL",
  terminal_reason: null,
  created_at: "2026-08-18T08:00:00Z",
  updated_at: "2026-08-18T08:05:00Z",
  steps: [
    {
      index: 0,
      tool_name: "analyze_content_opportunities",
      args: { account_id: "hidden-account" },
      outcome: "succeeded",
      output: { count: 3 },
      error: null,
      reasoning: "Analyze verified evidence.",
    },
    {
      index: 1,
      tool_name: "create_content_brief",
      args: {},
      outcome: "blocked_approval",
      output: null,
      error: null,
      reasoning: "Human approval is required.",
    },
  ],
  pending_approval: {
    tool_name: "create_content_brief",
    tool_args: {},
    reasoning: "Human approval is required.",
  },
}

it("shows business progress first and reveals raw technical data on demand", async () => {
  const user = userEvent.setup()
  render(AgentRunTimeline, { props: { run } })

  expect(screen.getByText("AI Agent")).toBeInTheDocument()
  expect(screen.getByText("分析市场与内容机会")).toBeInTheDocument()
  expect(screen.getByText("等待你批准")).toBeInTheDocument()
  expect(screen.queryByText(/hidden-account/)).not.toBeInTheDocument()

  await user.click(screen.getByText("技术记录"))

  expect(screen.getByText(/hidden-account/)).toBeInTheDocument()
})
