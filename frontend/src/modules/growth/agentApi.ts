import { queryOptions } from "@tanstack/vue-query"

import { apiRequest } from "../../api/client"


export type AgentRunStep = {
  index: number
  tool_name: string | null
  args: Record<string, unknown>
  outcome: string
  output: Record<string, unknown> | null
  error: string | null
  reasoning: string
}

export type AgentRun = {
  id: string
  goal: string
  status: "RUNNING" | "WAITING_APPROVAL" | "COMPLETED" | "BUDGET_EXCEEDED" | "FAILED"
  terminal_reason: string | null
  created_at: string
  updated_at: string
  steps: AgentRunStep[]
  pending_approval: {
    tool_name: string | null
    tool_args: Record<string, unknown> | null
    reasoning: string
  } | null
}

export function agentRunsQueryOptions(status?: string) {
  const query = status ? `?status=${encodeURIComponent(status)}` : ""
  return queryOptions({
    queryKey: ["growth", "agent-runs", status ?? "all"],
    queryFn: async () => {
      const runs = await apiRequest<AgentRun[]>(`/api/v1/growth/agent/runs${query}`)
      if (!runs) throw new Error("agent 运行列表为空")
      return runs
    },
    staleTime: 10_000,
  })
}

export async function approveAgentRun(
  runId: string,
  decision: "approve" | "reject",
): Promise<AgentRun> {
  const result = await apiRequest<AgentRun>(
    `/api/v1/growth/agent/runs/${runId}/approve`,
    { method: "POST", body: { decision } },
  )
  if (!result) throw new Error("审批失败")
  return result
}

export type AgentRunStartResult = {
  status: string
  terminal_reason: string | null
  pending_approval_token: string | null
}

export async function startAgentRun(
  agentType: string,
  params: Record<string, unknown> = {},
): Promise<AgentRunStartResult> {
  const result = await apiRequest<AgentRunStartResult>(
    "/api/v1/growth/agent/runs/start",
    { method: "POST", body: { agent_type: agentType, ...params } },
  )
  if (!result) throw new Error("启动失败")
  return result
}
