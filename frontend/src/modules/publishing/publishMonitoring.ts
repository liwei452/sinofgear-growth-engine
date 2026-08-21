import type { PublishTask } from "./api"

export type MonitoringGroup = "ATTENTION" | "PROVIDER" | "FAILED" | "WAITING" | "COMPLETED" | "CANCELED"

const GROUP_PRIORITY: Record<MonitoringGroup, number> = {
  ATTENTION: 0,
  PROVIDER: 1,
  FAILED: 2,
  WAITING: 3,
  COMPLETED: 4,
  CANCELED: 5,
}

export function monitoringGroup(status: PublishTask["status"]): MonitoringGroup {
  switch (status) {
    case "SCHEDULED":
    case "QUEUED":
    case "RUNNING": return "WAITING"
    case "SUBMITTED":
    case "SUBMISSION_UNKNOWN": return "PROVIDER"
    case "NEEDS_ATTENTION": return "ATTENTION"
    case "FAILED": return "FAILED"
    case "SUCCEEDED": return "COMPLETED"
    case "CANCELED": return "CANCELED"
  }
}

export function monitoringStatusLabel(status: PublishTask["status"]): string {
  switch (status) {
    case "SCHEDULED": return "已排期，等待执行"
    case "QUEUED": return "已进入发布队列"
    case "RUNNING": return "正在提交到 Provider"
    case "SUBMITTED": return "Buffer 已接收，等待发布确认"
    case "SUBMISSION_UNKNOWN": return "提交结果未知，系统正在安全对账"
    case "NEEDS_ATTENTION": return "需要人工确认"
    case "SUCCEEDED": return "已确认发布"
    case "FAILED": return "发布失败"
    case "CANCELED": return "已取消"
  }
}

export function sortMonitoringTasks(tasks: readonly PublishTask[]): PublishTask[] {
  return [...tasks].sort((left, right) => {
    const priority = GROUP_PRIORITY[monitoringGroup(left.status)] - GROUP_PRIORITY[monitoringGroup(right.status)]
    if (priority !== 0) return priority
    return right.created_at.localeCompare(left.created_at)
  })
}

export function defaultMonitoringTasks(tasks: readonly PublishTask[], completedLimit = 5): PublishTask[] {
  let completedCount = 0
  return sortMonitoringTasks(tasks).filter((task) => {
    if (monitoringGroup(task.status) !== "COMPLETED") return true
    completedCount += 1
    return completedCount <= completedLimit
  })
}

export function hasUnsettledTasks(tasks: readonly PublishTask[]): boolean {
  return tasks.some(task => monitoringGroup(task.status) === "WAITING" || monitoringGroup(task.status) === "PROVIDER")
}

export function canShowConfirmNotPublished(task: PublishTask): boolean {
  if (!task.allowed_actions.confirm_not_published.allowed) return false
  const evidence = task.resolution_evidence
  return evidence.candidate_count === 0
    && evidence.query_window_ended === true
    && evidence.truncated === false
    && evidence.snapshot_valid === true
}

export function isNativeBufferPostId(value: string): boolean {
  const normalized = value.trim()
  return normalized.length > 0
    && normalized.length <= 255
    && !normalized.includes("://")
    && !/[\s/]/.test(normalized)
}
