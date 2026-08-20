export type BusinessStatusTone = "neutral" | "info" | "warning" | "danger" | "success"

export type BusinessStatus = {
  label: string
  consequence: string
  tone: BusinessStatusTone
}

const statuses: Record<string, BusinessStatus> = {
  ACTION_REQUIRED: { label: "需要处理", consequence: "继续推进前，需要先处理当前问题。", tone: "warning" },
  ACTIVE: { label: "已启用", consequence: "该项可继续用于当前业务流程。", tone: "success" },
  APPROVED: { label: "已通过", consequence: "已完成审核，可进入下一步。", tone: "success" },
  ARCHIVED: { label: "已归档", consequence: "该项不会再参与当前流程。", tone: "neutral" },
  AWAITING_REVIEW: { label: "等待审核", consequence: "发布前仍需人工确认。", tone: "warning" },
  BUDGET_BLOCKED: { label: "预算受限", consequence: "预算限制会阻止后续执行。", tone: "warning" },
  BUDGET_EXCEEDED: { label: "预算已超限", consequence: "请调整预算或等待额度恢复后再继续。", tone: "warning" },
  CANCELED: { label: "已取消", consequence: "该项已停止，不会继续执行。", tone: "neutral" },
  CHANNEL_BLOCKED: { label: "渠道受阻", consequence: "请处理渠道配置或审核问题后再继续。", tone: "warning" },
  COMPLETED: { label: "已完成", consequence: "该项工作已经完成。", tone: "success" },
  CONFIGURATION_REQUIRED: { label: "需要配置", consequence: "配置完成前，暂不能继续执行。", tone: "warning" },
  CONFIGURED_AI: { label: "已配置 AI", consequence: "可在审批边界内使用已配置的 AI 能力。", tone: "success" },
  CONNECTED: { label: "已连接", consequence: "连接可用于当前业务流程。", tone: "success" },
  DATA_INSUFFICIENT: { label: "数据不足", consequence: "现有数据不足以支持可靠判断。", tone: "warning" },
  DISCONNECTED: { label: "未连接", consequence: "请先完成连接后再继续。", tone: "warning" },
  DRAFT: { label: "草稿", consequence: "尚未提交审核或执行。", tone: "neutral" },
  FAILED: { label: "执行失败", consequence: "该项未能完成，请查看原因后重试。", tone: "danger" },
  FAKE_OFFLINE: { label: "离线演示", consequence: "当前不会发起真实外部请求。", tone: "info" },
  INACTIVE: { label: "已停用", consequence: "该项当前不会参与业务流程。", tone: "neutral" },
  IN_REVIEW: { label: "审核中", consequence: "正在等待审核结果。", tone: "warning" },
  INSUFFICIENT_CAPABILITY: { label: "能力不足", consequence: "当前连接缺少完成此项工作的必要权限或能力。", tone: "warning" },
  KEY_REQUIRED: { label: "需要密钥", consequence: "配置平台密钥前，暂不能继续执行。", tone: "warning" },
  NOT_CONNECTED: { label: "尚未连接", consequence: "请先连接平台后再继续。", tone: "warning" },
  NOT_STARTED: { label: "尚未开始", consequence: "该项尚未进入执行流程。", tone: "neutral" },
  NORMAL: { label: "运行正常", consequence: "目前没有需要处理的业务风险。", tone: "success" },
  PAUSED: { label: "已暂停", consequence: "恢复前不会继续执行。", tone: "warning" },
  PARTIAL_SUCCESS: { label: "部分完成", consequence: "部分工作已完成，仍有事项需要处理。", tone: "warning" },
  PENDING_APPROVAL: { label: "待批准", consequence: "需要批准后才能进入执行。", tone: "warning" },
  PRIVATE_ONLY: { label: "仅限私域", consequence: "当前连接仅支持私域范围内的操作。", tone: "info" },
  PROVIDER_UNAVAILABLE: { label: "服务暂不可用", consequence: "外部服务暂时不可用，请稍后重试。", tone: "danger" },
  PUBLISHED: { label: "已发布", consequence: "内容已进入已发布状态。", tone: "success" },
  QUEUED: { label: "等待处理", consequence: "已进入队列，等待系统处理。", tone: "info" },
  READY: { label: "已就绪", consequence: "可进入下一步操作。", tone: "success" },
  REAUTHORIZATION_REQUIRED: { label: "需要重新授权", consequence: "重新授权前，相关操作暂不能继续。", tone: "warning" },
  REFRESH_DUE: { label: "需要刷新连接", consequence: "请刷新连接信息以保持服务可用。", tone: "warning" },
  REJECTED: { label: "未通过", consequence: "请根据审核意见调整后再提交。", tone: "danger" },
  RETRY_QUEUED: { label: "等待重试", consequence: "系统将按计划再次尝试执行。", tone: "info" },
  RUNNING: { label: "正在获客", consequence: "系统正在按当前计划推进获客工作。", tone: "info" },
  SCHEDULED: { label: "已安排", consequence: "将在安排的时间进入执行。", tone: "info" },
  SKIPPED: { label: "已跳过", consequence: "该项按当前规则未执行。", tone: "neutral" },
  STALE: { label: "结果已过期", consequence: "请刷新后确认当前结果。", tone: "warning" },
  SUBMITTED: { label: "已提交", consequence: "已提交至平台，等待处理结果。", tone: "info" },
  SUBMISSION_UNKNOWN: { label: "已提交，等待平台确认", consequence: "平台尚未确认提交结果，请暂勿重复发布。", tone: "warning" },
  SUCCEEDED: { label: "已完成", consequence: "该项已成功完成。", tone: "success" },
  SUPERSEDED: { label: "已被替代", consequence: "已有更新版本可供使用。", tone: "neutral" },
  TERMINATED: { label: "已终止", consequence: "该项已终止，不会继续执行。", tone: "danger" },
  WAITING_APPROVAL: { label: "等待人工审核", consequence: "需要人工确认后才能继续。", tone: "warning" },
  WAITING_PLATFORM_REVIEW: { label: "等待平台审核", consequence: "平台审核完成前，相关操作暂不能继续。", tone: "warning" },
}

const fallback: BusinessStatus = {
  label: "状态待确认",
  consequence: "系统尚未提供可解释的业务状态。",
  tone: "neutral",
}

export function businessStatus(status: string): BusinessStatus {
  return statuses[status] ?? fallback
}
