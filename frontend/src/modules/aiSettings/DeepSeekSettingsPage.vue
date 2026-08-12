<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue"

import { currentUserQueryOptions } from "../auth/auth"
import {
  aiProviderConfigurationQueryOptions, aiSettingsKeys, deleteAIProviderConfiguration,
  saveAIProviderConfiguration, testAIProviderConfiguration, type AIProviderConfiguration,
} from "./api"
import AppIcon from "../../shared/components/AppIcon.vue"
import OperationModal from "../../shared/components/OperationModal.vue"
import { ApiError } from "../../api/client"
import { ordinaryJobError } from "../../shared/presentation/ordinary"

const queryClient = useQueryClient()
const currentUser = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUser.data.value?.organization.id ?? "")
const canManage = computed(() => currentUser.data.value?.membership.permissions.includes("credentials.manage") ?? false)
const configuration = useQuery(computed(() => aiProviderConfigurationQueryOptions(organizationId.value, canManage.value)))
const connected = computed(() => configuration.data.value?.connection_state === "CONNECTED")
const keyValue = ref("")
const modalOpen = ref(false)
const deleteOpen = ref(false)
const testSucceeded = ref(false)
const statusMessage = ref("")
const errorMessage = ref("")
const deleteErrorMessage = ref("")
const errorElement = ref<HTMLElement | null>(null)
const deleteErrorElement = ref<HTMLElement | null>(null)
const keyInput = ref<HTMLInputElement | null>(null)
const dailyBudget = ref("5.00")
const flashTokens = ref(4096)
const proTokens = ref(8192)
const timeoutSeconds = ref(60)
let pendingTestUsesStoredKey = false
let pendingTestKey = ""
let operationGeneration = 0
let pendingTestContext: OperationContext | undefined
let pendingSaveContext: (OperationContext & { input: Parameters<typeof saveAIProviderConfiguration>[0] }) | undefined
let pendingDeleteContext: OperationContext | undefined

type OperationContext = { generation: number; organizationId: string }

function operationContext(): OperationContext {
  return { generation: operationGeneration, organizationId: organizationId.value }
}

function isCurrent(context?: OperationContext): boolean {
  return Boolean(context && context.generation === operationGeneration
    && context.organizationId === organizationId.value && canManage.value)
}

function applyConfiguration(value?: AIProviderConfiguration) {
  if (!value) return
  dailyBudget.value = value.daily_budget_usd
  flashTokens.value = value.flash_max_output_tokens
  proTokens.value = value.pro_max_output_tokens
  timeoutSeconds.value = value.timeout_seconds
}

watch(() => configuration.data.value, applyConfiguration, { immediate: true })

function wipeKey() {
  keyValue.value = ""
  pendingTestKey = ""
}

function resetSensitiveState() {
  operationGeneration += 1
  wipeKey()
  pendingTestContext = undefined
  pendingSaveContext = undefined
  pendingDeleteContext = undefined
  pendingTestUsesStoredKey = false
  testSucceeded.value = false
  modalOpen.value = false
  deleteOpen.value = false
  statusMessage.value = ""
  errorMessage.value = ""
  deleteErrorMessage.value = ""
  applyConfiguration(configuration.data.value)
}

function safeFailure(message = "连接没有成功，请检查 API Key 和网络后重试。") {
  wipeKey()
  testSucceeded.value = false
  statusMessage.value = ""
  errorMessage.value = message
  void nextTick(() => (modalOpen.value ? keyInput.value : errorElement.value)?.focus())
}

function safeProviderFailure(error: unknown) {
  if (error instanceof ApiError && error.code?.startsWith("deepseek_")) {
    const notice = ordinaryJobError({ code: error.code })
    safeFailure(`${notice.message}${notice.recovery}`)
    return
  }
  safeFailure()
}

const testMutation = useMutation({
  mutationFn: async () => {
    const context = pendingTestContext
    const apiKey = pendingTestKey
    try {
      const value = await testAIProviderConfiguration(apiKey || undefined)
      return { context, value }
    } finally {
      pendingTestKey = ""
    }
  },
  onSuccess: ({ context }) => {
    if (!isCurrent(context)) return
    wipeKey()
    errorMessage.value = ""
    if (!pendingTestUsesStoredKey) {
      testSucceeded.value = true
      statusMessage.value = "连接测试成功，请重新输入同一个 API Key 后保存。"
    } else {
      statusMessage.value = "现有连接可用。"
    }
  },
  onError: (error) => {
    if (isCurrent(pendingTestContext)) safeProviderFailure(error)
  },
})

const saveMutation = useMutation({
  mutationFn: async () => {
    const pending = pendingSaveContext
    if (!pending) throw new Error("missing operation context")
    const value = await saveAIProviderConfiguration(pending.input)
    return { context: pending, value }
  },
  onSuccess: ({ context, value }) => {
    if (!isCurrent(context)) return
    queryClient.setQueryData(aiSettingsKeys.configuration(context.organizationId), value)
    applyConfiguration(value)
    errorMessage.value = ""
    statusMessage.value = "DeepSeek 已连接，可以开始执行 AI 任务。"
    testSucceeded.value = false
    closeKeyModal(false)
  },
  onError: () => {
    if (isCurrent(pendingSaveContext)) safeFailure("保存没有成功，原来的连接和限制没有改变。请重新测试后再试。")
  },
  onSettled: () => { wipeKey(); pendingSaveContext = undefined },
})

const deleteMutation = useMutation({
  mutationFn: async () => {
    const context = pendingDeleteContext
    const value = await deleteAIProviderConfiguration()
    return { context, value }
  },
  onSuccess: ({ context, value }) => {
    if (!isCurrent(context)) return
    queryClient.setQueryData(aiSettingsKeys.configuration(context.organizationId), value)
    statusMessage.value = "DeepSeek 连接已删除。"
    deleteErrorMessage.value = ""
    deleteOpen.value = false
  },
  onError: () => {
    if (!isCurrent(pendingDeleteContext)) return
    deleteErrorMessage.value = "暂时无法删除连接，请稍后重试。"
    void nextTick(() => deleteErrorElement.value?.focus())
  },
  onSettled: () => { pendingDeleteContext = undefined },
})

function startTest() {
  if (!canManage.value || !organizationId.value || !keyValue.value || testMutation.isPending.value) return
  pendingTestUsesStoredKey = false
  pendingTestContext = operationContext()
  pendingTestKey = keyValue.value
  errorMessage.value = ""
  statusMessage.value = "正在安全测试连接…"
  testMutation.mutate()
}

function retest() {
  if (!canManage.value || !organizationId.value || testMutation.isPending.value) return
  pendingTestUsesStoredKey = true
  pendingTestContext = operationContext()
  pendingTestKey = ""
  errorMessage.value = ""
  statusMessage.value = "正在安全测试现有连接…"
  testMutation.mutate()
}

function save() {
  if (!canManage.value || !organizationId.value || !testSucceeded.value || !keyValue.value || saveMutation.isPending.value) return
  pendingSaveContext = { ...operationContext(), input: {
    api_key: keyValue.value, daily_budget_usd: Number(dailyBudget.value).toFixed(2),
    flash_max_output_tokens: flashTokens.value, pro_max_output_tokens: proTokens.value,
    timeout_seconds: timeoutSeconds.value,
  } }
  saveMutation.mutate()
}

function openKeyModal() {
  if (!canManage.value) return
  wipeKey()
  testSucceeded.value = false
  errorMessage.value = ""
  modalOpen.value = true
}

function closeKeyModal(restoreFocus = true) {
  wipeKey()
  testSucceeded.value = false
  modalOpen.value = false
  applyConfiguration(configuration.data.value)
  void restoreFocus
}

function openDeleteModal() {
  if (!canManage.value) return
  deleteErrorMessage.value = ""
  deleteOpen.value = true
}

function closeDeleteModal() {
  deleteErrorMessage.value = ""
  deleteOpen.value = false
}

function removeConnection() {
  if (!canManage.value || !organizationId.value || deleteMutation.isPending.value) return
  pendingDeleteContext = operationContext()
  deleteMutation.mutate()
}

watch([organizationId, canManage], ([nextOrganization, allowed], [previousOrganization]) => {
  if (!allowed || (previousOrganization && nextOrganization !== previousOrganization)) resetSensitiveState()
  if (!allowed) queryClient.removeQueries({ queryKey: aiSettingsKeys.all })
})
onBeforeUnmount(resetSensitiveState)
</script>

<template>
  <section v-if="canManage" data-testid="deepseek-settings-page" class="ai-settings-page page-stack">
    <header class="ai-settings-hero">
      <div>
        <p class="eyebrow">AI 能力设置</p>
        <h1>{{ connected ? "管理 DeepSeek" : "连接 DeepSeek" }}</h1>
        <p>只需由管理员配置一次。API Key 是 DeepSeek 提供的访问密钥，系统不会再次显示完整内容。</p>
      </div>
      <div class="ai-connection-state" :class="connected ? 'is-connected' : ''">
        <AppIcon :name="connected ? 'check' : 'key'" />
        <div>
          <strong>{{ connected ? "DeepSeek 已安全连接" : "DeepSeek 尚未连接" }}</strong>
          <span v-if="connected && configuration.data.value?.key_suffix">尾号 {{ configuration.data.value.key_suffix }}</span>
          <span v-else>连接后，AI 才能开始生成和分析</span>
        </div>
      </div>
    </header>

    <p v-if="configuration.isPending.value" class="state-message" role="status">正在读取安全设置…</p>
    <div v-else-if="configuration.isError.value" class="card state-error" role="alert">
      <strong>设置没有加载成功</strong><p>请检查网络后重新加载。</p>
      <button class="button button-secondary" type="button" @click="configuration.refetch()">重新加载</button>
    </div>

    <template v-else>
      <div v-if="errorMessage && !modalOpen" ref="errorElement" class="ai-settings-alert" role="alert" tabindex="-1">{{ errorMessage }}</div>
      <p v-if="statusMessage || testMutation.isPending.value" class="ai-settings-status" role="status" aria-live="polite">
        {{ statusMessage }}
      </p>

      <div class="ai-settings-grid">
        <article class="card ai-settings-card">
          <div class="section-heading"><div><p class="eyebrow">01 · 安全连接</p><h2>API Key</h2></div><AppIcon name="key" /></div>
          <p class="muted">密钥仅发送给服务器进行测试和保存，不会保留在页面、网址或浏览器缓存中。</p>
          <template v-if="!connected">
            <label class="field-label" for="deepseek-key">API Key（DeepSeek 提供的访问密钥）</label>
            <input id="deepseek-key" v-model="keyValue" class="text-input" type="password" autocomplete="off" spellcheck="false">
            <div class="ai-settings-actions">
              <button class="button button-secondary" type="button" :disabled="!keyValue || testMutation.isPending.value" @click="startTest">
                {{ testMutation.isPending.value ? "正在测试…" : "先测试连接" }}
              </button>
              <button class="button button-primary" type="button" :disabled="!testSucceeded || !keyValue || saveMutation.isPending.value" @click="save">
                {{ saveMutation.isPending.value ? "正在保存…" : "保存并启用" }}
              </button>
              <button class="button button-quiet" type="button" @click="wipeKey">清空</button>
            </div>
          </template>
          <div v-else class="ai-settings-actions">
            <button class="button button-secondary" type="button" :disabled="testMutation.isPending.value" @click="retest">
              {{ testMutation.isPending.value ? "正在测试…" : "重新测试" }}
            </button>
            <button class="button button-secondary" type="button" @click="openKeyModal">更换 API Key</button>
            <button class="button button-danger" type="button" @click="openDeleteModal">删除连接</button>
          </div>
        </article>

        <article class="card ai-settings-card">
          <div class="section-heading"><div><p class="eyebrow">02 · 费用保护</p><h2>每日使用上限</h2></div><AppIcon name="shield" /></div>
          <label class="field-label" for="daily-budget">每天最多使用（美元）</label>
          <input id="daily-budget" v-model="dailyBudget" class="text-input" type="number" min="0" max="100000" step="0.01" :disabled="connected">
          <p class="field-help">达到上限后，新任务会暂停，不会继续产生费用。</p>
          <button v-if="connected" class="button button-secondary" type="button" @click="openKeyModal">修改限制</button>
        </article>

        <article class="card ai-settings-card">
          <p class="eyebrow">03 · 自动选择</p><h2>AI 会自己选择合适方案</h2>
          <ul class="ai-routing-list">
            <li><AppIcon name="sparkles" /><span><strong>日常任务自动使用快速方案</strong><small>适合内容草稿和常规分析。</small></span></li>
            <li><AppIcon name="search" /><span><strong>复杂任务自动使用增强分析</strong><small>适合需要更多推理的任务。</small></span></li>
          </ul>
        </article>

        <article class="card ai-settings-card">
          <p class="eyebrow">04 · 高级限制</p><h2>任务保护参数</h2>
          <div class="ai-limit-grid">
            <label>快速方案输出上限<input v-model.number="flashTokens" class="text-input" type="number" min="64" max="65536" :disabled="connected"></label>
            <label>增强分析输出上限<input v-model.number="proTokens" class="text-input" type="number" min="64" max="65536" :disabled="connected"></label>
            <label>单次等待时间（秒）<input v-model.number="timeoutSeconds" class="text-input" type="number" min="1" max="300" :disabled="connected"></label>
          </div>
        </article>

        <article class="card ai-settings-card ai-settings-usage">
          <p class="eyebrow">近期用量</p><h2>使用记录</h2>
          <p class="muted">用量将在任务运行后显示于审计</p>
        </article>
      </div>
    </template>

    <OperationModal v-if="modalOpen" title="修改 DeepSeek 设置" title-id="replace-title" @close="closeKeyModal()">
      <div v-if="errorMessage" class="ai-settings-alert" role="alert">{{ errorMessage }}</div>
      <p>修改 API Key 或限制时，需要重新输入 API Key；系统会测试成功后再保存，失败时原设置不变。</p>
      <div class="ai-limit-grid">
        <label>每天最多使用（美元）<input v-model="dailyBudget" class="text-input" type="number" min="0" max="100000" step="0.01"></label>
        <label>快速方案输出上限<input v-model.number="flashTokens" class="text-input" type="number" min="64" max="65536"></label>
        <label>增强分析输出上限<input v-model.number="proTokens" class="text-input" type="number" min="64" max="65536"></label>
        <label>单次等待时间（秒）<input v-model.number="timeoutSeconds" class="text-input" type="number" min="1" max="300"></label>
      </div>
      <label class="field-label" for="replacement-key">API Key（DeepSeek 提供的访问密钥）</label>
      <input id="replacement-key" ref="keyInput" v-model="keyValue" class="text-input" type="password" autocomplete="off" spellcheck="false">
      <div class="ai-settings-actions">
        <button class="button button-secondary" type="button" :disabled="!keyValue || testMutation.isPending.value" @click="startTest">{{ testMutation.isPending.value ? "正在测试…" : "先测试连接" }}</button>
        <button class="button button-primary" type="button" :disabled="!testSucceeded || !keyValue || saveMutation.isPending.value" @click="save">{{ saveMutation.isPending.value ? "正在保存…" : "测试并保存设置" }}</button>
        <button class="button button-quiet" type="button" @click="wipeKey">清空</button>
        <button class="button button-quiet" type="button" @click="closeKeyModal()">取消</button>
      </div>
    </OperationModal>

    <OperationModal v-if="deleteOpen" title="确认删除 DeepSeek 连接" title-id="delete-title" @close="closeDeleteModal">
      <div v-if="deleteErrorMessage" ref="deleteErrorElement" class="ai-settings-alert" role="alert" aria-live="assertive" tabindex="-1">
        {{ deleteErrorMessage }}
      </div>
      <p>删除后，AI 任务将暂停，已有内容和审计记录不会被删除。</p>
      <div class="ai-settings-actions">
        <button class="button button-danger" type="button" :disabled="deleteMutation.isPending.value" @click="removeConnection">
          {{ deleteMutation.isPending.value ? "正在删除…" : deleteErrorMessage ? "重新删除" : "确认删除" }}
        </button>
        <button class="button button-secondary" type="button" @click="closeDeleteModal">保留连接</button>
      </div>
    </OperationModal>
  </section>
</template>

<style scoped>
.ai-settings-page{min-width:0}.ai-settings-hero{display:flex;align-items:center;justify-content:space-between;gap:24px;border:1px solid var(--sg-line);border-left:5px solid var(--sg-brand);border-radius:var(--sg-radius-lg);background:white;padding:clamp(24px,5vw,42px);box-shadow:var(--sg-shadow-sm)}.ai-settings-hero h1{margin:0;font-size:clamp(1.8rem,4vw,2.7rem)}.ai-settings-hero p:last-child{max-width:650px;margin:12px 0 0;color:var(--sg-muted);line-height:1.65}.ai-connection-state{display:flex;min-width:270px;align-items:center;gap:14px;border:1px solid var(--sg-line);border-radius:var(--sg-radius-md);background:var(--sg-canvas);padding:16px}.ai-connection-state.is-connected{border-color:#a9d8ba;background:var(--sg-status-success-tint);color:var(--sg-status-success)}.ai-connection-state .app-icon{width:28px;height:28px;flex:none}.ai-connection-state strong,.ai-connection-state span{display:block}.ai-connection-state span{margin-top:4px;font-size:.82rem}.ai-settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.ai-settings-card{min-width:0}.ai-settings-card h2{margin:0}.ai-settings-card>.muted{line-height:1.65}.section-heading>.app-icon{width:28px;height:28px;color:var(--sg-brand)}.field-label,.ai-limit-grid label{display:grid;gap:7px;margin-top:18px;font-weight:700}.text-input{width:100%;min-height:44px;border:1px solid #b9c6d3;border-radius:var(--sg-radius-sm);background:white;padding:10px 12px;color:var(--sg-ink)}.field-help{margin:8px 0 0;color:var(--sg-muted);font-size:.86rem;line-height:1.5}.ai-settings-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}.button-danger{border-color:var(--sg-danger);background:white;color:var(--sg-danger)}.ai-routing-list{display:grid;gap:14px;margin:20px 0 0;padding:0;list-style:none}.ai-routing-list li{display:flex;gap:12px;border-radius:var(--sg-radius-sm);background:var(--sg-brand-soft);padding:14px;color:var(--sg-brand)}.ai-routing-list .app-icon{width:22px;height:22px;flex:none}.ai-routing-list strong,.ai-routing-list small{display:block}.ai-routing-list small{margin-top:4px;color:var(--sg-muted);line-height:1.45}.ai-limit-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 14px}.ai-settings-usage{grid-column:1/-1}.ai-settings-alert,.ai-settings-status{margin:0;border-radius:var(--sg-radius-sm);padding:14px 16px}.ai-settings-alert{border:1px solid #e7c471;background:var(--sg-status-warning-tint);color:#6a4b00}.ai-settings-status{background:var(--sg-status-success-tint);color:var(--sg-status-success)}.ai-modal-backdrop{position:fixed;inset:0;z-index:80;display:grid;place-items:center;background:rgb(23 34 49 / 48%);padding:18px}.ai-modal{width:min(100%,540px);max-height:calc(100vh - 36px);overflow:auto;border-radius:var(--sg-radius-lg);background:white;padding:clamp(22px,5vw,32px);box-shadow:var(--sg-shadow)}.ai-modal h2{margin:0}.ai-modal>p{color:var(--sg-muted);line-height:1.6}@media(max-width:720px){.ai-settings-hero{align-items:stretch;flex-direction:column}.ai-connection-state{min-width:0}.ai-settings-grid{grid-template-columns:1fr}.ai-settings-usage{grid-column:auto}.ai-limit-grid{grid-template-columns:1fr}.ai-settings-actions>.button{width:100%;min-height:44px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style>
