import { expect, it } from "vitest"

import {
  formatOrdinaryError,
  ordinaryPlatform,
  ordinaryScoreBand,
  ordinaryStatus,
  ordinaryTerm,
} from "./ordinary"

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
