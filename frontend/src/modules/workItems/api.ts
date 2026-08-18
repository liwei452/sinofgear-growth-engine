import { queryOptions } from "@tanstack/vue-query"

import { apiRequest } from "../../api/client"
import {
  approveAllChannelPackages,
  retryFailedPublishBatch,
} from "../growth/api"
import { approveAgentRun } from "../growth/agentApi"

export type WorkItemActionType =
  | "APPROVE_AGENT_RUN"
  | "APPROVE_CHANNEL_PACKAGE_GROUP"
  | "RETRY_PUBLISH_BATCH"
  | "OPEN_CUSTOMER"
  | "OPEN_SETTINGS"

export type WorkItem = {
  id: string
  mission_id: string | null
  mission_title: string
  kind: string
  title: string
  summary: string
  priority: "URGENT" | "HIGH" | "NORMAL"
  source_type: string
  source_id: string
  source_ids: string[]
  action_type: string
  action_label: string
  preview: Record<string, unknown>
  created_at: string
}

export const workItemsQueryKeys = {
  list: ["growth", "work-items"] as const,
}

export function workItemsQueryOptions() {
  return queryOptions({
    queryKey: workItemsQueryKeys.list,
    queryFn: async () => {
      const items = await apiRequest<WorkItem[]>("/api/v1/growth/work-items")
      if (!items) throw new Error("今日待办响应为空。")
      return items
    },
    staleTime: 10_000,
  })
}

const workItemActions = {
  APPROVE_AGENT_RUN: (item: WorkItem) => approveAgentRun(item.source_id, "approve"),
  APPROVE_CHANNEL_PACKAGE_GROUP: (item: WorkItem) => approveAllChannelPackages(item.source_ids),
  RETRY_PUBLISH_BATCH: (item: WorkItem) => retryFailedPublishBatch(item.source_id),
} satisfies Partial<Record<WorkItemActionType, (item: WorkItem) => Promise<unknown>>>

export function executeWorkItemAction(item: WorkItem): Promise<unknown> {
  const action = workItemActions[item.action_type as WorkItemActionType]
  if (!action) {
    throw new Error(`不支持的工作项操作：${item.action_type}`)
  }
  return action(item)
}
