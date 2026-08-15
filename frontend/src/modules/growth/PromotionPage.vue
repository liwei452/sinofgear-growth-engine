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

import PromotionPlanSummary from "./PromotionPlanSummary.vue"
import PublishResultsPanel from "./PublishResultsPanel.vue"
import SocialReadinessPanel, { type SocialChannelStatus } from "./SocialReadinessPanel.vue"
import StandardChannelPackageCard from "./StandardChannelPackageCard.vue"
import TikTokPackageReview from "./TikTokPackageReview.vue"
import ChannelPublishPanel, { type ChannelReadiness } from "./ChannelPublishPanel.vue"
import { packageFactEvidence, payloadList, payloadShots, payloadText } from "./packagePayload"

const queryClient = useQueryClient()
const workspaceQuery = useQuery(growthWorkspaceQueryOptions())
async function regeneratePlan(): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
}
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
  ? payloadShots(activePackage.value).join(" / ") || "待补全"
  : "待准备")
const tiktokVoiceover = computed(() => activePackage.value
  ? payloadText(activePackage.value, "voiceover") || payloadText(activePackage.value, "english_voiceover") || "待补全"
  : "待准备")
const tiktokSubtitles = computed(() => activePackage.value
  ? payloadText(activePackage.value, "subtitles") || payloadText(activePackage.value, "chinese_subtitles") || "待补全"
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
const allPackagesApproved = computed(() => reviewPackages.value.length === 4
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
  if (reviewPackages.value.length !== 4 || !batchReviewConfirmed.value || allPackagesApproved.value) return
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

const socialChannelStatuses = computed<SocialChannelStatus[]>(() => socialChannels.map(channel => {
  const connection = formalConnection(channel.code)
  const status = connection?.status ?? ""
  return {
    code: channel.code,
    name: channel.name,
    actionName: channel.actionName,
    status: socialStatus(channel.code),
    capability: socialCapability(channel.code),
    connected: connection?.status === "CONNECTED",
    accountId: connection?.account_id ?? null,
    actionLabel: connectionActionLabel(channel.code, channel.actionName),
    reauthorizationRequired: connection?.status === "REAUTHORIZATION_REQUIRED",
    blocked: ["WAITING_PLATFORM_REVIEW", "PRIVATE_ONLY"].includes(status),
  }
}))
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

    <PromotionPlanSummary
      :plan="workspaceQuery.data.value?.promotion_plan"
      @regenerate="regeneratePlan"
    />

    <SocialReadinessPanel
      :channels="socialChannelStatuses"
      :connecting="connectionMutation.isPending.value"
      :disconnecting="disconnectMutation.isPending.value"
      @connect="connectChannel"
      @disconnect="disconnectSocialChannel"
    />

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
        <StandardChannelPackageCard
          v-for="channel in preparedStandardChannels"
          :key="channel.name"
          :code="channel.code"
          :name="channel.name"
          :action-name="channel.actionName"
          :format="channel.format"
          :mode-label="modeLabel(channel.code)"
          :connection-display="connectionDisplay(channel.code)"
          :connection-connected="connectionFor(channel.code)?.status === 'CONNECTED'"
          :connection-action-label="connectionActionLabel(channel.code, channel.actionName)"
          :recovery-action="connectionFor(channel.code)?.recovery_action || ''"
          :publishing-route-label="publishingRouteLabel(channel.code)"
          :package-title="String(packageFor(channel.code)?.payload.title ?? '')"
          :facts="packageFactEvidence(packageFor(channel.code))"
          :approved="isApproved(packageFor(channel.code))"
          :approving="approveMutation.isPending.value"
          :exporting="exportMutation.isPending.value"
          :connecting="connectionMutation.isPending.value"
          @approve="approvePackage(packageFor(channel.code))"
          @download="downloadPackage(packageFor(channel.code))"
          @connect="connectChannel(channel.code)"
        />
        <TikTokPackageReview
          v-if="activePackage"
          :channel-package="activePackage"
          :approved="approved"
          :mode-label="modeLabel('TIKTOK')"
          :connection-display="connectionDisplay('TIKTOK')"
          :connection-action-label="connectionActionLabel('TIKTOK', 'TikTok')"
          :connection-connected="connectionFor('TIKTOK')?.status === 'CONNECTED'"
          :publishing-route-label="publishingRouteLabel('TIKTOK')"
          :package-title="packageTitle"
          :format-label="tiktokFormatLabel"
          :script="tiktokScript"
          :shots="tiktokShots"
          :voiceover="tiktokVoiceover"
          :subtitles="tiktokSubtitles"
          :hashtags="tiktokHashtags"
          :cta="tiktokCta"
          :utm="tiktokUtm"
          :facts="packageFactEvidence(activePackage)"
          :approving="approveMutation.isPending.value"
          :exporting="exportMutation.isPending.value"
          :connecting="connectionMutation.isPending.value"
          @approve="approve"
          @download="download"
          @connect="connectChannel('TIKTOK')"
        />
      </div>
      <div v-else class="promotion-empty">
        <h3>还没有可审核的渠道内容包</h3>
        <p>请先用已确认的公司和产品事实创建内容，再到审核中心逐个平台核对；空工作区不会生成固定脚本或文案。</p>
        <div class="page-actions">
          <a class="button button-primary" href="/content-factory">创建内容</a>
          <a class="button button-secondary" href="/reviews">进入审核中心</a>
        </div>
      </div>
      <ChannelPublishPanel
        v-model:batch-review-confirmed="batchReviewConfirmed"
        :review-packages="reviewPackages"
        :all-packages-approved="allPackagesApproved"
        :manual-export-issues="manualExportIssues"
        :channel-readiness="channelReadiness"
        :all-channels-ready="allChannelsReady"
        :pending-readiness-count="pendingReadinessCount"
        :publishing-route-summary="publishingRouteSummary"
        :approving-all="approveAllMutation.isPending.value"
        :exporting-all="exportAllMutation.isPending.value"
        :publishing="publishMutation.isPending.value"
        :publish-locked="Boolean(publishBatch)"
        :channel-label="channelLabel"
        @approve-all="approveAllPackages"
        @download-all="downloadAllPackages"
        @publish="publishAll"
        @focus-channel="focusChannelPackage"
      />
      <PublishResultsPanel
        v-if="publishBatch"
        :batch="publishBatch"
        :retrying="retryPublishMutation.isPending.value"
        :channel-label="channelLabel"
        @retry="retryFailed"
      />
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
