<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, ref, watchEffect } from "vue"

import {
  approveChannelPackage,
  approveAllChannelPackages,
  authorizePlatformConnection,
  confirmPlatformConnection,
  createPublishBatch,
  disconnectPlatformConnection,
  exportChannelPackage,
  exportFourChannelPackage,
  growthQueryKeys,
  growthWorkspaceQueryOptions,
  getPlatformConnectionSession,
  retryFailedPublishBatch,
  type ChannelPackage,
  type ManualPackageExport,
  type PlatformConnection,
  type PlatformConnectionCandidate,
  type PublishBatch,
} from "./api"

const queryClient = useQueryClient()
const workspaceQuery = useQuery(growthWorkspaceQueryOptions())
const activeMarkets = computed(() => (workspaceQuery.data.value?.market_pilots?.markets ?? [])
  .filter(market => market.status === "ACTIVE_MARKET" && !market.is_demo))
const activeMarketLabel = computed(() => activeMarkets.value.length
  ? `${activeMarkets.value.map(market => market.country_label).join(" + ")} · 当前试点`
  : "尚未选择市场")
const activeMarketIndustries = computed(() => {
  const industries = [...new Set(activeMarkets.value.flatMap(market => market.suitable_industries ?? []))]
  return industries.length ? `${industries.slice(0, 3).join("、")}相关企业` : "尚未形成客户画像"
})
const validationPeriodLabel = computed(() => {
  if (!activeMarkets.value.length) return "尚未设置验证周期"
  const weeks = workspaceQuery.data.value?.market_pilots?.validation_goals.weeks
  return typeof weeks === "number" && weeks > 0 ? `${weeks} 周市场验证` : "尚未设置验证周期"
})
const locallyApprovedIds = ref(new Set<string>())
const approvalError = ref("")
const batchReviewConfirmed = ref(false)
const downloadMessage = ref("")
const downloadError = ref("")
const publishBatch = ref<PublishBatch | null>(null)
const publishError = ref("")
const connectionError = ref("")
const connectionMessage = ref("")
const selectedCandidateId = ref("")
const connectionHeading = ref<HTMLElement | null>(null)
const publishKey = ref("")
const publishSignature = ref("")
const publishKeySequence = ref(0)

function initialConnectionSessionId(): string {
  const value = new URL(window.location.href).searchParams.get("connection_session") ?? ""
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
    ? value
    : ""
}

const connectionSessionId = ref(initialConnectionSessionId())
const connectionSessionQuery = useQuery({
  queryKey: computed(() => ["platform-connection-session", connectionSessionId.value]),
  queryFn: () => getPlatformConnectionSession(connectionSessionId.value),
  enabled: computed(() => Boolean(connectionSessionId.value)),
  retry: false,
})
const activePackage = computed(() => packageFor("TIKTOK"))
const packageTitle = computed(() => String(activePackage.value?.payload.title ?? ""))
function payloadText(channelPackage: ChannelPackage | undefined, field: string, maxLength = 2_000): string {
  const value = channelPackage?.payload[field]
  return typeof value === "string" ? value.trim().slice(0, maxLength) : ""
}
function payloadList(channelPackage: ChannelPackage | undefined, field: string): string[] {
  const value = channelPackage?.payload[field]
  if (!Array.isArray(value)) return []
  return value.slice(0, 50).flatMap(item => (
    typeof item === "string" && item.trim() ? [item.trim().slice(0, 500)] : []
  ))
}
const tiktokFormatLabel = computed(() => {
  if (!activePackage.value) return "格式待准备"
  const duration = activePackage.value.payload.duration_seconds
  const aspectRatio = payloadText(activePackage.value, "aspect_ratio", 16)
  return `${typeof duration === "number" ? `${duration} 秒` : "时长待补全"} · ${aspectRatio || "画幅待补全"}`
})
const tiktokScript = computed(() => activePackage.value
  ? payloadText(activePackage.value, "script") || "待补全"
  : "待准备")
const tiktokShots = computed(() => activePackage.value
  ? payloadList(activePackage.value, "shot_list").join(" · ") || "待补全"
  : "待准备")
const tiktokVoiceover = computed(() => activePackage.value
  ? payloadText(activePackage.value, "english_voiceover") || "待补全"
  : "待准备")
const tiktokSubtitles = computed(() => activePackage.value
  ? payloadText(activePackage.value, "chinese_subtitles") || "待补全"
  : "待准备")
const tiktokHashtags = computed(() => activePackage.value
  ? payloadList(activePackage.value, "hashtags").join(" ") || "待补全"
  : "待人工补充")
const tiktokCta = computed(() => activePackage.value
  ? payloadText(activePackage.value, "cta") || "待补全"
  : "待准备")
const tiktokUtm = computed(() => activePackage.value
  ? payloadText(activePackage.value, "utm") || "待补全"
  : "待准备")
function packageFor(channel: string): ChannelPackage | undefined {
  return [...(workspaceQuery.data.value?.channel_packages ?? [])]
    .filter(item => item.channel === channel && !item.is_demo)
    .sort((left, right) => {
      const sourcePriority = Number(Boolean(right.source_platform_content_id))
        - Number(Boolean(left.source_platform_content_id))
      return sourcePriority || right.created_at.localeCompare(left.created_at)
    })[0]
}
type PackageFactEvidence = {
  id: string
  fieldName: string
  value: string
  sourceFilename: string
  sourcePage: number | null
  sourceExcerpt: string
}
function safePackageText(value: unknown, maxLength: number): string {
  return typeof value === "string" ? value.trim().slice(0, maxLength) : ""
}
function packageFactEvidence(channelPackage: ChannelPackage | undefined): PackageFactEvidence[] {
  const raw = channelPackage?.payload.verified_fact_evidence
  if (!Array.isArray(raw)) return []
  return raw.slice(0, 50).flatMap((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return []
    const fact = entry as Record<string, unknown>
    const id = safePackageText(fact.fact_id, 36)
    const fieldName = safePackageText(fact.field_name, 100)
    const value = safePackageText(fact.value, 500)
    const sourceFilename = safePackageText(fact.source_filename, 255)
    const sourceExcerpt = safePackageText(fact.source_excerpt, 500)
    const sourcePage = typeof fact.source_page === "number" && Number.isSafeInteger(fact.source_page)
      && fact.source_page > 0 ? fact.source_page : null
    if (!id || !fieldName || !value || !sourceFilename || !sourceExcerpt) return []
    if (fact.is_demo === true) return []
    return [{ id, fieldName, value, sourceFilename, sourcePage, sourceExcerpt }]
  })
}
function isApproved(channelPackage: ChannelPackage | undefined): boolean {
  return Boolean(channelPackage && (
    channelPackage.status === "APPROVED" || locallyApprovedIds.value.has(channelPackage.id)
  ))
}
const approved = computed(() => activePackage.value
  ? isApproved(activePackage.value)
  : false)
const connectionsByChannel = computed(() => new Map(
  (workspaceQuery.data.value?.connectors ?? []).map(item => [item.channel, item]),
))
const publishChannelCodes = ["LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"] as const
const calendarPackages = computed(() => publishChannelCodes
  .map(channel => packageFor(channel))
  .filter((channelPackage): channelPackage is ChannelPackage => Boolean(channelPackage)))
type ChannelReadiness = {
  channel: typeof publishChannelCodes[number]
  label: string
  package: ChannelPackage | undefined
  ready: boolean
  issue: "MISSING_PACKAGE" | "REVIEW" | "FORMAT" | "CONNECTION" | null
}
function channelPackageFormatReady(channelPackage: ChannelPackage): boolean {
  if (channelPackage.channel !== "TIKTOK") return true
  const duration = channelPackage.payload.duration_seconds
  return typeof duration === "number" && Number.isInteger(duration)
    && duration >= 15 && duration <= 60 && channelPackage.payload.aspect_ratio === "9:16"
}
const channelReadiness = computed<ChannelReadiness[]>(() => publishChannelCodes.map(channel => {
  const channelPackage = packageFor(channel)
  let label = "缺少内容包"
  let issue: ChannelReadiness["issue"] = "MISSING_PACKAGE"
  if (channelPackage && !isApproved(channelPackage)) { label = "等待内容审核"; issue = "REVIEW" }
  else if (channelPackage && !channelPackageFormatReady(channelPackage)) { label = "发布格式待补全"; issue = "FORMAT" }
  else if (channelPackage && connectionFor(channel)?.status !== "CONNECTED") { label = "账号未连接"; issue = "CONNECTION" }
  else if (channelPackage) { label = "已就绪"; issue = null }
  return { channel, label, package: channelPackage, ready: issue === null, issue }
}))
const pendingReadinessCount = computed(() => channelReadiness.value.filter(item => !item.ready).length)
const allChannelsReady = computed(() => pendingReadinessCount.value === 0)
const hasPublishingPackages = computed(() => channelReadiness.value.some(item => item.package))
const publishingModeSummary = computed(() => {
  const connections = publishChannelCodes.map(channel => connectionFor(channel))
  if (connections.every(connection => connection?.status === "CONNECTED" && connection.mode === "OFFICIAL")) {
    return "官方接口 · 人工确认后发布"
  }
  if (connections.some(connection => connection?.status === "CONNECTED" && connection.mode === "OFFICIAL")) {
    return "混合发布方式 · 以各渠道状态为准"
  }
  return "手工发布包 · 尚未连接官方账号"
})
const publishingRouteSummary = computed(() => {
  const connections = publishChannelCodes.map(channel => connectionFor(channel))
  const officialCount = connections.filter(connection => (
    connection?.status === "CONNECTED" && connection.mode === "OFFICIAL"
  )).length
  const manualCount = publishChannelCodes.length - officialCount
  return `当前路径：官方连接 ${officialCount} 个 · 手工发布包 ${manualCount} 个`
})
const reviewPackages = computed(() => publishChannelCodes
  .map(packageFor)
  .filter((channelPackage): channelPackage is ChannelPackage => Boolean(channelPackage)))
const hasFourReviewPackages = computed(() => reviewPackages.value.length === 4)
const allPackagesApproved = computed(() => hasFourReviewPackages.value
  && reviewPackages.value.every(channelPackage => isApproved(channelPackage)))
const manualExportIssues = computed(() => publishChannelCodes.flatMap(channel => {
  const channelPackage = packageFor(channel)
  if (!channelPackage) return [`${channelLabel(channel)}：缺少内容包`]
  if (!isApproved(channelPackage)) return [`${channelLabel(channel)}：等待人工审核`]
  return []
}))
const eligiblePackages = computed(() => channelReadiness.value
  .filter((item): item is ChannelReadiness & { package: ChannelPackage } => item.ready && Boolean(item.package))
  .map(item => item.package))
const failedPublishItems = computed(() => publishBatch.value?.items
  .filter(item => item.status === "FAILED") ?? [])
const succeededPublishCount = computed(() => publishBatch.value?.items
  .filter(item => item.status === "SUCCEEDED").length ?? 0)
watchEffect(() => {
  const latest = workspaceQuery.data.value?.publish_batches?.find(batch => !batch.is_demo)
  if (!publishBatch.value && latest) publishBatch.value = latest
})
const approveMutation = useMutation({
  mutationFn: approveChannelPackage,
  onSuccess: async (_result, packageId) => {
    locallyApprovedIds.value = new Set([...locallyApprovedIds.value, packageId])
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => { approvalError.value = "内容包暂时无法批准，请稍后重试。" },
})
const approveAllMutation = useMutation({
  mutationFn: (packageIds: string[]) => approveAllChannelPackages(packageIds),
  onSuccess: async () => {
    locallyApprovedIds.value = new Set([
      ...locallyApprovedIds.value,
      ...reviewPackages.value.map(channelPackage => channelPackage.id),
    ])
    batchReviewConfirmed.value = false
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => { approvalError.value = "四渠道内容暂时无法一起批准，请检查内容包后重试。" },
})
const exportMutation = useMutation({ mutationFn: exportChannelPackage })
const exportAllMutation = useMutation({
  mutationFn: (packageIds: string[]) => exportFourChannelPackage(packageIds),
})
const publishMutation = useMutation({
  mutationFn: ({ packageIds, key }: { packageIds: string[], key: string }) => createPublishBatch(packageIds, key),
  onSuccess: result => { publishBatch.value = result },
  onError: () => { publishError.value = "暂时无法提交发布，请稍后重试。" },
})
const retryPublishMutation = useMutation({
  mutationFn: retryFailedPublishBatch,
  onSuccess: result => { publishBatch.value = result },
  onError: () => { publishError.value = "失败渠道暂时无法重试，请稍后再试。" },
})
const connectionMutation = useMutation({
  mutationFn: authorizePlatformConnection,
  onSuccess: result => {
    const destination = new URL(result.authorization_url)
    if (destination.protocol !== "https:") {
      connectionError.value = "账号连接地址无效，请联系管理员。"
      return
    }
    window.location.assign(destination.href)
  },
  onError: () => { connectionError.value = "官方账号连接尚未配置。" },
})
const disconnectMutation = useMutation({
  mutationFn: disconnectPlatformConnection,
  onSuccess: async () => {
    connectionMessage.value = "账号连接已断开；历史内容和效果记录仍然保留。"
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => { connectionError.value = "暂时无法断开账号连接，请稍后重试。" },
})
const confirmConnectionMutation = useMutation({
  mutationFn: confirmPlatformConnection,
  onSuccess: async () => {
    const selected = connectionSessionQuery.data.value?.candidates
      .find(candidate => candidate.candidate_id === selectedCandidateId.value)
    connectionMessage.value = `${selected?.display_name ?? "发布账号"} 已连接。`
    clearConnectionSessionFromUrl()
    connectionSessionId.value = ""
    selectedCandidateId.value = ""
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => { connectionError.value = "账号连接暂时无法完成，请重新连接。" },
})

watchEffect(async () => {
  const candidates = connectionSessionQuery.data.value?.candidates ?? []
  if (!candidates.length) return
  if (!candidates.some(candidate => candidate.candidate_id === selectedCandidateId.value)) {
    selectedCandidateId.value = candidates[0].candidate_id
  }
  await nextTick()
  connectionHeading.value?.focus()
})

function clearConnectionSessionFromUrl(): void {
  const current = new URL(window.location.href)
  current.searchParams.delete("connection_session")
  current.searchParams.delete("connection_status")
  window.history.replaceState({}, "", `${current.pathname}${current.search}${current.hash}`)
}

function cancelConnectionSelection(): void {
  clearConnectionSessionFromUrl()
  connectionSessionId.value = ""
  selectedCandidateId.value = ""
}

async function confirmSelectedConnection(): Promise<void> {
  if (!connectionSessionId.value || !selectedCandidateId.value) return
  connectionError.value = ""
  connectionMessage.value = ""
  await confirmConnectionMutation.mutateAsync({
    sessionId: connectionSessionId.value,
    candidateId: selectedCandidateId.value,
  }).catch(() => undefined)
}

function candidateChannel(candidate: PlatformConnectionCandidate): string {
  return channelLabel(candidate.channel)
}

function connectionFor(channel: string): PlatformConnection | undefined {
  const connection = connectionsByChannel.value.get(channel)
  return connection?.mode === "DEMO_FAKE" ? undefined : connection
}

function connectionDisplay(channel: string): string {
  const connection = connectionFor(channel)
  if (!connection) return "未连接"
  return connection.connection_label
}

function modeLabel(channel: string): string {
  const mode = connectionFor(channel)?.mode
  if (mode === "OFFICIAL") return "官方连接"
  const channelPackage = packageFor(channel)
  if (!channelPackage) return "尚无内容包"
  return "仅发布包"
}

function publishingRouteLabel(channel: string): string {
  const connection = connectionFor(channel)
  if (connection?.status === "CONNECTED" && connection.mode === "OFFICIAL") {
    return "发布方式：官方接口 · 仍需人工确认"
  }
  return "发布方式：手工发布包 · 不会调用平台"
}

function calendarReviewLabel(channelPackage: ChannelPackage): string {
  return isApproved(channelPackage) ? "已审核" : "待审核"
}

function connectionActionLabel(channel: string, channelName: string): string {
  const action = connectionFor(channel)?.recovery_action || "连接"
  const conciseAction = action.endsWith("账号") ? action.slice(0, -2) : action
  return `${conciseAction} ${channelName} 账号`
}

async function connectChannel(channel: PlatformConnection["channel"]): Promise<void> {
  connectionError.value = ""
  await connectionMutation.mutateAsync(channel).catch(() => undefined)
}

async function disconnectChannel(connection: PlatformConnection, label: string): Promise<void> {
  if (!connection.account_id) return
  if (!window.confirm(`确认断开 ${label}？历史内容和效果记录会保留，也不会触发发布。`)) return
  connectionError.value = ""
  await disconnectMutation.mutateAsync(connection.account_id).catch(() => undefined)
}

async function disconnectSocialChannel(channel: PlatformConnection["channel"], label: string): Promise<void> {
  const connection = formalConnection(channel)
  if (connection) await disconnectChannel(connection, label)
}

async function approve(): Promise<void> {
  await approvePackage(activePackage.value)
}

async function approvePackage(channelPackage: ChannelPackage | undefined): Promise<void> {
  approvalError.value = ""
  if (!channelPackage) return
  await approveMutation.mutateAsync(channelPackage.id).catch(() => undefined)
}

async function approveAllPackages(): Promise<void> {
  approvalError.value = ""
  if (!hasFourReviewPackages.value || !batchReviewConfirmed.value || allPackagesApproved.value) return
  await approveAllMutation.mutateAsync(reviewPackages.value.map(channelPackage => channelPackage.id))
    .catch(() => undefined)
}

function saveExport(exported: ManualPackageExport): void {
  const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json;charset=utf-8" })
  if (typeof URL.createObjectURL !== "function") return
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = objectUrl
  anchor.download = exported.filename
  anchor.click()
  URL.revokeObjectURL(objectUrl)
}

function saveBlob(blob: Blob, filename: string): void {
  if (typeof URL.createObjectURL !== "function") return
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = objectUrl
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(objectUrl)
}

async function downloadAllPackages(): Promise<void> {
  downloadMessage.value = ""
  downloadError.value = ""
  if (!allPackagesApproved.value) {
    downloadError.value = "请先补齐并人工批准四个渠道内容。"
    return
  }
  try {
    const exported = await exportAllMutation.mutateAsync(
      reviewPackages.value.map(channelPackage => channelPackage.id),
    )
    saveBlob(exported.blob, exported.filename)
    downloadMessage.value = "四渠道手工发布包已下载；请人工登录平台发布，未触发任何平台请求。"
  } catch {
    downloadError.value = "四渠道发布包暂时无法下载，请检查内容是否仍为最新且已批准。"
  }
}

async function download(): Promise<void> {
  await downloadPackage(activePackage.value)
}

async function downloadPackage(channelPackage: ChannelPackage | undefined): Promise<void> {
  downloadMessage.value = ""
  downloadError.value = ""
  if (!channelPackage) {
    downloadError.value = "当前没有可导出的内容包。"
    return
  }
  try {
    const exported = await exportMutation.mutateAsync(channelPackage.id)
    saveExport(exported)
    downloadMessage.value = `发布包已下载：${exported.filename}。请人工登录平台发布。`
  } catch {
    downloadError.value = "发布包暂时无法下载，请确认内容已批准后重试。"
  }
}

function currentPublishKey(): string {
  const signature = eligiblePackages.value.map(item => item.id).sort().join(":")
  if (!publishKey.value || signature !== publishSignature.value) {
    publishSignature.value = signature
    publishKeySequence.value += 1
    publishKey.value = `growth-${Date.now().toString(36)}-${publishKeySequence.value}`
  }
  return publishKey.value
}

async function publishAll(): Promise<void> {
  publishError.value = ""
  if (!allChannelsReady.value) return
  const packageIds = eligiblePackages.value.map(item => item.id)
  if (!packageIds.length) return
  await publishMutation.mutateAsync({ packageIds, key: currentPublishKey() }).catch(() => undefined)
}

async function focusChannelPackage(channel: ChannelReadiness["channel"]): Promise<void> {
  await nextTick()
  document.getElementById(`channel-package-${channel}`)?.focus()
}

async function retryFailed(): Promise<void> {
  publishError.value = ""
  if (!publishBatch.value) return
  await retryPublishMutation.mutateAsync(publishBatch.value.id).catch(() => undefined)
}

function channelLabel(channel: string): string {
  return ({
    LINKEDIN: "LinkedIn",
    FACEBOOK: "Facebook",
    INSTAGRAM: "Instagram",
    TIKTOK: "TikTok",
    YOUTUBE: "YouTube",
  } as Record<string, string>)[channel] ?? channel
}

const resultTimeFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
})

function formatResultTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "时间不可用"
  return resultTimeFormatter.format(date).replace(",", "")
}

const channels: Array<{
  code: PlatformConnection["channel"]
  actionName: string
  name: string
  format: string
}> = [
  { code: "LINKEDIN", actionName: "LinkedIn", name: "LinkedIn Company Page", format: "英文专业短帖 + 中文对照" },
  { code: "FACEBOOK", actionName: "Facebook", name: "Facebook Page", format: "案例图文 + CTA" },
  { code: "INSTAGRAM", actionName: "Instagram", name: "Instagram Business", format: "轮播提纲 + Reels 文案" },
]
const preparedStandardChannels = computed(() => channels.filter(channel => Boolean(packageFor(channel.code))))
const socialChannels: Array<{
  code: PlatformConnection["channel"]
  name: string
  actionName: string
}> = [
  { code: "FACEBOOK", name: "Facebook Page", actionName: "Facebook" },
  { code: "INSTAGRAM", name: "Instagram Business", actionName: "Instagram" },
  { code: "LINKEDIN", name: "LinkedIn Company Page", actionName: "LinkedIn" },
  { code: "TIKTOK", name: "TikTok", actionName: "TikTok" },
  { code: "YOUTUBE", name: "YouTube", actionName: "YouTube" },
]

function formalConnection(channel: PlatformConnection["channel"]): PlatformConnection | undefined {
  const connection = connectionsByChannel.value.get(channel)
  return connection?.mode === "DEMO_FAKE" ? undefined : connection
}

function socialStatus(channel: PlatformConnection["channel"]): string {
  const connection = formalConnection(channel)
  return connection?.connection_label || "未连接"
}

function socialCapability(channel: PlatformConnection["channel"]): string {
  const connection = formalConnection(channel)
  if (channel === "TIKTOK" && connection?.publication_mode === "PRIVATE_ONLY") return "仅私密发布"
  if (channel === "YOUTUBE") return "可上传草稿"
  if (connection?.status === "CONNECTED") return "可准备发布，仍需人工确认"
  return "当前不会向平台发送内容"
}
</script>

<template>
  <div class="growth-page">
    <header class="growth-hero">
      <div><p class="eyebrow">推广</p><h1>推广计划与内容包</h1><p>从已验证的公司事实创建内容；人工批准后，再下载发布包或提交到已连接渠道。</p></div>
      <span class="fake-label">{{ hasPublishingPackages ? `${calendarPackages.length} 个正式内容包` : "尚无内容包" }}</span>
    </header>

    <section v-if="connectionSessionId" class="growth-card account-picker" aria-labelledby="account-picker-title">
      <p v-if="connectionSessionQuery.isPending.value">正在读取可发布账号…</p>
      <div v-else-if="connectionSessionQuery.isError.value" class="account-picker-error">
        <p role="alert">连接信息已失效，请重新连接账号。</p>
        <button class="button button-secondary" type="button" @click="cancelConnectionSelection">关闭</button>
      </div>
      <template v-else-if="connectionSessionQuery.data.value">
        <div class="growth-heading">
          <div>
            <p class="eyebrow">账号连接</p>
            <h2 id="account-picker-title" ref="connectionHeading" tabindex="-1">选择要用于发布的账号</h2>
            <p>授权已完成；选择账号后仍需单独点击一键发布。</p>
          </div>
          <span>{{ connectionSessionQuery.data.value.platform_name }}</span>
        </div>
        <fieldset class="account-candidates">
          <legend class="sr-only">可用于发布的账号</legend>
          <label v-for="candidate in connectionSessionQuery.data.value.candidates" :key="candidate.candidate_id">
            <input v-model="selectedCandidateId" type="radio" name="publishing-account" :value="candidate.candidate_id">
            <span>
              <strong>{{ candidate.display_name }}</strong>
              <small>{{ candidateChannel(candidate) }} · {{ candidate.capability_label }}</small>
            </span>
          </label>
        </fieldset>
        <div class="page-actions account-picker-actions">
          <button class="button button-secondary" type="button" @click="cancelConnectionSelection">暂不连接</button>
          <button
            class="button button-primary" type="button"
            :disabled="!selectedCandidateId || confirmConnectionMutation.isPending.value"
            @click="confirmSelectedConnection"
          >
            {{ confirmConnectionMutation.isPending.value ? "正在连接…" : "使用此账号" }}
          </button>
        </div>
      </template>
    </section>
    <p v-if="connectionMessage" role="status" class="approval-status connection-success">{{ connectionMessage }}</p>

    <section class="growth-card plan-summary">
      <div><span>目标市场</span><strong>{{ activeMarketLabel }}</strong></div>
      <div><span>理想客户</span><strong>{{ activeMarketIndustries }}</strong></div>
      <div><span>验证周期</span><strong>{{ validationPeriodLabel }}</strong></div>
      <div><span>审核边界</span><strong>所有内容人工批准后导出</strong></div>
    </section>

    <section class="growth-card social-readiness" aria-label="社媒账号连接状态">
      <div class="growth-heading">
        <div><h2>社媒账号连接</h2><p>连接只激活官方账号边界；任何内容仍需人工批准后才能提交。</p></div>
        <span>5 个渠道</span>
      </div>
      <div class="social-readiness-grid">
        <article v-for="channel in socialChannels" :key="channel.code">
          <div>
            <h3>{{ channel.name }}</h3>
            <span class="connection-state">{{ socialStatus(channel.code) }}</span>
          </div>
          <p>{{ socialCapability(channel.code) }}</p>
          <div class="social-readiness-actions">
            <button
              v-if="formalConnection(channel.code)?.status === 'CONNECTED' && formalConnection(channel.code)?.account_id"
              class="button button-secondary" type="button"
              :disabled="disconnectMutation.isPending.value"
              :aria-label="`断开 ${channel.actionName} 连接`"
              @click="disconnectSocialChannel(channel.code, channel.name)"
            >
              断开连接
            </button>
            <button
              v-else-if="!['WAITING_PLATFORM_REVIEW', 'PRIVATE_ONLY'].includes(formalConnection(channel.code)?.status ?? '')"
              class="button button-secondary" type="button"
              :disabled="connectionMutation.isPending.value"
              :aria-label="connectionActionLabel(channel.code, channel.actionName)"
              @click="connectChannel(channel.code)"
            >
              {{ formalConnection(channel.code)?.status === 'REAUTHORIZATION_REQUIRED' ? '重新授权' : '连接账号' }}
            </button>
            <small v-else>无需在此输入密钥</small>
          </div>
        </article>
      </div>
    </section>

    <section class="growth-card" aria-label="内容日历">
      <div class="growth-heading"><div><h2>内容日历</h2><p>显示当前真实内容包；没有正式排期时不会编造发布日期。</p></div><span>{{ calendarPackages.length }} 个内容包</span></div>
      <div v-if="calendarPackages.length" class="calendar-strip">
        <article v-for="channelPackage in calendarPackages" :key="channelPackage.id">
          <span>待安排</span>
          <strong>内容：{{ String(channelPackage.payload.title ?? "待补充标题") }}</strong>
          <span>{{ channelLabel(channelPackage.channel) }} · {{ calendarReviewLabel(channelPackage) }}</span>
        </article>
      </div>
      <p v-else>还没有可安排的内容包；先从审核中心准备渠道版本。</p>
    </section>

    <section class="growth-card">
      <div class="growth-heading"><div><h2>各渠道内容包</h2><p>先审核内容，再一次提交到所有可用渠道。</p></div><span class="connector-state">{{ publishingModeSummary }}</span></div>
      <div v-if="hasPublishingPackages" class="package-grid">
        <article v-for="channel in preparedStandardChannels" :id="`channel-package-${channel.code}`" :key="channel.name" tabindex="-1" :aria-label="`${channel.name} 内容包`">
          <span class="fake-label">{{ modeLabel(channel.code) }}</span><h3>{{ channel.name }}</h3>
          <div class="channel-connection">
            <span>{{ connectionDisplay(channel.code) }}</span>
            <button
              v-if="connectionFor(channel.code)?.status !== 'CONNECTED'"
              class="button button-secondary" type="button"
              :disabled="connectionMutation.isPending.value"
              :aria-label="connectionActionLabel(channel.code, channel.actionName)"
              @click="connectChannel(channel.code)"
            >
              {{ connectionFor(channel.code)?.recovery_action || "连接账号" }}
            </button>
          </div>
          <p class="publishing-route">{{ publishingRouteLabel(channel.code) }}</p>
          <p class="package-source">{{ String(packageFor(channel.code)?.payload.title ?? channel.format) }}</p>
          <p>{{ channel.format }}</p><strong>手工发布包</strong>
          <details v-if="packageFactEvidence(packageFor(channel.code)).length" class="package-evidence"><summary>查看已验证事实依据</summary><article v-for="fact in packageFactEvidence(packageFor(channel.code))" :key="fact.id"><strong>{{ fact.fieldName }}：{{ fact.value }}</strong><p>{{ fact.sourceFilename }}<template v-if="fact.sourcePage"> · 第 {{ fact.sourcePage }} 页</template></p><blockquote>{{ fact.sourceExcerpt }}</blockquote></article></details>
          <div v-if="packageFor(channel.code)" class="package-actions">
            <button
              class="button button-secondary" type="button"
              :disabled="isApproved(packageFor(channel.code)) || approveMutation.isPending.value"
              :aria-label="`批准 ${channel.actionName} 内容包`"
              @click="approvePackage(packageFor(channel.code))"
            >
              {{ isApproved(packageFor(channel.code)) ? "已批准" : "批准" }}
            </button>
            <button
              v-if="isApproved(packageFor(channel.code))" class="button button-secondary" type="button"
              :disabled="exportMutation.isPending.value" :aria-label="`下载 ${channel.actionName} 发布包`"
              @click="downloadPackage(packageFor(channel.code))"
            >
              下载
            </button>
          </div>
        </article>
        <article v-if="activePackage" id="channel-package-TIKTOK" class="tiktok-package" tabindex="-1" aria-label="TikTok 内容包">
          <span class="fake-label">{{ modeLabel('TIKTOK') }}</span><h3>TikTok</h3>
          <div class="channel-connection">
            <span>{{ connectionDisplay('TIKTOK') }}</span>
            <button
              v-if="connectionFor('TIKTOK')?.status !== 'CONNECTED'"
              class="button button-secondary" type="button"
              :disabled="connectionMutation.isPending.value"
              :aria-label="connectionActionLabel('TIKTOK', 'TikTok')"
              @click="connectChannel('TIKTOK')"
            >
              {{ connectionFor('TIKTOK')?.recovery_action || "连接账号" }}
            </button>
          </div>
          <p class="publishing-route">{{ publishingRouteLabel('TIKTOK') }}</p>
          <p v-if="packageTitle" class="package-source">{{ packageTitle }}</p>
          <p class="package-lead">{{ tiktokFormatLabel }} · 手工发布包 · {{ modeLabel('TIKTOK') }}</p>
          <dl>
            <div><dt>脚本</dt><dd>{{ tiktokScript }}</dd></div>
            <div><dt>分镜</dt><dd>{{ tiktokShots }}</dd></div>
            <div><dt>英文口播</dt><dd>{{ tiktokVoiceover }}</dd></div>
            <div><dt>中文字幕</dt><dd>{{ tiktokSubtitles }}</dd></div>
            <div><dt>标题 / 标签 / CTA</dt><dd>{{ packageTitle || "待补全" }} · {{ tiktokHashtags }} · {{ tiktokCta }}</dd></div>
            <div><dt>归因</dt><dd>UTM：{{ tiktokUtm }}</dd></div>
            <div><dt>回填</dt><dd>发布结果、播放、完播、点击、回复、询盘可手工录入</dd></div>
          </dl>
          <details v-if="packageFactEvidence(activePackage).length" class="package-evidence"><summary>查看已验证事实依据</summary><article v-for="fact in packageFactEvidence(activePackage)" :key="fact.id"><strong>{{ fact.fieldName }}：{{ fact.value }}</strong><p>{{ fact.sourceFilename }}<template v-if="fact.sourcePage"> · 第 {{ fact.sourcePage }} 页</template></p><blockquote>{{ fact.sourceExcerpt }}</blockquote></article></details>
          <div v-if="activePackage" class="package-actions">
            <button
              class="button button-secondary" type="button"
              :disabled="approved || approveMutation.isPending.value" aria-label="批准 TikTok 内容包"
              @click="approve"
            >
              {{ approved ? "已批准" : "批准" }}
            </button>
            <button
              v-if="approved" class="button button-secondary" type="button"
              :disabled="exportMutation.isPending.value" aria-label="下载 TikTok 发布包"
              @click="download"
            >
              下载
            </button>
          </div>
        </article>
      </div>
      <div v-else class="promotion-empty">
        <h3>还没有可审核的渠道内容包</h3>
        <p>请先用已确认的公司和产品事实创建内容，再到审核中心逐个平台核对；空工作区不会生成固定脚本或文案。</p>
        <div class="page-actions">
          <a class="button button-primary" href="/content-factory">创建内容</a>
          <a class="button button-secondary" href="/reviews">进入审核中心</a>
        </div>
      </div>
      <section v-if="hasFourReviewPackages" class="batch-review-panel" aria-label="四渠道内容总审核">
        <div>
          <p class="eyebrow">一次人工总审核</p>
          <h3>{{ allPackagesApproved ? "四个平台内容均已人工批准" : "核对四个平台版本后统一批准" }}</h3>
          <ul>
            <li v-for="channelPackage in reviewPackages" :key="channelPackage.id">
              <strong>{{ channelLabel(channelPackage.channel) }}</strong>
              <span>{{ String(channelPackage.payload.title ?? "待核对内容") }}</span>
            </li>
          </ul>
          <label v-if="!allPackagesApproved" class="batch-review-confirmation">
            <input v-model="batchReviewConfirmed" type="checkbox">
            <span>我已核对四个平台内容与事实证据</span>
          </label>
          <p v-else>批准只记录人工审核，不会发送或请求任何真实平台。</p>
        </div>
        <button
          v-if="!allPackagesApproved" class="button button-primary" type="button"
          :disabled="!batchReviewConfirmed || approveAllMutation.isPending.value"
          aria-label="批准 4 个渠道内容" @click="approveAllPackages"
        >
          {{ approveAllMutation.isPending.value ? "正在批准…" : "批准 4 个渠道内容" }}
        </button>
      </section>
      <section v-if="hasPublishingPackages" class="batch-review-panel manual-export-panel" aria-label="四渠道手工发布包">
        <div>
          <p class="eyebrow">官方接口未就绪时的安全兜底</p>
          <h3>{{ allPackagesApproved ? "四渠道手工发布包可以下载" : `还需处理 ${manualExportIssues.length} 项` }}</h3>
          <ul v-if="manualExportIssues.length">
            <li v-for="issue in manualExportIssues" :key="issue"><span>{{ issue }}</span></li>
          </ul>
          <p v-else>包含四个平台文案、素材引用、UTM 与事实证据；下载不会发布到任何平台。</p>
        </div>
        <button
          class="button button-secondary" type="button"
          :disabled="!allPackagesApproved || exportAllMutation.isPending.value"
          aria-label="下载四渠道手工发布包"
          @click="downloadAllPackages"
        >
          {{ exportAllMutation.isPending.value ? "正在准备…" : "下载四渠道手工发布包" }}
        </button>
      </section>
      <section v-if="hasPublishingPackages" class="publish-panel" aria-label="四渠道发布就绪检查">
        <div>
          <p class="eyebrow">四渠道发布就绪检查</p>
          <h3>{{ allChannelsReady ? '四个渠道均可提交' : `还有 ${pendingReadinessCount} 个渠道需要处理` }}</h3>
          <p>{{ publishingRouteSummary }}</p>
          <ul class="readiness-list">
            <li v-for="item in channelReadiness" :key="item.channel">
              <span>{{ channelLabel(item.channel) }} · {{ item.label }}</span>
              <a
                v-if="item.issue === 'MISSING_PACKAGE' || item.issue === 'FORMAT'"
                class="readiness-action" href="/reviews"
                :aria-label="item.issue === 'FORMAT' ? `补全 ${channelLabel(item.channel)} 发布格式` : `准备 ${channelLabel(item.channel)} 内容包`"
              >{{ item.issue === 'FORMAT' ? '去补全' : '准备内容' }}</a>
              <button
                v-else-if="item.issue === 'REVIEW' || item.issue === 'CONNECTION'"
                class="readiness-action" type="button"
                :aria-label="item.issue === 'REVIEW' ? `审核 ${channelLabel(item.channel)} 内容` : `处理 ${channelLabel(item.channel)} 账号`"
                @click="focusChannelPackage(item.channel)"
              >
                {{ item.issue === 'REVIEW' ? '去审核' : '去连接' }}
              </button>
            </li>
          </ul>
          <p>全部内容须人工批准且账号就绪；未连接官方账号时请下载手工发布包。</p>
        </div>
        <button
          class="button button-primary" type="button"
          :disabled="!allChannelsReady || publishMutation.isPending.value || Boolean(publishBatch)"
          @click="publishAll"
        >
          {{ publishMutation.isPending.value ? "正在提交…" : allChannelsReady ? "一键发布到 4 个渠道" : `还有 ${pendingReadinessCount} 个渠道未就绪` }}
        </button>
      </section>
      <section v-if="publishBatch" class="publish-results" aria-label="发布结果">
        <div class="growth-heading">
          <div><p class="eyebrow">{{ publishBatch.data_label }}</p><h3>渠道发布结果</h3></div>
          <strong v-if="publishBatch.status === 'SUCCEEDED'">
            {{ succeededPublishCount }} 个渠道{{ succeededPublishCount > 1 ? "均" : "" }}已发布成功。
          </strong>
          <strong v-else-if="failedPublishItems.length">
            {{ succeededPublishCount }} 个渠道发布成功，{{ failedPublishItems.length }} 个渠道需要重试。
          </strong>
          <strong v-else>发布请求已受理。</strong>
        </div>
        <ul class="publish-result-list">
          <li v-for="item in publishBatch.items" :key="item.id">
            <span>{{ channelLabel(item.channel) }}</span>
            <div class="publish-result-detail">
              <a
                v-if="item.status === 'SUCCEEDED'" :href="item.external_post_url"
                target="_blank" rel="noreferrer"
                :aria-label="`查看 ${channelLabel(item.channel)} 平台帖子`"
              >发布成功 · 查看平台帖子</a>
              <span v-else>{{ item.recovery_action || "等待发布" }}</span>
              <small>
                <span>结果记录时间：</span>
                <time :datetime="item.updated_at">{{ formatResultTime(item.updated_at) }}</time>
              </small>
            </div>
          </li>
        </ul>
        <button
          v-if="failedPublishItems.length" class="button button-primary" type="button"
          :disabled="retryPublishMutation.isPending.value" @click="retryFailed"
        >
          {{ retryPublishMutation.isPending.value ? "正在重试…" : "重试失败渠道" }}
        </button>
      </section>
      <p v-if="publishError" role="alert" class="approval-status">{{ publishError }}</p>
      <p v-if="connectionError" role="alert" class="approval-status connection-error">{{ connectionError }}</p>
      <div v-if="activePackage" class="approval-row">
        <p>批准后状态：{{ approved ? "等待人工下载或手工发布" : "等待你的审核" }}</p>
        <div class="page-actions">
          <button
            class="button button-primary" type="button"
            :disabled="approved || approveMutation.isPending.value" @click="approve"
          >
            {{ approved ? "已批准" : approveMutation.isPending.value ? "正在保存…" : "批准内容包" }}
          </button>
          <button
            v-if="approved" class="button button-secondary" type="button"
            :disabled="exportMutation.isPending.value" @click="download"
          >
            {{ exportMutation.isPending.value ? "正在准备…" : "下载发布包" }}
          </button>
        </div>
      </div>
      <p v-if="approved" role="status" class="approval-status">已批准，等待人工下载或手工发布；没有触发任何平台请求。</p>
      <p v-if="downloadMessage" role="status" class="approval-status">{{ downloadMessage }}</p>
      <p v-if="downloadError" role="alert" class="approval-status">{{ downloadError }}</p>
      <p v-if="approvalError" role="alert" class="approval-status">{{ approvalError }}</p>
    </section>
  </div>
</template>

<style scoped src="./growth-pages.css"></style>
