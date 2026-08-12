import { expect, it } from "vitest"

import {
  formatOrdinaryError,
  ordinaryJobError,
  ordinaryJobProgress,
  ordinaryPlatform,
  ordinaryScoreBand,
  ordinaryStatus,
  ordinaryTerm,
} from "./ordinary"

it.each([
  ["provider_authentication_failed", "AI服务的连接信息已失效，任务没有继续。", "请联系管理员检查连接后重新尝试。"],
  ["provider_balance_required", "AI账户余额不足，任务没有继续扣费。", "请联系管理员充值后重新尝试。"],
  ["provider_rate_limited", "当前使用人数较多，本次处理没有完成。", "请稍后重新尝试。"],
  ["provider_unavailable", "AI服务暂时繁忙，本次处理没有完成。", "请稍后重新尝试。"],
  ["provider_timeout", "AI服务响应超时，本次处理没有完成。", "请稍后重新尝试。"],
  ["invalid_provider_output_after_repair", "AI返回的内容仍不符合要求，本次处理已停止。", "请检查输入资料后重新尝试；仍有问题请联系管理员。"],
  ["deepseek_daily_budget_exceeded", "今天的AI使用额度已达到上限，任务没有继续扣费。", "请联系管理员调整额度，或明天再试。"],
  ["deepseek_retry_exhausted", "多次尝试后仍未完成，系统已停止自动重试。", "请稍后手动重试；仍有问题请联系管理员。"],
  ["deepseek_invalid_usage", "本次AI用量记录异常，任务已安全停止。", "请联系管理员检查后再重试。"],
  ["deepseek_not_connected", "AI服务尚未连接，任务没有开始。", "请联系管理员完成设置后重新尝试。"],
  ["deepseek_invalid_key", "AI服务的连接信息无效，设置没有保存。", "请联系管理员重新填写连接信息。"],
  ["deepseek_configuration_busy", "另一项AI设置正在处理中。", "请等待管理员完成设置后再试。"],
  ["administrator_approval_required", "这项操作需要管理员确认。", "请联系管理员确认后重新尝试。"],
  ["job_error", "这次没有处理完成。", "请稍后手动重试；仍有问题请联系管理员。"],
  ["provider_error", "AI服务没有完成本次处理。", "请稍后手动重试；仍有问题请联系管理员。"],
  ["output_too_large", "需要生成的内容超出处理范围，任务已停止。", "请减少输入资料或生成要求后重新尝试。"],
  ["ai_run_start_failed", "AI任务没有成功启动。", "请稍后手动重试；仍有问题请联系管理员。"],
  ["content_finalize_failed", "内容已经生成，但没有成功保存。", "请重新生成；仍有问题请联系管理员。"],
  ["invalid_provider_contract", "AI服务返回了无法处理的结果，任务已停止。", "请联系管理员检查后再重试。"],
] as const)("maps controlled job error %s to beginner Chinese", (code, message, recovery) => {
  expect(ordinaryJobError({ code, message: "raw secret V4 Flash Pro 模型" })).toEqual({ message, recovery })
})

it("shows safe retry count and time without promising terminal recovery", () => {
  const scheduled = ordinaryJobProgress({
    status: "RUNNING", retry_count: 1, next_retry_at: "2026-08-12T06:30:00Z", error: null,
  })
  expect(scheduled.message).toContain("第 1 次")
  expect(scheduled.message).toContain("再次处理")
  expect(scheduled.recovery).toBe("暂时无需操作，系统会按计划继续。")

  const terminal = ordinaryJobProgress({
    status: "FAILED", retry_count: 2, next_retry_at: null,
    error: { code: "deepseek_retry_exhausted", message: "raw provider detail" },
  })
  expect(terminal.message).toContain("已停止自动重试")
  expect(`${terminal.message}${terminal.recovery}`).not.toMatch(/V4|Flash|Pro|模型|raw provider detail/)
})

it.each([
  ["Campaign", "推广计划"],
  ["ContentBrief", "推广要求"],
  ["LeadCandidate", "潜在客户"],
  ["Ontology", "AI 对公司的了解"],
])("translates %s for ordinary users", (input, expected) => {
  expect(ordinaryTerm(input)).toBe(expected)
})

it("never leaks an unknown server enum to ordinary users", () => {
  expect(ordinaryStatus("NEW_SERVER_STATE")).toBe("状态待确认")
  expect(ordinaryStatus("NEW_SERVER_STATE")).not.toContain("NEW_SERVER_STATE")
})

it.each([
  "ACTIVE", "INACTIVE", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED",
  "DISCOVERED", "ANALYZING", "ANALYZED", "REVIEWED", "READY_FOR_HANDOFF", "HANDED_OFF", "DISMISSED",
  "DRAFT", "READY", "QUEUED", "RETRY_QUEUED", "SUGGESTED", "APPROVED", "REJECTED", "DEPRECATED",
  "IN_REVIEW", "ARCHIVED", "PUBLISHED", "STALE", "SCHEDULED", "DISABLED", "PARTIAL_SUCCESS", "CANCELLED",
])("renders generated status %s without an enum token", (status) => {
  expect(ordinaryStatus(status)).not.toMatch(/[A-Z_]{2,}/)
})

it.each([
  ["LINKEDIN", "领英"],
  ["YOUTUBE", "YouTube"],
  ["FACEBOOK", "Facebook"],
  ["INSTAGRAM", "Instagram"],
  ["TIKTOK", "TikTok"],
  ["MANUAL", "手动录入"],
])("translates platform %s", (input, expected) => {
  expect(ordinaryPlatform(input)).toBe(expected)
})

it.each([
  ["HIGH", "高价值"],
  ["WATCH", "重点关注"],
  ["OBSERVE", "持续观察"],
  ["LOW", "低优先级"],
])("translates value band %s", (input, expected) => {
  expect(ordinaryScoreBand(input)).toBe(expected)
})

it("uses safe Chinese fallbacks for missing values and unexpected errors", () => {
  expect(ordinaryPlatform("UNLISTED_PLATFORM")).toBe("平台待确认")
  expect(ordinaryScoreBand("UNLISTED_BAND")).toBe("价值待确认")
  expect(ordinaryScoreBand(null)).toBe("暂无价值判断")
  expect(formatOrdinaryError(new Error("INTERNAL_PERMISSION_CODE"))).toBe("操作未能完成，请稍后重试。")
})
