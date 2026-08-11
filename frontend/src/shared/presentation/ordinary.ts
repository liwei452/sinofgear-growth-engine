import type { components } from "../../api/generated/schema"

type OrdinaryTerm = "Campaign" | "ContentBrief" | "LeadCandidate" | "Ontology"
type OrdinaryStatus =
  | components["schemas"]["ActiveStatusEnum"]
  | components["schemas"]["AIRunStatusEnum"]
  | components["schemas"]["CandidateStatusEnum"]
  | components["schemas"]["ContentBriefStatusEnum"]
  | components["schemas"]["JobStatusEnum"]
  | components["schemas"]["KnowledgeStatusEnum"]
  | components["schemas"]["LeadAnalyzeAcceptedStatusEnum"]
  | components["schemas"]["MasterContentStatusEnum"]
  | components["schemas"]["MaterialAssetStatusEnum"]
  | components["schemas"]["PlatformContentStatusEnum"]
  | components["schemas"]["ProductStatusEnum"]
  | components["schemas"]["PublishAttemptStatusEnum"]
  | components["schemas"]["PublishTaskStatusEnum"]
  | components["schemas"]["ShortLinkStatusEnum"]
  | components["schemas"]["StatusDbdEnum"]

const terms: Readonly<Record<OrdinaryTerm, string>> = {
  Campaign: "推广计划",
  ContentBrief: "推广要求",
  LeadCandidate: "潜在客户",
  Ontology: "AI 对公司的了解",
}

const statuses: Readonly<Record<OrdinaryStatus, string>> = {
  ACTIVE: "启用中",
  INACTIVE: "未启用",
  RUNNING: "正在处理",
  SUCCEEDED: "已完成",
  FAILED: "处理失败",
  CANCELED: "已取消",
  CANCELLED: "已取消",
  DISCOVERED: "新发现",
  ANALYZING: "正在判断",
  ANALYZED: "判断完成",
  REVIEWED: "已人工确认",
  READY_FOR_HANDOFF: "可联系",
  HANDED_OFF: "已交接",
  DISMISSED: "已忽略",
  DRAFT: "草稿",
  READY: "可生成",
  QUEUED: "等待处理",
  RETRY_QUEUED: "等待重试",
  SUGGESTED: "等待确认",
  APPROVED: "已批准",
  REJECTED: "已退回",
  DEPRECATED: "已停用",
  IN_REVIEW: "等待确认",
  ARCHIVED: "已归档",
  PUBLISHED: "已发布",
  STALE: "已过期",
  SCHEDULED: "已安排",
  DISABLED: "已停用",
  PARTIAL_SUCCESS: "部分完成",
}

const platforms: Readonly<Record<string, string>> = {
  LINKEDIN: "领英",
  YOUTUBE: "YouTube",
  FACEBOOK: "Facebook",
  INSTAGRAM: "Instagram",
  TIKTOK: "TikTok",
  MANUAL: "手动录入",
}

const scoreBands: Readonly<Record<components["schemas"]["ScoreBandEnum"], string>> = {
  HIGH: "高价值",
  WATCH: "重点关注",
  OBSERVE: "持续观察",
  LOW: "低优先级",
}

export function ordinaryTerm(value: OrdinaryTerm | string | null | undefined): string {
  return value ? terms[value as OrdinaryTerm] ?? "业务内容" : "业务内容"
}

export function ordinaryStatus(value: OrdinaryStatus | string | null | undefined): string {
  return value ? statuses[value as OrdinaryStatus] ?? "状态待确认" : "暂无状态"
}

export function ordinaryPlatform(value: string | null | undefined): string {
  return value ? platforms[value.trim().toUpperCase()] ?? "平台待确认" : "暂无平台"
}

export function ordinaryScoreBand(value: components["schemas"]["ScoreBandEnum"] | string | null | undefined): string {
  return value ? scoreBands[value as components["schemas"]["ScoreBandEnum"]] ?? "价值待确认" : "暂无价值判断"
}

export function formatOrdinaryError(error: unknown): string {
  void error
  return "操作未能完成，请稍后重试。"
}

export function assertNeverOrdinaryValue(value: never): never {
  void value
  throw new Error("普通用户展示值未配置")
}
