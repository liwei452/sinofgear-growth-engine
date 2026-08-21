import { ApiError, apiRequest } from "../../api/client"
import type { components } from "../../api/generated/schema"

export type PublishTask = components["schemas"]["PublishTask"]
export type PublishTaskPage = components["schemas"]["PublishTaskCursorEnvelope"]
export type PublishResolutionRequest = components["schemas"]["PublishResolutionRequest"]

function required<T>(value: T | undefined): T {
  if (value === undefined) throw new ApiError(0, "服务响应不完整，请重试。")
  return value
}

export const publishingMonitorKeys = {
  all: ["publishing-monitor"] as const,
  tasks: ["publishing-monitor", "tasks"] as const,
}

export const listPublishTasks = async (): Promise<PublishTaskPage> => required(
  await apiRequest<PublishTaskPage>("/api/v1/publish-tasks?page_size=50"),
)

export const retryPublishTask = async (taskId: string): Promise<PublishTask> => required(
  await apiRequest<PublishTask>(`/api/v1/publish-tasks/${taskId}/retry`, { method: "POST" }),
)

export const reconcilePublishTask = async (taskId: string): Promise<PublishTask> => required(
  await apiRequest<PublishTask>(`/api/v1/publish-tasks/${taskId}/reconcile`, { method: "POST" }),
)

export const resolvePublishTask = async (
  taskId: string,
  input: PublishResolutionRequest,
): Promise<PublishTask> => required(
  await apiRequest<PublishTask>(`/api/v1/publish-tasks/${taskId}/resolve`, {
    method: "POST",
    body: input,
  }),
)
