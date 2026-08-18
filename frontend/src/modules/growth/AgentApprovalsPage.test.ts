import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import AgentApprovalsPage from "./AgentApprovalsPage.vue"

const pendingRun = {
  id: "run-1",
  goal: "为德国客户准备一封人工审核的开发信",
  status: "WAITING_APPROVAL",
  terminal_reason: null,
  created_at: "2026-08-18T08:00:00Z",
  updated_at: "2026-08-18T08:05:00Z",
  steps: [{
    index: 1,
    tool_name: "draft_outreach",
    args: { account_id: "account-1" },
    outcome: "drafted",
    output: { english_draft: "Hello, we prepared this draft for your review." },
    error: null,
    reasoning: "Public evidence passed the drafting threshold.",
  }],
  pending_approval: {
    tool_name: "send_outreach",
    tool_args: { account_id: "account-1" },
    reasoning: "The message is ready but cannot be sent without approval.",
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("puts the human decision ahead of technical agent execution data", async () => {
  document.cookie = "csrftoken=agent-approval-token; path=/"
  let approvalBody: unknown
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      approvalBody = JSON.parse(String(init.body))
      return new Response(JSON.stringify({ ...pendingRun, status: "COMPLETED" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }
    return new Response(JSON.stringify([pendingRun]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(AgentApprovalsPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByRole("heading", { name: "等待你决定" })).toBeInTheDocument()
  expect(await screen.findByRole("region", { name: pendingRun.goal })).toBeInTheDocument()
  expect(screen.getByText("Hello, we prepared this draft for your review.")).toBeInTheDocument()
  const technicalSummary = screen.getByText("技术执行记录")
  expect(technicalSummary.closest("details")).not.toHaveAttribute("open")
  expect(screen.getByRole("button", { name: "批准执行" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "拒绝" })).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "批准执行" }))
  await waitFor(() => expect(approvalBody).toEqual({ decision: "approve" }))
})
