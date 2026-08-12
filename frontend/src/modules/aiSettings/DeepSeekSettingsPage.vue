<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { currentUserQueryOptions } from "../auth/auth"
import {
  aiProviderConfigurationQueryOptions, aiSettingsKeys, deleteAIProviderConfiguration,
  saveAIProviderConfiguration, testAIProviderConfiguration, type AIProviderConfiguration,
} from "./api"
import AppIcon from "../../shared/components/AppIcon.vue"

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
const errorElement = ref<HTMLElement | null>(null)
const replaceButton = ref<HTMLButtonElement | null>(null)
const deleteButton = ref<HTMLButtonElement | null>(null)
const dailyBudget = ref("5.00")
const flashTokens = ref(4096)
const proTokens = ref(8192)
const timeoutSeconds = ref(60)
let pendingTestUsesStoredKey = false
let pendingTestKey = ""

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
}

function safeFailure(message = "连接没有成功，请检查 API Key 和网络后重试。") {
  wipeKey()
  testSucceeded.value = false
  statusMessage.value = ""
  errorMessage.value = message
  void nextTick(() => errorElement.value?.focus())
}

const testMutation = useMutation({
  mutationFn: async () => {
    const apiKey = pendingTestKey
    try {
      return await testAIProviderConfiguration(apiKey || undefined)
    } finally {
      pendingTestKey = ""
    }
  },
  onSuccess: () => {
    wipeKey()
    errorMessage.value = ""
    if (!pendingTestUsesStoredKey) {
      testSucceeded.value = true
      statusMessage.value = "连接测试成功，请重新输入同一个 API Key 后保存。"
    } else {
      statusMessage.value = "现有连接可用。"
    }
  },
  onError: () => safeFailure(),
})

const saveMutation = useMutation({
  mutationFn: () => saveAIProviderConfiguration({
    api_key: keyValue.value,
    daily_budget_usd: dailyBudget.value,
    flash_max_output_tokens: flashTokens.value,
    pro_max_output_tokens: proTokens.value,
    timeout_seconds: timeoutSeconds.value,
  }),
  onSuccess: (value) => {
    queryClient.setQueryData(aiSettingsKeys.configuration(organizationId.value), value)
    errorMessage.value = ""
    statusMessage.value = "DeepSeek 已连接，可以开始执行 AI 任务。"
    testSucceeded.value = false
    closeKeyModal(false)
  },
  onError: () => safeFailure("保存没有成功，原来的连接没有改变。请重新测试后再试。"),
  onSettled: wipeKey,
})

const deleteMutation = useMutation({
  mutationFn: deleteAIProviderConfiguration,
  onSuccess: (value) => {
    queryClient.setQueryData(aiSettingsKeys.configuration(organizationId.value), value)
    statusMessage.value = "DeepSeek 连接已删除。"
    deleteOpen.value = false
    void nextTick(() => deleteButton.value?.focus())
  },
  onError: () => safeFailure("暂时无法删除连接，请稍后重试。"),
})

function startTest() {
  if (!keyValue.value || testMutation.isPending.value) return
  pendingTestUsesStoredKey = false
  pendingTestKey = keyValue.value
  errorMessage.value = ""
  statusMessage.value = "正在安全测试连接…"
  testMutation.mutate()
}

function retest() {
  if (testMutation.isPending.value) return
  pendingTestUsesStoredKey = true
  pendingTestKey = ""
  errorMessage.value = ""
  statusMessage.value = "正在安全测试现有连接…"
  testMutation.mutate()
}

function save() {
  if (!testSucceeded.value || !keyValue.value || saveMutation.isPending.value) return
  saveMutation.mutate()
}

function openKeyModal() {
  wipeKey()
  testSucceeded.value = false
  errorMessage.value = ""
  modalOpen.value = true
}

function closeKeyModal(restoreFocus = true) {
  wipeKey()
  testSucceeded.value = false
  modalOpen.value = false
  if (restoreFocus) void nextTick(() => replaceButton.value?.focus())
}

function onKeydown(event: KeyboardEvent) {
  if (event.key !== "Escape") return
  if (modalOpen.value) closeKeyModal()
  else if (deleteOpen.value) {
    deleteOpen.value = false
    void nextTick(() => deleteButton.value?.focus())
  }
}

watch(canManage, (allowed) => {
  if (!allowed) queryClient.removeQueries({ queryKey: aiSettingsKeys.all })
})
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown))
onMounted(() => window.addEventListener("keydown", onKeydown))
</script>

<template>
  <section data-testid="deepseek-settings-page" class="ai-settings-page page-stack">
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
      <div v-if="errorMessage" ref="errorElement" class="ai-settings-alert" role="alert" tabindex="-1">{{ errorMessage }}</div>
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
            <button ref="replaceButton" class="button button-secondary" type="button" @click="openKeyModal">更换 API Key</button>
            <button ref="deleteButton" class="button button-danger" type="button" @click="deleteOpen = true">删除连接</button>
          </div>
        </article>

        <article class="card ai-settings-card">
          <div class="section-heading"><div><p class="eyebrow">02 · 费用保护</p><h2>每日使用上限</h2></div><AppIcon name="shield" /></div>
          <label class="field-label" for="daily-budget">每天最多使用（美元）</label>
          <input id="daily-budget" v-model="dailyBudget" class="text-input" type="number" min="0" max="100000" step="0.01">
          <p class="field-help">达到上限后，新任务会暂停，不会继续产生费用。</p>
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
            <label>快速方案输出上限<input v-model.number="flashTokens" class="text-input" type="number" min="64" max="65536"></label>
            <label>增强分析输出上限<input v-model.number="proTokens" class="text-input" type="number" min="64" max="65536"></label>
            <label>单次等待时间（秒）<input v-model.number="timeoutSeconds" class="text-input" type="number" min="1" max="300"></label>
          </div>
        </article>

        <article class="card ai-settings-card ai-settings-usage">
          <p class="eyebrow">近期用量</p><h2>使用记录</h2>
          <p class="muted">用量将在任务运行后显示于审计</p>
        </article>
      </div>
    </template>

    <div v-if="modalOpen" data-testid="ai-key-modal-backdrop" class="ai-modal-backdrop" @mousedown.self="closeKeyModal()">
      <section class="ai-modal" role="dialog" aria-modal="true" aria-labelledby="replace-title">
        <h2 id="replace-title">更换 API Key</h2><p>先测试新密钥。测试失败时，原来的连接不会改变。</p>
        <label class="field-label" for="replacement-key">API Key（DeepSeek 提供的访问密钥）</label>
        <input id="replacement-key" v-model="keyValue" class="text-input" type="password" autocomplete="off" spellcheck="false" autofocus>
        <div class="ai-settings-actions">
          <button class="button button-secondary" type="button" :disabled="!keyValue || testMutation.isPending.value" @click="startTest">{{ testMutation.isPending.value ? "正在测试…" : "先测试连接" }}</button>
          <button class="button button-primary" type="button" :disabled="!testSucceeded || !keyValue || saveMutation.isPending.value" @click="save">{{ saveMutation.isPending.value ? "正在保存…" : "保存并启用" }}</button>
          <button class="button button-quiet" type="button" @click="wipeKey">清空</button>
          <button class="button button-quiet" type="button" @click="closeKeyModal()">取消</button>
        </div>
      </section>
    </div>

    <div v-if="deleteOpen" class="ai-modal-backdrop" @mousedown.self="deleteOpen = false">
      <section class="ai-modal" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <h2 id="delete-title">确认删除 DeepSeek 连接</h2>
        <p>删除后，AI 任务将暂停，已有内容和审计记录不会被删除。</p>
        <div class="ai-settings-actions">
          <button class="button button-danger" type="button" :disabled="deleteMutation.isPending.value" @click="deleteMutation.mutate()">{{ deleteMutation.isPending.value ? "正在删除…" : "确认删除" }}</button>
          <button class="button button-secondary" type="button" @click="deleteOpen = false">保留连接</button>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.ai-settings-page{min-width:0}.ai-settings-hero{display:flex;align-items:center;justify-content:space-between;gap:24px;border:1px solid var(--sg-line);border-left:5px solid var(--sg-brand);border-radius:var(--sg-radius-lg);background:white;padding:clamp(24px,5vw,42px);box-shadow:var(--sg-shadow-sm)}.ai-settings-hero h1{margin:0;font-size:clamp(1.8rem,4vw,2.7rem)}.ai-settings-hero p:last-child{max-width:650px;margin:12px 0 0;color:var(--sg-muted);line-height:1.65}.ai-connection-state{display:flex;min-width:270px;align-items:center;gap:14px;border:1px solid var(--sg-line);border-radius:var(--sg-radius-md);background:var(--sg-canvas);padding:16px}.ai-connection-state.is-connected{border-color:#a9d8ba;background:var(--sg-status-success-tint);color:var(--sg-status-success)}.ai-connection-state .app-icon{width:28px;height:28px;flex:none}.ai-connection-state strong,.ai-connection-state span{display:block}.ai-connection-state span{margin-top:4px;font-size:.82rem}.ai-settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.ai-settings-card{min-width:0}.ai-settings-card h2{margin:0}.ai-settings-card>.muted{line-height:1.65}.section-heading>.app-icon{width:28px;height:28px;color:var(--sg-brand)}.field-label,.ai-limit-grid label{display:grid;gap:7px;margin-top:18px;font-weight:700}.text-input{width:100%;min-height:44px;border:1px solid #b9c6d3;border-radius:var(--sg-radius-sm);background:white;padding:10px 12px;color:var(--sg-ink)}.field-help{margin:8px 0 0;color:var(--sg-muted);font-size:.86rem;line-height:1.5}.ai-settings-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}.button-danger{border-color:var(--sg-danger);background:white;color:var(--sg-danger)}.ai-routing-list{display:grid;gap:14px;margin:20px 0 0;padding:0;list-style:none}.ai-routing-list li{display:flex;gap:12px;border-radius:var(--sg-radius-sm);background:var(--sg-brand-soft);padding:14px;color:var(--sg-brand)}.ai-routing-list .app-icon{width:22px;height:22px;flex:none}.ai-routing-list strong,.ai-routing-list small{display:block}.ai-routing-list small{margin-top:4px;color:var(--sg-muted);line-height:1.45}.ai-limit-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 14px}.ai-settings-usage{grid-column:1/-1}.ai-settings-alert,.ai-settings-status{margin:0;border-radius:var(--sg-radius-sm);padding:14px 16px}.ai-settings-alert{border:1px solid #e7c471;background:var(--sg-status-warning-tint);color:#6a4b00}.ai-settings-status{background:var(--sg-status-success-tint);color:var(--sg-status-success)}.ai-modal-backdrop{position:fixed;inset:0;z-index:80;display:grid;place-items:center;background:rgb(23 34 49 / 48%);padding:18px}.ai-modal{width:min(100%,540px);max-height:calc(100vh - 36px);overflow:auto;border-radius:var(--sg-radius-lg);background:white;padding:clamp(22px,5vw,32px);box-shadow:var(--sg-shadow)}.ai-modal h2{margin:0}.ai-modal>p{color:var(--sg-muted);line-height:1.6}@media(max-width:720px){.ai-settings-hero{align-items:stretch;flex-direction:column}.ai-connection-state{min-width:0}.ai-settings-grid{grid-template-columns:1fr}.ai-settings-usage{grid-column:auto}.ai-limit-grid{grid-template-columns:1fr}.ai-settings-actions>.button{width:100%;min-height:44px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style>
