<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue"

import { ApiError } from "../../api/client"
import OperationModal from "../../shared/components/OperationModal.vue"
import { ordinaryJobProgress, ordinaryPlatform } from "../../shared/presentation/ordinary"
import { currentUserQueryOptions } from "../auth/auth"
import {
  analyzeLeadCandidate,
  createLeadReview,
  getJob,
  getLeadCandidate,
  isActiveImportJob,
  leadKeys,
  safePublicHttpUrl,
  type LeadReviewCreate,
} from "./api"
import LeadHandoffPanel from "./LeadHandoffPanel.vue"

type ReviewAction = "CONFIRM" | "CORRECT" | "DISMISS" | "REOPEN" | "REQUEST_MORE_EVIDENCE"
type CompanyCorrection = { company_name?: string; company_domain?: string; country_hint?: string }
type RecoveryState = "idle" | "refreshing" | "ready" | "unavailable" | "blocked"

const props = defineProps<{ organizationId: string; candidateId: string | null; open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const queryClient = useQueryClient()
const currentUserQuery = useQuery(currentUserQueryOptions())

const selectedAction = ref<ReviewAction | null>(null)
const reason = ref("")
const correctedName = ref("")
const correctedDomain = ref("")
const correctedCountry = ref("")
const correctedFields = ref<Set<keyof CompanyCorrection>>(new Set())
const message = ref("")
const alert = ref("")
const recoveryState = ref<RecoveryState>("idle")
const submitting = ref(false)
const analyzing = ref(false)
const activeJobId = ref<string | null>(null)
const handoffOpen = ref(false)
const reviewHeading = ref<HTMLElement | null>(null)
const decisionSection = ref<HTMLElement | null>(null)
const decisionHeading = ref<HTMLElement | null>(null)
const handoffRegion = ref<HTMLElement | null>(null)
const crmHandoffButton = ref<HTMLButtonElement | null>(null)
let reviewOpener: HTMLElement | null = null
let reviewOpenerLabel = ""
let pollTimer: ReturnType<typeof setTimeout> | undefined
let session = 0
let reviewKeySignature = ""
let reviewKey = ""
let analyzeKeySignature = ""
let analyzeKey = ""

const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const canAnalyze = computed(() => permissions.value.includes("leads.analyze"))
const canReview = computed(() => permissions.value.includes("leads.review"))
const canHandoff = computed(() => permissions.value.includes("leads.handoff"))
const canRead = computed(() => permissions.value.includes("leads.read"))

const detailQuery = useQuery({
  queryKey: computed(() => leadKeys.detail(props.organizationId, props.candidateId ?? "")),
  queryFn: ({ signal }) => getLeadCandidate(props.candidateId!, { signal }),
  enabled: computed(() => props.open && Boolean(props.organizationId && props.candidateId) && canRead.value),
  retry: false,
})
const detail = computed(() => detailQuery.data.value)
const permittedActions = computed(() => new Set(detail.value?.permitted_actions ?? []))
const usableEvidence = computed(() => (detail.value?.evidence ?? []).filter((item) => (
  item.availability === "AVAILABLE" && item.original_text.trim().length > 0
)))
const reviewActions = computed(() => ([
  { action: "CONFIRM" as const, label: "确认值得跟进" },
  { action: "CORRECT" as const, label: "纠正信息" },
  { action: "DISMISS" as const, label: "暂不跟进" },
  { action: "REOPEN" as const, label: "重新打开" },
  { action: "REQUEST_MORE_EVIDENCE" as const, label: "请求更多证据" },
].filter((item) => canReview.value && permittedActions.value.has(item.action))))
const handoffEligible = computed(() => ["REVIEWED", "READY_FOR_HANDOFF"].includes(detail.value?.status ?? ""))
// This stays false until a separately tested backend capability endpoint reports a real connector.
const connectorConfigured = false

function stringField(record: unknown, field: string): string {
  if (!record || typeof record !== "object") return ""
  const value = (record as Record<string, unknown>)[field]
  return typeof value === "string" ? value : ""
}

const companyName = computed(() => stringField(detail.value?.company, "name"))
const companyDomain = computed(() => stringField(detail.value?.company, "domain"))
const countryHint = computed(() => stringField(detail.value?.company, "country_hint"))
const insight = computed(() => detail.value?.latest_insight ?? null)
const evidenceSufficient = computed(() => {
  const gates = insight.value?.gates
  if (!gates || typeof gates !== "object") return null
  const values = Object.values(gates)
  if (!values.length || values.some((value) => typeof value !== "boolean")) return null
  return values.every(Boolean)
})
const reviewCorrection = computed<CompanyCorrection>(() => {
  const correction: CompanyCorrection = {}
  if (correctedFields.value.has("company_name")) correction.company_name = correctedName.value
  if (correctedFields.value.has("company_domain")) correction.company_domain = correctedDomain.value
  if (correctedFields.value.has("country_hint")) correction.country_hint = correctedCountry.value
  return correction
})
const selectedActionAllowed = computed(() => Boolean(
  selectedAction.value && permittedActions.value.has(selectedAction.value),
))
const canSubmitReview = computed(() => Boolean(selectedAction.value && reason.value.trim())
  && (selectedAction.value !== "CORRECT" || Object.keys(reviewCorrection.value).length > 0)
  && canReview.value
  && selectedActionAllowed.value
  && ["idle", "ready"].includes(recoveryState.value)
  && !detailQuery.isFetching.value
  && !submitting.value)
const canStartAnalysis = computed(() => canAnalyze.value
  && permittedActions.value.has("ANALYZE")
  && usableEvidence.value.length > 0
  && ["idle", "ready"].includes(recoveryState.value)
  && !detailQuery.isFetching.value
  && !analyzing.value)
const showVersionReviewRetry = computed(() => selectedAction.value !== null
  && ["ready", "unavailable"].includes(recoveryState.value))

function freshKey(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID()
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function keyForReview(version: number, correction: CompanyCorrection | undefined): string {
  const signature = JSON.stringify([
    props.organizationId, props.candidateId, selectedAction.value, version, reason.value, correction ?? null,
  ])
  if (signature !== reviewKeySignature) {
    reviewKeySignature = signature
    reviewKey = freshKey("lead-review")
  }
  return reviewKey
}

function keyForAnalysis(version: number, evidenceIds: readonly string[]): string {
  const signature = JSON.stringify([props.organizationId, props.candidateId, version, evidenceIds])
  if (signature !== analyzeKeySignature) {
    analyzeKeySignature = signature
    analyzeKey = freshKey("lead-analysis")
  }
  return analyzeKey
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.userMessage : fallback
}

function clearPolling(): void {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = undefined
}

function resetTransient(): void {
  session += 1
  clearPolling()
  selectedAction.value = null
  reason.value = ""
  correctedName.value = ""
  correctedDomain.value = ""
  correctedCountry.value = ""
  correctedFields.value = new Set()
  message.value = ""
  alert.value = ""
  recoveryState.value = "idle"
  submitting.value = false
  analyzing.value = false
  activeJobId.value = null
  handoffOpen.value = false
  reviewOpener = null
  reviewOpenerLabel = ""
  reviewKeySignature = ""
  reviewKey = ""
  analyzeKeySignature = ""
  analyzeKey = ""
}

function isCurrent(token: number, organizationId: string, candidateId: string): boolean {
  return props.open && session === token && props.organizationId === organizationId && props.candidateId === candidateId
}

async function invalidateMutationScopes(organizationId: string, candidateId: string): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: [...leadKeys.all(organizationId), "list"] }),
    queryClient.invalidateQueries({ queryKey: leadKeys.detail(organizationId, candidateId) }),
    queryClient.invalidateQueries({ queryKey: leadKeys.jobs(organizationId) }),
  ])
}

function closeDialog(): void {
  resetTransient()
  emit("close")
}

function startReview(action: ReviewAction, event?: MouseEvent): void {
  if (!canReview.value || !permittedActions.value.has(action)
    || submitting.value || analyzing.value || detailQuery.isFetching.value) return
  selectedAction.value = action
  reason.value = ""
  correctedName.value = companyName.value
  correctedDomain.value = companyDomain.value
  correctedCountry.value = countryHint.value
  correctedFields.value = new Set()
  message.value = ""
  alert.value = ""
  recoveryState.value = "idle"
  reviewKeySignature = ""
  reviewKey = ""
  reviewOpener = event?.currentTarget instanceof HTMLElement ? event.currentTarget : null
  reviewOpenerLabel = reviewActions.value.find((item) => item.action === action)?.label ?? ""
  void nextTick(() => reviewHeading.value?.focus())
}

function restoreReviewFocus(opener: HTMLElement | null, label: string): void {
  if (opener?.isConnected) {
    opener.focus()
    return
  }
  const availableActions = [...(decisionSection.value?.querySelectorAll<HTMLButtonElement>("button") ?? [])]
    .filter((button) => !button.disabled)
  const replacement = availableActions.find((button) => button.textContent?.trim() === label)
    ?? availableActions[0]
    ?? decisionHeading.value
    ?? document.getElementById("lead-detail-title")
  replacement?.focus()
}

function cancelReview(): void {
  const opener = reviewOpener
  const openerLabel = reviewOpenerLabel
  selectedAction.value = null
  reason.value = ""
  recoveryState.value = "idle"
  alert.value = ""
  reviewOpener = null
  reviewOpenerLabel = ""
  void nextTick(() => restoreReviewFocus(opener, openerLabel))
}

function focusHandoffHeading(): void {
  handoffRegion.value?.querySelector<HTMLElement>("#lead-handoff-title")?.focus()
}

function openHandoff(): void {
  if (!canHandoff.value || !handoffEligible.value || !detail.value) return
  handoffOpen.value = true
  void nextTick(focusHandoffHeading)
}

function closeHandoff(): void {
  handoffOpen.value = false
  void nextTick(() => (crmHandoffButton.value ?? document.getElementById("lead-detail-title"))?.focus())
}

function restoreSafeDetailFocus(): void {
  void nextTick(() => document.getElementById("lead-detail-title")?.focus())
}

function handoffKeydown(event: KeyboardEvent): void {
  if (event.key !== "Escape") return
  event.preventDefault()
  event.stopPropagation()
  closeHandoff()
}

function handoffRequested(): void {
  // Event contract only. No connector mutation exists until backend capability discovery is implemented.
}

function markCorrected(field: keyof CompanyCorrection): void {
  correctedFields.value = new Set([...correctedFields.value, field])
}

function confirmationLabel(action: ReviewAction): string {
  return ({
    CONFIRM: "确认值得跟进",
    CORRECT: "确认纠正",
    DISMISS: "确认暂不跟进",
    REOPEN: "确认重新打开",
    REQUEST_MORE_EVIDENCE: "确认请求更多证据",
  })[action]
}

async function refetchLatestAfterConflict(token: number, organizationId: string, candidateId: string): Promise<boolean> {
  const refreshed = await detailQuery.refetch()
  if (!isCurrent(token, organizationId, candidateId)) return false
  return !refreshed.error && Boolean(refreshed.data)
}

function classifiedConflictMessage(error: ApiError): string {
  return [error.userMessage, error.recoveryAction].filter(Boolean).join(" ")
}

async function submitReview(): Promise<void> {
  const current = detail.value
  const action = selectedAction.value
  const candidateId = props.candidateId
  const organizationId = props.organizationId
  if (!current || !action || !candidateId || !canSubmitReview.value || !canReview.value) return
  const token = session
  const correction = action === "CORRECT" ? reviewCorrection.value : undefined
  const payload: LeadReviewCreate = {
    action,
    candidate_id: candidateId,
    expected_version: current.version,
    idempotency_key: keyForReview(current.version, correction),
    reason: reason.value,
    ...(correction ? { correction } : {}),
  }
  submitting.value = true
  message.value = ""
  alert.value = ""
  try {
    await createLeadReview(payload)
    await invalidateMutationScopes(organizationId, candidateId)
    if (!isCurrent(token, organizationId, candidateId)) return
    recoveryState.value = "idle"
    selectedAction.value = null
    const opener = reviewOpener
    const openerLabel = reviewOpenerLabel
    reviewOpener = null
    reviewOpenerLabel = ""
    message.value = "处理结果已保存"
    void nextTick(() => restoreReviewFocus(opener, openerLabel))
  } catch (error) {
    if (!isCurrent(token, organizationId, candidateId)) return
    if (error instanceof ApiError && error.status === 409) {
      if (error.code !== "version_conflict") {
        recoveryState.value = "blocked"
        message.value = ""
        alert.value = classifiedConflictMessage(error)
        return
      }
      recoveryState.value = "refreshing"
      const refreshed = await refetchLatestAfterConflict(token, organizationId, candidateId)
      if (!isCurrent(token, organizationId, candidateId)) return
      if (!refreshed) {
        recoveryState.value = "unavailable"
        alert.value = "最新机会版本没有加载成功，请重新加载后再提交。"
        return
      }
      message.value = "另一位同事刚刚保存了处理结果"
      recoveryState.value = selectedActionAllowed.value ? "ready" : "unavailable"
    } else {
      alert.value = errorMessage(error, "处理结果没有保存，请检查后重试。")
    }
  } finally {
    if (isCurrent(token, organizationId, candidateId)) submitting.value = false
  }
}

async function pollAnalysis(jobId: string, token: number, organizationId: string, candidateId: string): Promise<void> {
  if (!isCurrent(token, organizationId, candidateId)) return
  try {
    const job = await queryClient.fetchQuery({
      queryKey: leadKeys.job(organizationId, jobId),
      queryFn: ({ signal }) => getJob(jobId, { signal }),
      retry: false,
      staleTime: 0,
    })
    if (!isCurrent(token, organizationId, candidateId)) return
    if (isActiveImportJob(job.status)) {
      const retryNotice = ordinaryJobProgress(job)
      message.value = (job as { next_retry_at?: unknown }).next_retry_at
        ? `${retryNotice.message} ${retryNotice.recovery}`
        : job.status === "RUNNING" ? "正在分析公开证据…" : "分析任务正在排队…"
      pollTimer = setTimeout(() => { void pollAnalysis(jobId, token, organizationId, candidateId) }, 1_000)
      return
    }
    analyzing.value = false
    if (job.status === "SUCCEEDED") {
      message.value = "分析已完成"
      await invalidateMutationScopes(organizationId, candidateId)
    } else {
      const notice = ordinaryJobProgress(job)
      alert.value = `${notice.message} ${notice.recovery}`
    }
  } catch (error) {
    if (!isCurrent(token, organizationId, candidateId)) return
    analyzing.value = false
    alert.value = errorMessage(error, "分析状态没有加载成功，请稍后重试。")
  }
}

async function startAnalysis(): Promise<void> {
  const current = detail.value
  const candidateId = props.candidateId
  const organizationId = props.organizationId
  if (!current || !candidateId || !canStartAnalysis.value) return
  const evidenceIds = usableEvidence.value.map((item) => item.id)
  if (!evidenceIds.length) {
    alert.value = "当前没有可供分析的公开证据。"
    return
  }
  const token = session
  analyzing.value = true
  alert.value = ""
  message.value = "正在提交分析…"
  try {
    const accepted = await analyzeLeadCandidate(candidateId, {
      evidence_ids: evidenceIds,
      expected_version: current.version,
      idempotency_key: keyForAnalysis(current.version, evidenceIds),
    })
    await invalidateMutationScopes(organizationId, candidateId)
    if (!isCurrent(token, organizationId, candidateId)) return
    recoveryState.value = "idle"
    activeJobId.value = accepted.job_id
    await pollAnalysis(accepted.job_id, token, organizationId, candidateId)
  } catch (error) {
    if (!isCurrent(token, organizationId, candidateId)) return
    analyzing.value = false
    if (error instanceof ApiError && error.status === 409) {
      if (error.code !== "version_conflict") {
        recoveryState.value = "blocked"
        message.value = ""
        alert.value = classifiedConflictMessage(error)
        return
      }
      recoveryState.value = "refreshing"
      const refreshed = await refetchLatestAfterConflict(token, organizationId, candidateId)
      if (!isCurrent(token, organizationId, candidateId)) return
      if (!refreshed) {
        recoveryState.value = "unavailable"
        message.value = ""
        alert.value = "最新机会版本没有加载成功，请重新加载后再分析。"
        return
      }
      if (!permittedActions.value.has("ANALYZE") || !usableEvidence.value.length) {
        recoveryState.value = "unavailable"
        message.value = ""
        alert.value = "最新状态不再允许分析，请重新加载机会后选择可用操作。"
        return
      }
      recoveryState.value = "ready"
      message.value = "另一位同事刚刚保存了处理结果"
    } else {
      alert.value = errorMessage(error, "分析没有开始，请检查后重试。")
    }
  }
}

function explanationText(value: unknown): string {
  if (typeof value === "string" && value.trim()) return value.trim()
  if (value && typeof value === "object") {
    for (const key of ["summary", "reason", "text"]) {
      const text = (value as Record<string, unknown>)[key]
      if (typeof text === "string" && text.trim()) return text.trim()
    }
  }
  return "AI 尚未给出可展示的判断说明。"
}

function valueLabel(band: string | undefined): string {
  return ({ HIGH: "高价值机会", WATCH: "值得关注", OBSERVE: "继续观察", LOW: "当前价值较低" } as Record<string, string>)[band ?? ""] ?? "等待判断"
}

function actionLabel(action: string): string {
  return ({
    CONFIRM: "确认值得跟进", CORRECT: "纠正信息", DISMISS: "暂不跟进", REOPEN: "重新打开",
    REQUEST_MORE_EVIDENCE: "请求更多证据",
  } as Record<string, string>)[action] ?? action
}

function evidenceAvailabilityText(availability: string, originalText: string): string {
  if (availability === "REDACTED_BY_RETENTION") return "内容已按保留期限移除"
  if (availability === "SOURCE_UNAVAILABLE") return "公开来源当前不可用"
  if (!originalText.trim()) return "公开原文为空，当前不能用于分析"
  return ""
}

function evidenceIsUsable(availability: string, originalText: string): boolean {
  return availability === "AVAILABLE" && originalText.trim().length > 0
}

function auditJson(value: unknown): string {
  if (value === null || value === undefined) return "无"
  try { return JSON.stringify(value, null, 2) } catch { return "无法显示" }
}

const dimensionLabels: Record<string, string> = {
  intent: "购买意向",
  company_fit: "公司匹配",
  specificity: "需求明确度",
  capability_fit: "能力匹配",
  recency: "时效性",
}

const auditKeyLabels: Record<string, string> = {
  ai_run_id: "分析记录编号",
  status: "运行状态",
  prompt_code: "分析模板",
  prompt_version: "模板版本",
  model: "分析模型",
  provider: "服务提供方",
  started_at: "开始时间",
  finished_at: "完成时间",
  input_snapshot: "输入摘要",
  output_json: "输出摘要",
}

function dimensionLabel(name: string): string {
  return dimensionLabels[name] ?? "其他指标"
}

function localizedAuditJson(value: unknown): string {
  let unknownKeyIndex = 0

  function localizeKeys(current: unknown): unknown {
    if (Array.isArray(current)) return current.map(localizeKeys)
    if (!current || typeof current !== "object") return current

    return Object.fromEntries(Object.entries(current as Record<string, unknown>).map(([key, nestedValue]) => {
      const label = auditKeyLabels[key] ?? `未识别字段 ${++unknownKeyIndex}`
      return [label, localizeKeys(nestedValue)]
    }))
  }

  return auditJson(localizeKeys(value))
}

watch(() => [props.open, props.organizationId, props.candidateId] as const, (current, previous) => {
  const wasInHandoff = handoffOpen.value
  if (previous?.[1] && previous[2]) {
    void queryClient.cancelQueries({ queryKey: leadKeys.detail(previous[1], previous[2]), exact: true })
    void queryClient.cancelQueries({ queryKey: leadKeys.jobs(previous[1]) })
  }
  if (!previous || current.some((value, index) => value !== previous[index])) {
    resetTransient()
    if (wasInHandoff && current[0]) restoreSafeDetailFocus()
  }
}, { immediate: true, flush: "sync" })

watch(canRead, (current, previous) => {
  if (!previous || current) return
  const organizationId = props.organizationId
  const candidateId = props.candidateId
  resetTransient()
  if (organizationId && candidateId) {
    void queryClient.cancelQueries({ queryKey: leadKeys.detail(organizationId, candidateId), exact: true })
  }
  if (organizationId) void queryClient.cancelQueries({ queryKey: leadKeys.jobs(organizationId) })
}, { flush: "sync" })

watch(canHandoff, (current) => {
  if (!current && handoffOpen.value) {
    handoffOpen.value = false
    restoreSafeDetailFocus()
  }
}, { flush: "sync" })

onBeforeUnmount(() => {
  const organizationId = props.organizationId
  const candidateId = props.candidateId
  resetTransient()
  if (organizationId && candidateId) void queryClient.cancelQueries({ queryKey: leadKeys.detail(organizationId, candidateId), exact: true })
  if (organizationId) void queryClient.cancelQueries({ queryKey: leadKeys.jobs(organizationId) })
})
</script>

<template>
  <OperationModal v-if="open" title="机会依据" title-id="lead-detail-title" @close="closeDialog">
    <article class="lead-detail" @keydown="handoffOpen ? handoffKeydown($event) : undefined">
      <header class="dialog-header">
        <p class="eyebrow">{{ handoffOpen ? "本地导出" : "证据优先" }}</p>
        <button type="button" :aria-label="handoffOpen ? '返回机会依据' : '关闭机会依据'" @click="handoffOpen ? closeHandoff() : closeDialog()">×</button>
      </header>
      <p class="live-message" role="status" aria-live="polite">{{ message }}</p>
      <p v-if="alert" class="form-alert" role="alert">{{ alert }}</p>

      <section v-if="handoffOpen && detail" ref="handoffRegion" class="handoff-subview">
        <LeadHandoffPanel
          :detail="detail"
          :can-handoff="canHandoff"
          :connector-configured="connectorConfigured"
          @close="closeHandoff"
          @handoff="handoffRequested"
        />
      </section>
      <p v-else-if="!canRead" class="state-panel" role="status">当前账号不能查看机会依据</p>
      <p v-else-if="detailQuery.isPending.value && !detail" role="status" aria-live="polite">正在加载机会依据…</p>
      <section v-else-if="detailQuery.isError.value && !detail" class="state-panel" role="alert">
        <h3>机会依据没有加载成功</h3>
        <button type="button" @click="detailQuery.refetch()">重新加载机会依据</button>
      </section>
      <template v-else-if="detail">
        <section class="detail-section summary-section" aria-labelledby="opportunity-summary-title">
          <h3 id="opportunity-summary-title">AI 判断</h3>
          <dl class="identity-grid">
            <div><dt>公司名称</dt><dd>{{ companyName || "未知" }} <span class="pending-tag">待确认</span></dd></div>
            <div><dt>公开域名</dt><dd>{{ companyDomain || "未知" }} <span class="pending-tag">待确认</span></dd></div>
            <div><dt>国家或地区</dt><dd>{{ countryHint || "未知" }} <span class="pending-tag">待确认</span></dd></div>
          </dl>
          <div class="decision-signals">
            <div><span>机会价值</span><strong>{{ valueLabel(insight?.score_band) }}</strong><small v-if="insight">评分 {{ insight.score }}</small></div>
            <div><span>证据充分度</span><strong>{{ evidenceSufficient === true ? "证据已达到判断门槛" : evidenceSufficient === false ? "证据还不够" : "等待分析证据" }}</strong></div>
          </div>
        </section>

        <section class="detail-section" aria-labelledby="ai-explanation-title">
          <h3 id="ai-explanation-title">判断理由</h3>
          <p>{{ explanationText(insight?.explanation) }}</p>
          <h4 id="match-title">需求与能力匹配</h4>
          <p v-if="!detail.requirements.length">还没有可核对的需求与能力匹配。</p>
          <article v-for="requirement in detail.requirements" :key="requirement.id" class="match-card">
            <div><span>推断需求</span><strong>{{ requirement.requirement_label }}</strong> <em class="pending-tag">待确认</em></div>
            <p v-if="requirement.extracted_value">提取值：{{ requirement.extracted_value }} {{ requirement.unit }}</p>
            <div><span>能力匹配</span><strong>{{ requirement.capability_label || "尚未匹配" }}</strong> <em class="pending-tag">待确认</em></div>
          </article>
        </section>

        <section class="detail-section" aria-labelledby="original-evidence-title">
          <h3 id="original-evidence-title">来源证据</h3>
          <p v-if="!detail.evidence.length">还没有可展示的公开证据。</p>
          <article v-for="item in detail.evidence" :key="item.id" class="evidence-card">
            <div class="evidence-meta"><strong>{{ ordinaryPlatform(item.platform) }}</strong><span>{{ item.language || "语言未知" }}</span></div>
            <p v-if="!evidenceIsUsable(item.availability, item.original_text)" class="evidence-status">
              {{ evidenceAvailabilityText(item.availability, item.original_text) }}
            </p>
            <template v-else>
              <blockquote>{{ item.original_text }}</blockquote>
              <div v-if="item.translated_text" class="translation"><h4>翻译（辅助理解）</h4><p>{{ item.translated_text }}</p></div>
              <a v-if="safePublicHttpUrl(item.source_url)" :href="safePublicHttpUrl(item.source_url)!" target="_blank" rel="noopener noreferrer">打开公开来源</a>
              <span v-else class="unsafe-link">公开来源链接不可用</span>
            </template>
          </article>
        </section>

        <section class="detail-section uncertainty-section" aria-labelledby="uncertainty-title">
          <h3 id="uncertainty-title">不确定项</h3>
          <ul>
            <li>公司名称和公开域名来自公开信息推断，待人工确认。</li>
            <li>需求与能力匹配由 AI 提取，不能替代原始证据。</li>
            <li v-if="evidenceSufficient === false">至少一项证据门槛尚未满足。</li>
          </ul>
        </section>

        <section ref="decisionSection" class="detail-section decision-section" aria-labelledby="human-decision-title">
          <h3 id="human-decision-title" ref="decisionHeading" tabindex="-1">人工决定</h3>
          <div v-if="!selectedAction" class="action-grid">
            <button v-if="canAnalyze && permittedActions.has('ANALYZE')" type="button" :disabled="!canStartAnalysis" @click="startAnalysis">{{ analyzing ? "正在分析…" : recoveryState === "ready" ? "按最新版本重新提交" : "重新分析" }}</button>
            <p v-if="canAnalyze && permittedActions.has('ANALYZE') && !usableEvidence.length" class="handoff-note">没有可用于分析的公开证据。请先补充仍可访问的公开原文。</p>
            <button v-for="item in reviewActions" :key="item.action" type="button" :disabled="submitting || analyzing || detailQuery.isFetching.value" @click="startReview(item.action, $event)">{{ item.label }}</button>
          </div>
          <form v-else class="review-form" @submit.prevent="submitReview">
            <h4 ref="reviewHeading" tabindex="-1">记录人工决定</h4>
            <p v-if="!canReview" class="form-alert">审核权限已撤销，当前处理内容不会提交。</p>
            <p v-else-if="!selectedActionAllowed" class="form-alert">最新状态不再允许“{{ actionLabel(selectedAction) }}”，请保留原因并取消后重新选择。</p>
            <fieldset v-if="selectedAction === 'CORRECT'" :disabled="!canReview || submitting">
              <legend>纠正已推断的公司信息</legend>
              <label>公司名称<input v-model="correctedName" autocomplete="organization" @input="markCorrected('company_name')"></label>
              <label>公开域名<input v-model="correctedDomain" inputmode="url" @input="markCorrected('company_domain')"></label>
              <label>国家或地区<input v-model="correctedCountry" maxlength="255" @input="markCorrected('country_hint')"></label>
              <p>这里只提交后端支持的公司名称、公开域名和国家或地区字段。</p>
            </fieldset>
            <label>处理原因<textarea v-model="reason" rows="4" maxlength="2000" required :disabled="!canReview || submitting"></textarea></label>
            <div class="form-actions">
              <button type="button" :disabled="submitting" @click="cancelReview">取消</button>
              <button v-if="showVersionReviewRetry" class="primary-action" type="submit" :disabled="!canSubmitReview">按最新版本重新提交</button>
              <button v-else class="primary-action" type="submit" :disabled="!canSubmitReview">{{ confirmationLabel(selectedAction) }}</button>
            </div>
          </form>
        </section>

        <section v-if="canHandoff" class="detail-section handoff-section" aria-labelledby="crm-export-title">
          <h3 id="crm-export-title">CRM 与导出</h3>
          <p v-if="handoffEligible">可下载包含来源证据的本地文件；CRM 连接器尚未配置，不会自动发送客户资料。</p>
          <p v-else>完成人工决定后，可在这里导出资料或查看 CRM 接入方式。</p>
          <button ref="crmHandoffButton" class="primary-action" type="button" :disabled="!handoffEligible" @click="openHandoff">交给 CRM</button>
        </section>

        <details class="detail-section audit-section">
          <summary>高级审计信息</summary>
          <section v-if="insight" aria-labelledby="score-dimensions-title">
            <h4 id="score-dimensions-title">评分维度</h4>
            <dl class="audit-grid"><div v-for="(value, name) in insight.dimensions" :key="name"><dt>{{ dimensionLabel(name) }}</dt><dd>{{ value }}</dd></div></dl>
            <h4>AI 版本</h4>
            <p>洞察版本 {{ insight.version }}</p>
            <pre>{{ localizedAuditJson(insight.ai_audit) }}</pre>
          </section>
          <section aria-labelledby="review-history-title">
            <h4 id="review-history-title">处理历史</h4>
            <p v-if="!detail.review_history.length">还没有人工处理记录。</p>
            <article v-for="review in detail.review_history" :key="review.id" class="history-card">
              <strong>{{ actionLabel(review.action) }}</strong>
              <p>{{ review.reason }}</p>
              <pre v-if="review.correction !== null">{{ auditJson(review.correction) }}</pre>
              <small>{{ review.created_at }}</small>
            </article>
          </section>
        </details>
      </template>
    </article>
  </OperationModal>
</template>

<style scoped>
:deep(.operation-backdrop){place-items:stretch end;padding:0}:deep(.operation-dialog){box-sizing:border-box;width:min(46rem,52vw);max-height:100vh;border-radius:1rem 0 0 1rem}.lead-detail{display:grid;gap:1rem}.dialog-header,.evidence-meta,.form-actions{display:flex;align-items:center;justify-content:space-between;gap:1rem}.dialog-header .eyebrow,.live-message{margin:0}.live-message:empty{display:none}.detail-section{padding:1rem;border:1px solid var(--sg-line,#d8dee8);border-radius:.8rem;background:#fff}.detail-section h3{margin-top:0}.identity-grid,.audit-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.7rem}.identity-grid div,.audit-grid div{padding:.65rem;border-radius:.6rem;background:var(--sg-canvas,#f6f8fa)}dt,.detail-section span{color:var(--sg-muted,#536273)}dd{margin:.25rem 0 0;font-weight:700}.pending-tag{display:inline-flex;padding:.15rem .45rem;border-radius:999px;background:#fff4d6;color:#805400;font-size:.75rem;font-style:normal;font-weight:800}.decision-signals{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-top:1rem}.decision-signals>div{display:grid;gap:.25rem;padding:.8rem;border-left:4px solid var(--sg-brand,#005ba8);background:var(--sg-canvas,#f6f8fa)}.decision-signals>div+div{border-left-color:#c17d16}.evidence-card,.match-card,.history-card{display:grid;gap:.6rem;padding:.85rem;border:1px solid var(--sg-line,#d8dee8);border-radius:.7rem}.evidence-card+.evidence-card,.match-card+.match-card,.history-card+.history-card{margin-top:.75rem}blockquote{margin:.2rem 0;padding:.7rem;border-left:4px solid var(--sg-brand,#005ba8);background:#f5f9fd;white-space:pre-wrap}.translation h4,.translation p{margin:.25rem 0}.unsafe-link{font-weight:700}.uncertainty-section{background:#fffaf0}.action-grid,.form-actions{display:flex;flex-wrap:wrap;gap:.7rem}.handoff-note{flex-basis:100%;margin:0;color:var(--sg-muted,#536273)}.review-form,.review-form fieldset{display:grid;gap:.8rem}.review-form label{display:grid;gap:.35rem}.review-form input,.review-form textarea{box-sizing:border-box;width:100%}.form-actions{justify-content:flex-end}.primary-action{border-color:var(--sg-brand,#005ba8);background:var(--sg-brand,#005ba8);color:#fff}.form-alert{padding:.75rem;border-radius:.6rem;background:#fff0ed;color:#79291d}.audit-section summary{cursor:pointer;font-weight:800}.audit-section section{margin-top:1rem}.audit-section pre{max-width:100%;overflow:auto;padding:.7rem;border-radius:.5rem;background:#16202b;color:#f5f7fa;white-space:pre-wrap;word-break:break-word}.state-panel{text-align:center}@media(max-width:900px){:deep(.operation-dialog){width:100%;border-radius:0}}@media(max-width:600px){.identity-grid,.decision-signals,.audit-grid{grid-template-columns:1fr}.dialog-header{align-items:flex-start}.action-grid,.form-actions{display:grid;grid-template-columns:1fr}.action-grid button,.form-actions button{width:100%}}
</style>
