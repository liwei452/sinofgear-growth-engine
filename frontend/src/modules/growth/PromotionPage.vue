<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref, watchEffect } from "vue"

import {
  approveChannelPackage,
  authorizePlatformConnection,
  createPublishBatch,
  exportChannelPackage,
  growthQueryKeys,
  growthWorkspaceQueryOptions,
  retryFailedPublishBatch,
  type ChannelPackage,
  type ManualPackageExport,
  type PlatformConnection,
  type PublishBatch,
} from "./api"

const queryClient = useQueryClient()
const workspaceQuery = useQuery(growthWorkspaceQueryOptions())
const locallyApprovedIds = ref(new Set<string>())
const fallbackApproved = ref(false)
const approvalError = ref("")
const downloadMessage = ref("")
const downloadError = ref("")
const publishBatch = ref<PublishBatch | null>(null)
const publishError = ref("")
const connectionError = ref("")
const publishKey = ref("")
const publishSignature = ref("")
const publishKeySequence = ref(0)
const activePackage = computed(() => workspaceQuery.data.value?.channel_packages
  .find((item) => item.channel === "TIKTOK"))
const packageTitle = computed(() => String(activePackage.value?.payload.title ?? ""))
function packageFor(channel: string): ChannelPackage | undefined {
  return workspaceQuery.data.value?.channel_packages.find((item) => item.channel === channel)
}
function isApproved(channelPackage: ChannelPackage | undefined): boolean {
  return Boolean(channelPackage && (
    channelPackage.status === "APPROVED" || locallyApprovedIds.value.has(channelPackage.id)
  ))
}
const approved = computed(() => activePackage.value
  ? isApproved(activePackage.value)
  : fallbackApproved.value)
const connectionsByChannel = computed(() => new Map(
  (workspaceQuery.data.value?.connectors ?? []).map(item => [item.channel, item]),
))
const eligiblePackages = computed(() => (workspaceQuery.data.value?.channel_packages ?? [])
  .filter(channelPackage => isApproved(channelPackage) && connectionFor(channelPackage.channel)?.status === "CONNECTED"))
const failedPublishItems = computed(() => publishBatch.value?.items
  .filter(item => item.status === "FAILED") ?? [])
const succeededPublishCount = computed(() => publishBatch.value?.items
  .filter(item => item.status === "SUCCEEDED").length ?? 0)
watchEffect(() => {
  const latest = workspaceQuery.data.value?.publish_batches?.[0]
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
const exportMutation = useMutation({ mutationFn: exportChannelPackage })
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

function connectionFor(channel: string): PlatformConnection | undefined {
  return connectionsByChannel.value.get(channel)
}

function connectionDisplay(channel: string): string {
  const connection = connectionFor(channel)
  if (!connection) return "未连接"
  return connection.mode === "DEMO_FAKE"
    ? `${connection.connection_label} · Demo / Fake`
    : connection.connection_label
}

function modeLabel(channel: string): string {
  return connectionFor(channel)?.mode === "OFFICIAL" ? "官方连接" : "Demo / Fake"
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

async function approve(): Promise<void> {
  await approvePackage(activePackage.value)
}

async function approvePackage(channelPackage: ChannelPackage | undefined): Promise<void> {
  approvalError.value = ""
  if (!channelPackage) {
    fallbackApproved.value = true
    return
  }
  await approveMutation.mutateAsync(channelPackage.id).catch(() => undefined)
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
  const packageIds = eligiblePackages.value.map(item => item.id)
  if (!packageIds.length) return
  await publishMutation.mutateAsync({ packageIds, key: currentPublishKey() }).catch(() => undefined)
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
</script>

<template>
  <div class="growth-page">
    <header class="growth-hero">
      <div><p class="eyebrow">推广</p><h1>推广计划与内容包</h1><p>AI 已准备内容；人工批准后，可一次发布到所有已连接渠道。</p></div>
      <span class="fake-label">Demo / Fake</span>
    </header>

    <section class="growth-card plan-summary">
      <div><span>目标市场</span><strong>德国 · 包装机械</strong></div>
      <div><span>理想客户</span><strong>德国包装机械制造商 · 51–500 人</strong></div>
      <div><span>推广周期</span><strong>14 天 · 每周 3 个内容包</strong></div>
      <div><span>审核边界</span><strong>所有内容人工批准后导出</strong></div>
    </section>

    <section class="growth-card">
      <div class="growth-heading"><div><h2>内容日历</h2><p>先审计划，再逐条审内容；日期可在手工发布前调整。</p></div><span>6 个待审内容包</span></div>
      <div class="calendar-strip">
        <article><time>8 月 17 日</time><strong>精密检测如何降低装机返工</strong><span>LinkedIn · Instagram</span></article>
        <article><time>8 月 19 日</time><strong>30 秒看懂斜齿轮检测流程</strong><span>TikTok · Reels</span></article>
        <article><time>8 月 21 日</time><strong>包装线传动件选型核对表</strong><span>Facebook · LinkedIn</span></article>
      </div>
    </section>

    <section class="growth-card">
      <div class="growth-heading"><div><h2>各渠道内容包</h2><p>先审核内容，再一次提交到所有可用渠道。</p></div><span class="connector-state">Fake Connector · 一键发布演示</span></div>
      <div class="package-grid">
        <article v-for="channel in channels" :key="channel.name" :aria-label="`${channel.name} 内容包`">
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
          <p class="package-source">{{ String(packageFor(channel.code)?.payload.title ?? channel.format) }}</p>
          <p>{{ channel.format }}</p><strong>手工发布包</strong>
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
        <article class="tiktok-package" aria-label="TikTok 内容包">
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
          <p v-if="packageTitle" class="package-source">{{ packageTitle }}</p>
          <p class="package-lead">30 秒 · 9:16 · 手工发布包 · {{ modeLabel('TIKTOK') }}</p>
          <dl>
            <div><dt>脚本</dt><dd>15–60 秒结构：痛点 4 秒 → 检测过程 18 秒 → 证据与 CTA 8 秒</dd></div>
            <div><dt>分镜</dt><dd>1. 齿面特写 2. 测量仪读数 3. 检测报告 4. 包装线应用</dd></div>
            <div><dt>声音</dt><dd>英文口播 + 完整中文字幕，术语由人工核对</dd></div>
            <div><dt>发布信息</dt><dd>标题 / 标签 / CTA：查看检测能力摘要</dd></div>
            <div><dt>归因</dt><dd>UTM：tiktok / organic / din6-proof-demo</dd></div>
            <div><dt>回填</dt><dd>发布结果、播放、完播、点击、回复、询盘可手工录入</dd></div>
          </dl>
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
      <section v-if="eligiblePackages.length" class="publish-panel" aria-label="一键发布">
        <div>
          <p class="eyebrow">已批准 {{ eligiblePackages.length }} 个渠道</p>
          <h3>一次发布，分别记录结果</h3>
          <p>本地仅演示完整发布流程，不会请求真实社媒平台。</p>
        </div>
        <button
          class="button button-primary" type="button"
          :disabled="publishMutation.isPending.value || Boolean(publishBatch)"
          @click="publishAll"
        >
          {{ publishMutation.isPending.value ? "正在提交…" : `一键发布到 ${eligiblePackages.length} 个渠道` }}
        </button>
      </section>
      <section v-if="publishBatch" class="publish-results" aria-label="发布结果">
        <div class="growth-heading">
          <div><p class="eyebrow">{{ publishBatch.data_label }}</p><h3>渠道发布结果</h3></div>
          <strong v-if="publishBatch.status === 'SUCCEEDED'">4 个渠道均已发布成功。</strong>
          <strong v-else-if="failedPublishItems.length">
            {{ succeededPublishCount }} 个渠道发布成功，{{ failedPublishItems.length }} 个渠道需要重试。
          </strong>
          <strong v-else>发布请求已受理。</strong>
        </div>
        <ul class="publish-result-list">
          <li v-for="item in publishBatch.items" :key="item.id">
            <span>{{ channelLabel(item.channel) }}</span>
            <a
              v-if="item.status === 'SUCCEEDED'" :href="item.external_post_url"
              target="_blank" rel="noreferrer"
              :aria-label="`查看 ${channelLabel(item.channel)} Demo 帖子`"
            >发布成功 · 查看 Demo 帖子</a>
            <span v-else>{{ item.recovery_action || "等待发布" }}</span>
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
      <div class="approval-row">
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
