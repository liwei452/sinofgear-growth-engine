import { expect, it } from "vitest"

import type { PublishTask } from "./api"
import {
  canShowConfirmNotPublished,
  defaultMonitoringTasks,
  hasUnsettledTasks,
  monitoringGroup,
  monitoringStatusLabel,
  sortMonitoringTasks,
} from "./publishMonitoring"

function task(status: PublishTask["status"], overrides: Partial<PublishTask> = {}): PublishTask {
  return {
    id: `task-${status}`,
    status,
    allowed_actions: {
      retry: { allowed: false, reason_code: "STATUS_NOT_RETRYABLE" },
      reconcile: { allowed: false, reason_code: "STATUS_NOT_RECONCILABLE" },
      confirm_published: { allowed: false, reason_code: "STATUS_NOT_RESOLVABLE" },
      confirm_not_published: { allowed: false, reason_code: "STATUS_NOT_RESOLVABLE" },
    },
    resolution_evidence: {
      ambiguous: false,
      candidate_count: null,
      latest_outcome: null,
      observed_at: null,
      query_window_end: null,
      query_window_ended: false,
      snapshot_valid: false,
      truncated: null,
    },
    ...overrides,
  } as PublishTask
}

it("classifies every server status in one operator-facing mapping", () => {
  expect(monitoringGroup("SCHEDULED")).toBe("WAITING")
  expect(monitoringGroup("QUEUED")).toBe("WAITING")
  expect(monitoringGroup("RUNNING")).toBe("WAITING")
  expect(monitoringGroup("SUBMITTED")).toBe("PROVIDER")
  expect(monitoringGroup("SUBMISSION_UNKNOWN")).toBe("PROVIDER")
  expect(monitoringGroup("NEEDS_ATTENTION")).toBe("ATTENTION")
  expect(monitoringGroup("FAILED")).toBe("FAILED")
  expect(monitoringGroup("SUCCEEDED")).toBe("COMPLETED")
  expect(monitoringGroup("CANCELED")).toBe("CANCELED")
})

it("uses safe Chinese labels without treating submitted as published", () => {
  expect(monitoringStatusLabel("SUBMITTED")).toBe("Buffer 已接收，等待发布确认")
  expect(monitoringStatusLabel("SUBMISSION_UNKNOWN")).toBe("提交结果未知，系统正在安全对账")
  expect(monitoringStatusLabel("NEEDS_ATTENTION")).toBe("需要人工确认")
  expect(monitoringStatusLabel("SUCCEEDED")).toBe("已确认发布")
})

it("sorts attention before provider waits, failures, active work, and history", () => {
  const sorted = sortMonitoringTasks([
    task("SUCCEEDED"),
    task("RUNNING"),
    task("FAILED"),
    task("SUBMISSION_UNKNOWN"),
    task("NEEDS_ATTENTION"),
  ])
  expect(sorted.map(item => item.status)).toEqual([
    "NEEDS_ATTENTION", "SUBMISSION_UNKNOWN", "FAILED", "RUNNING", "SUCCEEDED",
  ])
})

it("keeps default history compact while preserving all active work", () => {
  const active = task("NEEDS_ATTENTION")
  const history = Array.from({ length: 8 }, (_, index) => task("SUCCEEDED", {
    id: `success-${index}`,
    created_at: `2026-08-${String(index + 1).padStart(2, "0")}T08:00:00Z`,
  }))
  const visible = defaultMonitoringTasks([active, ...history])
  expect(visible.filter(item => item.status === "NEEDS_ATTENTION")).toHaveLength(1)
  expect(visible.filter(item => item.status === "SUCCEEDED")).toHaveLength(5)
})

it("polls only while a server task is unsettled", () => {
  expect(hasUnsettledTasks([task("RUNNING")])).toBe(true)
  expect(hasUnsettledTasks([task("SUBMITTED")])).toBe(true)
  expect(hasUnsettledTasks([task("NEEDS_ATTENTION")])).toBe(false)
  expect(hasUnsettledTasks([task("FAILED"), task("SUCCEEDED")])).toBe(false)
})

it("never grants no-post confirmation and only displays strict server evidence", () => {
  const allowed = {
    allowed_actions: {
      ...task("NEEDS_ATTENTION").allowed_actions,
      confirm_not_published: { allowed: true, reason_code: null },
    },
  }
  const strict = task("NEEDS_ATTENTION", {
    ...allowed,
    resolution_evidence: {
      ambiguous: false,
      candidate_count: 0,
      latest_outcome: "NO_MATCH",
      observed_at: "2026-08-21T08:00:00Z",
      query_window_end: "2026-08-21T07:00:00Z",
      query_window_ended: true,
      snapshot_valid: true,
      truncated: false,
    },
  })

  expect(canShowConfirmNotPublished(strict)).toBe(true)
  expect(canShowConfirmNotPublished(task("NEEDS_ATTENTION", {
    ...allowed,
    resolution_evidence: { ...strict.resolution_evidence, truncated: null },
  }))).toBe(false)
  expect(canShowConfirmNotPublished(task("NEEDS_ATTENTION", {
    ...allowed,
    resolution_evidence: { ...strict.resolution_evidence, truncated: true },
  }))).toBe(false)
  expect(canShowConfirmNotPublished(task("NEEDS_ATTENTION", {
    ...allowed,
    resolution_evidence: { ...strict.resolution_evidence, snapshot_valid: false },
  }))).toBe(false)
  expect(canShowConfirmNotPublished(task("NEEDS_ATTENTION", {
    resolution_evidence: strict.resolution_evidence,
  }))).toBe(false)
})
