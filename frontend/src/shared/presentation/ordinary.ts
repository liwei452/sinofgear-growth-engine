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

export type OrdinaryJobNotice = { message: string; recovery: string }
type PublicJobError = { code?: unknown } | null | undefined
type PublicJobProgress = {
  status?: unknown
  retry_count?: unknown
  next_retry_at?: unknown
  error?: PublicJobError
}

const jobErrors: Readonly<Record<string, OrdinaryJobNotice>> = {
  job_error: {
    message: "这次没有处理完成。", recovery: "请稍后手动重试；仍有问题请联系管理员。",
  },
  provider_error: {
    message: "AI服务没有完成本次处理。", recovery: "请稍后手动重试；仍有问题请联系管理员。",
  },
  output_too_large: {
    message: "需要生成的内容超出处理范围，任务已停止。", recovery: "请减少输入资料或生成要求后重新尝试。",
  },
  ai_run_start_failed: {
    message: "AI任务没有成功启动。", recovery: "请稍后手动重试；仍有问题请联系管理员。",
  },
  content_finalize_failed: {
    message: "内容已经生成，但没有成功保存。", recovery: "请重新生成；仍有问题请联系管理员。",
  },
  invalid_provider_contract: {
    message: "AI服务返回了无法处理的结果，任务已停止。", recovery: "请联系管理员检查后再重试。",
  },
  provider_authentication_failed: {
    message: "AI服务的连接信息已失效，任务没有继续。", recovery: "请联系管理员检查连接后重新尝试。",
  },
  provider_balance_required: {
    message: "AI账户余额不足，任务没有继续扣费。", recovery: "请联系管理员充值后重新尝试。",
  },
  provider_rate_limited: {
    message: "当前使用人数较多，本次处理没有完成。", recovery: "请稍后重新尝试。",
  },
  provider_unavailable: {
    message: "AI服务暂时繁忙，本次处理没有完成。", recovery: "请稍后重新尝试。",
  },
  provider_timeout: {
    message: "AI服务响应超时，本次处理没有完成。", recovery: "请稍后重新尝试。",
  },
  provider_network_error: {
    message: "网络连接中断，本次处理没有完成。", recovery: "请检查网络后重新尝试。",
  },
  invalid_provider_output: {
    message: "AI返回的内容不符合要求，本次处理已停止。", recovery: "请检查输入资料后重新尝试。",
  },
  invalid_provider_output_after_repair: {
    message: "AI返回的内容仍不符合要求，本次处理已停止。", recovery: "请检查输入资料后重新尝试；仍有问题请联系管理员。",
  },
  deepseek_daily_budget_exceeded: {
    message: "今天的AI使用额度已达到上限，任务没有继续扣费。", recovery: "请联系管理员调整额度，或明天再试。",
  },
  deepseek_budget_unavailable: {
    message: "当前无法确认AI使用额度，任务已安全停止。", recovery: "请联系管理员检查额度后重新尝试。",
  },
  deepseek_retry_exhausted: {
    message: "多次尝试后仍未完成，系统已停止自动重试。", recovery: "请稍后手动重试；仍有问题请联系管理员。",
  },
  deepseek_usage_exceeds_reservation: {
    message: "本次AI用量超出预留范围，任务已安全停止。", recovery: "请联系管理员检查后再重试。",
  },
  deepseek_invalid_usage: {
    message: "本次AI用量记录异常，任务已安全停止。", recovery: "请联系管理员检查后再重试。",
  },
  deepseek_not_connected: {
    message: "AI服务尚未连接，任务没有开始。", recovery: "请联系管理员完成设置后重新尝试。",
  },
  deepseek_invalid_key: {
    message: "AI服务的连接信息无效，设置没有保存。", recovery: "请联系管理员重新填写连接信息。",
  },
  deepseek_balance_required: {
    message: "AI账户余额不足，任务没有继续扣费。", recovery: "请联系管理员充值后重新尝试。",
  },
  deepseek_rate_limited: {
    message: "当前使用人数较多，本次处理没有完成。", recovery: "请稍后重新尝试。",
  },
  deepseek_unavailable: {
    message: "AI服务暂时繁忙，本次处理没有完成。", recovery: "请稍后重新尝试。",
  },
  deepseek_credential_store_unavailable: {
    message: "当前无法安全保存AI连接信息。", recovery: "请联系管理员检查电脑设置。",
  },
  deepseek_invalid_configuration: {
    message: "AI服务设置不完整，设置没有保存。", recovery: "请联系管理员检查填写内容。",
  },
  deepseek_configuration_busy: {
    message: "另一项AI设置正在处理中。", recovery: "请等待管理员完成设置后再试。",
  },
  deepseek_configuration_superseded: {
    message: "AI服务设置已被更新。", recovery: "请刷新页面查看最新设置。",
  },
  deepseek_configuration_update_failed: {
    message: "AI服务设置没有保存成功。", recovery: "请联系管理员重新保存。",
  },
  deepseek_credential_state_uncertain: {
    message: "无法确认AI连接信息是否已保存。", recovery: "请联系管理员重新检查连接。",
  },
  administrator_approval_required: {
    message: "这项操作需要管理员确认。", recovery: "请联系管理员确认后重新尝试。",
  },
  job_canceled: {
    message: "任务已取消。", recovery: "如仍需处理，请重新发起。",
  },
}

const defaultJobError: OrdinaryJobNotice = {
  message: "这次没有处理完成。", recovery: "请稍后手动重试；仍有问题请联系管理员。",
}

export function ordinaryJobError(error: PublicJobError): OrdinaryJobNotice {
  const code = error && typeof error === "object" && typeof error.code === "string" ? error.code : ""
  return jobErrors[code] ?? defaultJobError
}

export function ordinaryJobProgress(job: PublicJobProgress): OrdinaryJobNotice {
  const retryCount = typeof job.retry_count === "number" && Number.isInteger(job.retry_count)
    && job.retry_count > 0 ? job.retry_count : 0
  const due = typeof job.next_retry_at === "string" && !Number.isNaN(Date.parse(job.next_retry_at))
    ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(new Date(job.next_retry_at))
    : ""
  if (retryCount && due && job.status !== "FAILED" && job.status !== "CANCELED") {
    return {
      message: `第 ${retryCount} 次再次处理已安排，预计 ${due} 继续。`,
      recovery: "暂时无需操作，系统会按计划继续。",
    }
  }
  if (job.status === "CANCELED") return jobErrors.job_canceled
  if (job.status === "FAILED") return ordinaryJobError(job.error)
  return { message: "任务正在处理中。", recovery: "暂时无需操作。" }
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

type DirectorAction = components["schemas"]["DirectorDecisionRequestActionEnum"]
const directorActions: Readonly<Record<DirectorAction, string>> = {
  APPROVE: "批准",
  REQUEST_ADJUSTMENT: "要求调整",
  REJECT: "拒绝",
}

export function ordinaryDirectorAction(action: DirectorAction): string {
  return directorActions[action]
}

export function ordinaryDirectorError(error: unknown): { message: string; refresh: boolean } {
  const code = error && typeof error === "object" && "code" in error
    && typeof error.code === "string" ? error.code : ""
  if (code === "director_version_conflict") {
    return { message: "这件事刚刚发生了变化，已为你刷新最新内容。", refresh: true }
  }
  if (code === "director_state_conflict" || code === "director_expired") {
    return { message: "这件事已经处理或过期，已为你刷新最新内容。", refresh: true }
  }
  if (code === "director_comment_required") {
    return { message: "请填写调整或拒绝的原因。", refresh: false }
  }
  return { message: "操作未能完成，请稍后重试。", refresh: false }
}

export function assertNeverOrdinaryValue(value: never): never {
  void value
  throw new Error("普通用户展示值未配置")
}
