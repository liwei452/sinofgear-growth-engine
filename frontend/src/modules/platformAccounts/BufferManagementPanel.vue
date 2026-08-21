<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, onBeforeUnmount, ref } from "vue"

import { ApiError } from "../../api/client"
import AppIcon from "../../shared/components/AppIcon.vue"
import OperationModal from "../../shared/components/OperationModal.vue"
import { currentUserQueryOptions } from "../auth/auth"
import {
  connectBuffer,
  disconnectBuffer,
  getBufferConnection,
  platformAccountKeys,
  probeBufferConnection,
  rotateBufferKey,
  syncBufferChannels,
  type Platform,
  type SocialAccount,
} from "./api"

const props = defineProps<{
  accounts: readonly SocialAccount[]
  platforms: readonly Platform[]
}>()

type Dialog = "CONNECT" | "ROTATE" | "DISCONNECT"
type Operation = "CONNECT" | "ROTATE" | "PROBE" | "SYNC" | "DISCONNECT"

const queryClient = useQueryClient()
const currentUser = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUser.data.value?.organization.id ?? "")
const canAdminister = computed(() => (
  currentUser.data.value?.membership.role === "ADMINISTRATOR"
  && currentUser.data.value.membership.permissions.includes("publishing.read")
  && currentUser.data.value.membership.permissions.includes("credentials.manage")
))
const connectionQuery = useQuery({
  queryKey: computed(() => platformAccountKeys.buffer(organizationId.value)),
  queryFn: getBufferConnection,
  enabled: computed(() => Boolean(organizationId.value) && canAdminister.value),
})

const dialog = ref<Dialog | null>(null)
const apiKey = ref("")
const bufferOrganizationId = ref("")
const notice = ref("")
const operationError = ref<unknown>()

const connection = computed(() => connectionQuery.data.value ?? null)
const bufferAccounts = computed(() => props.accounts.filter(account => account.provider === "BUFFER"))
const busy = computed(() => operation.isPending.value)

const statusPresentation = computed(() => {
  const value = connection.value
  if (!value) return { label: "未配置", tone: "neutral", advice: "填写 Buffer 组织 ID 和 API Key 后连接；系统不会保存或回显输入框内容。" }
  const states = {
    CONNECTED: { label: "已连接", tone: "success", advice: "连接可用。建议定期测试连接并同步渠道。" },
    CONFIGURATION_REQUIRED: { label: "配置不完整", tone: "warning", advice: "请重新连接并补充有效的组织 ID 与 API Key。" },
    REFRESH_DUE: { label: "配置不完整", tone: "warning", advice: "连接需要重新探测，请先测试连接。" },
    REAUTHORIZATION_REQUIRED: { label: "需要重新授权", tone: "danger", advice: "请轮换 API Key，然后重新测试连接和同步渠道。" },
    INSUFFICIENT_CAPABILITY: { label: "配置不完整", tone: "warning", advice: "当前凭据能力不足，请使用具备渠道读取与发布权限的 API Key。" },
    PROVIDER_UNAVAILABLE: { label: "Provider 暂不可用", tone: "warning", advice: "请稍后测试连接；历史发布记录不会受影响。" },
    DISCONNECTED: { label: "已断开", tone: "neutral", advice: "如需恢复自动发布，请重新连接 Buffer。" },
  } as const
  return states[value.connection_state] ?? {
    label: "配置不完整",
    tone: "warning",
    advice: "连接摘要不完整，请刷新页面后重试。",
  }
})

const errorPresentation = computed(() => {
  const error = operationError.value ?? connectionQuery.error.value
  if (!error) return null
  if (!(error instanceof ApiError)) {
    return { message: "Buffer 操作未能完成。", code: "", advice: "请刷新后重试。" }
  }
  const advice = error.status === 409 ? "连接状态已变化，请刷新后重试。"
    : error.status === 429 ? "操作过于频繁，请稍后再试。"
      : error.status === 502 || error.status === 503 ? "稍后重新测试连接；若持续失败，请检查 Buffer 服务状态。"
        : error.status === 403 ? "当前账户无管理权限，请联系组织管理员。"
          : error.recoveryAction ?? "请检查输入后重试。"
  return { message: error.userMessage, code: error.code ?? "", advice }
})

const operation = useMutation({
  mutationFn: async (kind: Operation) => {
    if (kind === "CONNECT") return connectBuffer({ api_key: apiKey.value, organization_id: bufferOrganizationId.value })
    if (kind === "ROTATE") return rotateBufferKey(apiKey.value)
    if (kind === "PROBE") return probeBufferConnection()
    if (kind === "SYNC") return syncBufferChannels()
    return disconnectBuffer()
  },
  onMutate: () => {
    notice.value = ""
    operationError.value = undefined
  },
  onSuccess: async (_result, kind) => {
    const notices: Record<Operation, string> = {
      CONNECT: "Buffer 已连接。",
      ROTATE: "API Key 已轮换。",
      PROBE: "连接测试通过。",
      SYNC: "Buffer 渠道已同步。",
      DISCONNECT: "Buffer 已断开。",
    }
    notice.value = notices[kind]
    closeDialog()
    await queryClient.invalidateQueries({ queryKey: platformAccountKeys.all(organizationId.value) })
  },
  onError: (error) => {
    operationError.value = error
    closeDialog()
  },
  onSettled: () => {
    apiKey.value = ""
  },
})

function openDialog(kind: Dialog) {
  operationError.value = undefined
  apiKey.value = ""
  if (kind === "CONNECT") bufferOrganizationId.value = ""
  dialog.value = kind
}

function closeDialog() {
  apiKey.value = ""
  bufferOrganizationId.value = ""
  dialog.value = null
}

function run(kind: Operation) {
  if (!busy.value) operation.mutate(kind)
}

function formatDate(value: string | null | undefined) {
  if (!value) return "尚无记录"
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
}

function platformFor(account: SocialAccount) {
  return props.platforms.find(platform => platform.id === account.platform_id)
}

function platformName(account: SocialAccount) {
  return platformFor(account)?.name ?? "未知平台"
}

function platformMark(account: SocialAccount) {
  const code = platformFor(account)?.code.toLowerCase()
  if (code === "linkedin") return "in"
  if (code === "facebook") return "f"
  if (code === "instagram") return "◎"
  return "•"
}

function canAutoPublish(account: SocialAccount) {
  return account.status === "ACTIVE"
    && account.connection_state === "CONNECTED"
    && !account.is_locked
    && !account.is_queue_paused
    && !account.reauthorization_required_at
    && account.effective_capabilities.includes("PUBLISH")
}

onBeforeUnmount(() => { apiKey.value = "" })
</script>

<template>
  <section v-if="canAdminister" class="buffer-management" aria-labelledby="buffer-management-title">
    <header class="buffer-heading">
      <div>
        <p class="eyebrow">官方连接器</p>
        <h2 id="buffer-management-title">Buffer 管理</h2>
        <p>集中管理连接与同步，只显示服务端提供的安全摘要。</p>
      </div>
      <span class="status-badge" :class="`status-${statusPresentation.tone}`">{{ statusPresentation.label }}</span>
    </header>

    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <div v-if="errorPresentation" class="error-notice" role="alert">
      <strong>{{ errorPresentation.message }}</strong>
      <span v-if="errorPresentation.code">错误码：{{ errorPresentation.code }}</span>
      <p>{{ errorPresentation.advice }}</p>
    </div>

    <p v-if="connectionQuery.isPending.value" class="loading" role="status">正在读取 Buffer 连接…</p>
    <template v-else>
      <section class="overview-card" aria-labelledby="buffer-overview-title">
        <div class="section-title">
          <div><h3 id="buffer-overview-title">Buffer 连接概览</h3><p>{{ statusPresentation.advice }}</p></div>
          <AppIcon name="share-2" :size="22" />
        </div>
        <dl class="connection-facts">
          <div><dt>连接状态</dt><dd>{{ statusPresentation.label }}</dd></div>
          <div><dt>Buffer 组织</dt><dd>{{ connection?.display_name || "尚未连接" }}</dd></div>
          <div><dt>安全组织标识</dt><dd>{{ connection?.external_id || "尚无记录" }}</dd></div>
          <div><dt>最后探测</dt><dd>{{ formatDate(connection?.last_probe_at) }}</dd></div>
          <div><dt>最后同步</dt><dd>{{ formatDate(connection?.last_sync_at) }}</dd></div>
          <div><dt>重新授权</dt><dd>{{ connection?.reauthorization_required_at ? "需要" : "不需要" }}</dd></div>
          <div><dt>安全错误状态</dt><dd>{{ connection?.lifecycle_error_code || "无" }}</dd></div>
          <div><dt>已同步渠道</dt><dd>{{ connection?.active_channel_count ?? 0 }} / {{ connection?.channel_count ?? 0 }}</dd></div>
        </dl>
        <div class="connection-actions" aria-label="Buffer 连接操作">
          <button v-if="!connection?.configured || connection.connection_state === 'DISCONNECTED'" class="button button-primary" type="button" :disabled="busy" @click="openDialog('CONNECT')">连接 Buffer</button>
          <template v-else>
            <button class="button button-primary" type="button" :disabled="busy" @click="openDialog('ROTATE')">轮换 API Key</button>
            <button class="button button-quiet" type="button" :disabled="busy" @click="run('PROBE')">测试连接</button>
            <button class="button button-quiet" type="button" :disabled="busy" @click="run('SYNC')">同步渠道</button>
            <button class="button disconnect-button" type="button" :disabled="busy" @click="openDialog('DISCONNECT')">断开连接</button>
          </template>
        </div>
      </section>

      <section class="channels-section" aria-labelledby="buffer-channels-title">
        <div class="section-title">
          <div><h3 id="buffer-channels-title">已同步渠道</h3><p>渠道状态来自最近一次 Buffer 同步，不读取原始 Provider 元数据。</p></div>
          <span>{{ bufferAccounts.length }} 个渠道</span>
        </div>
        <div v-if="!bufferAccounts.length" class="empty-channels">
          <strong>还没有同步渠道</strong>
          <p>{{ connection?.configured ? "点击“同步渠道”读取可用的 LinkedIn、Facebook 和 Instagram 渠道。" : "连接 Buffer 后再同步渠道。" }}</p>
        </div>
        <div v-else class="channel-grid">
          <article v-for="account in bufferAccounts" :key="account.id" class="channel-card" :aria-label="`${platformName(account)} 渠道 ${account.display_name}`">
            <header>
              <span class="platform-icon" aria-hidden="true">{{ platformMark(account) }}</span>
              <div><span>{{ platformName(account) }}</span><h4>{{ account.display_name }}</h4></div>
            </header>
            <p class="channel-id">渠道 ID {{ account.provider_channel_display_id || "未提供" }}</p>
            <div class="channel-badges">
              <span :class="account.status === 'ACTIVE' ? 'badge-success' : 'badge-neutral'">{{ account.status === "ACTIVE" ? "已连接" : "未启用" }}</span>
              <span v-if="account.is_locked" class="badge-danger">渠道已锁定</span>
              <span v-if="account.is_queue_paused" class="badge-warning">Buffer 队列已暂停</span>
              <span v-if="account.connection_state === 'REAUTHORIZATION_REQUIRED' || account.reauthorization_required_at" class="badge-danger">需要重新授权</span>
            </div>
            <dl class="channel-meta">
              <div><dt>Provider 最近同步</dt><dd>{{ formatDate(account.provider_last_sync_at) }}</dd></div>
              <div><dt>自动发布</dt><dd :class="canAutoPublish(account) ? 'ready' : 'not-ready'">{{ canAutoPublish(account) ? "可自动发布" : "不可自动发布" }}</dd></div>
            </dl>
          </article>
        </div>
      </section>
    </template>

    <OperationModal v-if="dialog === 'CONNECT'" title="连接 Buffer" title-id="buffer-connect-title" @close="closeDialog">
      <form class="operation-form" @submit.prevent="run('CONNECT')">
        <label for="buffer-organization">Buffer 组织 ID</label>
        <input id="buffer-organization" v-model="bufferOrganizationId" required autocomplete="off">
        <label for="buffer-api-key">Buffer API Key</label>
        <input id="buffer-api-key" v-model="apiKey" required type="password" autocomplete="new-password" spellcheck="false">
        <small>API Key 仅提交到服务端。本页面不会保存、回显或记录它。</small>
        <div class="modal-actions"><button class="button button-quiet" type="button" @click="closeDialog">取消</button><button class="button button-primary" :disabled="busy">保存连接</button></div>
      </form>
    </OperationModal>

    <OperationModal v-if="dialog === 'ROTATE'" title="轮换 API Key" title-id="buffer-rotate-title" @close="closeDialog">
      <form class="operation-form" @submit.prevent="run('ROTATE')">
        <label for="buffer-new-api-key">新的 Buffer API Key</label>
        <input id="buffer-new-api-key" v-model="apiKey" required type="password" autocomplete="new-password" spellcheck="false">
        <small>现有 Key 永不回显；本次输入在请求完成后立即清空。</small>
        <div class="modal-actions"><button class="button button-quiet" type="button" @click="closeDialog">取消</button><button class="button button-primary" :disabled="busy">确认轮换</button></div>
      </form>
    </OperationModal>

    <OperationModal v-if="dialog === 'DISCONNECT'" title="断开 Buffer" title-id="buffer-disconnect-title" @close="closeDialog">
      <div class="disconnect-confirmation">
        <p>断开后将停用通过 Buffer 同步的发布渠道，但不会删除历史发布记录。</p>
        <div class="modal-actions"><button class="button button-quiet" type="button" @click="closeDialog">取消</button><button class="button disconnect-button" type="button" :disabled="busy" @click="run('DISCONNECT')">确认断开</button></div>
      </div>
    </OperationModal>
  </section>
</template>

<style scoped>
.buffer-management { display: grid; gap: 16px; border: 1px solid #cfe5fb; border-radius: var(--sg-radius-lg); background: #f8fbff; padding: clamp(18px, 3vw, 26px); }
.buffer-heading, .section-title, .connection-actions, .modal-actions, .channel-card header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.buffer-heading h2, .buffer-heading p, .section-title h3, .section-title p, .channel-card h4, .channel-card p, .error-notice p { margin: 0; }
.buffer-heading > div > p:last-child, .section-title p { margin-top: 5px; color: var(--sg-muted); font-size: .8rem; line-height: 1.5; }
.status-badge, .channel-badges span { display: inline-flex; align-items: center; min-height: 26px; border-radius: 999px; padding: 4px 9px; font-size: .7rem; font-weight: 800; }
.status-success, .badge-success { background: var(--sg-success-soft); color: #16765a; }
.status-warning, .badge-warning { background: var(--sg-warning-soft); color: #8a5800; }
.status-danger, .badge-danger { background: var(--sg-danger-soft); color: #b23b3b; }
.status-neutral, .badge-neutral { background: #edf3f8; color: #53697d; }
.notice, .error-notice, .loading { margin: 0; border-radius: var(--sg-radius-sm); padding: 11px 13px; font-size: .8rem; }
.notice { background: var(--sg-success-soft); color: #16765a; }
.error-notice { display: grid; gap: 4px; background: var(--sg-danger-soft); color: #963737; }
.error-notice span { font-size: .7rem; font-weight: 800; }
.loading { background: var(--sg-brand-soft); color: var(--sg-brand-strong); }
.overview-card, .channels-section { display: grid; gap: 18px; border: 1px solid var(--sg-line); border-radius: var(--sg-radius-md); background: #fff; padding: clamp(16px, 3vw, 22px); }
.section-title svg { flex: 0 0 auto; color: var(--sg-brand); }
.section-title > span { flex: 0 0 auto; color: var(--sg-muted); font-size: .74rem; font-weight: 800; }
.connection-facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin: 0; }
.connection-facts div, .channel-meta div { display: grid; gap: 4px; }
.connection-facts dt, .channel-meta dt { color: var(--sg-muted); font-size: .68rem; }
.connection-facts dd, .channel-meta dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--sg-ink); font-size: .8rem; font-weight: 750; }
.connection-actions { justify-content: flex-start; flex-wrap: wrap; padding-top: 2px; }
.disconnect-button { border-color: #f0bebe; background: #fff; color: var(--sg-danger); }
.empty-channels { border: 1px dashed #bcd8f2; border-radius: var(--sg-radius-md); padding: 18px; }
.empty-channels p { margin: 5px 0 0; color: var(--sg-muted); font-size: .8rem; }
.channel-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.channel-card { display: grid; align-content: start; gap: 13px; border: 1px solid var(--sg-line); border-radius: var(--sg-radius-md); padding: 16px; }
.channel-card header { justify-content: flex-start; }
.platform-icon { display: grid; width: 36px; height: 36px; flex: 0 0 auto; place-items: center; border-radius: 10px; background: var(--sg-brand-soft); color: var(--sg-brand-strong); font-size: .92rem; font-weight: 900; }
.channel-card header span:not(.platform-icon) { color: var(--sg-muted); font-size: .68rem; }
.channel-card h4 { margin-top: 2px; font-size: .88rem; }
.channel-id { color: var(--sg-muted); font-size: .72rem; }
.channel-badges { display: flex; flex-wrap: wrap; gap: 6px; }
.channel-meta { display: grid; gap: 10px; margin: 0; border-top: 1px solid var(--sg-line); padding-top: 12px; }
.channel-meta .ready { color: #16765a; }.channel-meta .not-ready { color: #9a4d3c; }
.operation-form, .disconnect-confirmation { display: grid; gap: 12px; }
.operation-form label { color: var(--sg-ink); font-size: .78rem; font-weight: 750; }
.operation-form input { min-height: 44px; border: 1px solid var(--sg-line); border-radius: var(--sg-radius-sm); padding: 9px 11px; color: var(--sg-ink); }
.operation-form small, .disconnect-confirmation p { color: var(--sg-muted); font-size: .76rem; line-height: 1.55; }
.modal-actions { justify-content: flex-end; margin-top: 4px; }
@media (max-width: 900px) { .connection-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }.channel-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) { .buffer-heading, .section-title { display: grid; }.status-badge { justify-self: start; }.channel-grid { grid-template-columns: 1fr; }.connection-actions .button, .modal-actions .button { flex: 1 1 auto; }.buffer-management { padding: 14px; } }
</style>
