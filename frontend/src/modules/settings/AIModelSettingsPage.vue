<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref, watch } from "vue"
import { RouterLink } from "vue-router"

import { ApiError } from "../../api/client"
import AppIcon from "../../shared/components/AppIcon.vue"
import { currentUserQueryOptions } from "../auth/auth"
import {
  deleteAIProviderConfig,
  getAIProviderConfig,
  saveAIProviderConfig,
  testAIProviderConfig,
  type AIProviderConfig,
} from "./api"

const queryClient = useQueryClient()
const currentUser = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUser.data.value?.organization.id ?? "")
const configKey = computed(() => ["settings", organizationId.value, "ai-provider-config"])
const configQuery = useQuery({
  queryKey: configKey,
  queryFn: getAIProviderConfig,
  enabled: computed(() => Boolean(organizationId.value)),
})

const model = ref<AIProviderConfig["model"]>("deepseek-chat")
const apiKey = ref("")
const budgetUsd = ref("")
const notice = ref("")
const noticeTone = ref<"success" | "error" | "info">("info")

watch(configQuery.data, (config) => {
  if (!config) return
  model.value = config.model
  budgetUsd.value = config.daily_budget_micros === null
    ? ""
    : (config.daily_budget_micros / 1_000_000).toFixed(6)
}, { immediate: true })

function safeError(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.userMessage : fallback
}

function budgetMicros(): number | null {
  if (!budgetUsd.value.trim()) return null
  const value = Number(budgetUsd.value)
  return Number.isFinite(value) && value > 0 ? Math.round(value * 1_000_000) : null
}

function storeConfig(config: AIProviderConfig): void {
  queryClient.setQueryData(configKey.value, config)
}

const saveMutation = useMutation({
  mutationFn: () => saveAIProviderConfig({
    provider: "deepseek",
    model: model.value,
    enabled: configQuery.data.value?.enabled ?? true,
    daily_budget_micros: budgetMicros(),
    ...(apiKey.value.trim() ? { api_key: apiKey.value.trim() } : {}),
  }),
  onSuccess: (config) => {
    apiKey.value = ""
    storeConfig(config)
    noticeTone.value = "success"
    notice.value = "配置已安全保存。"
  },
  onError: (error) => {
    apiKey.value = ""
    noticeTone.value = "error"
    notice.value = safeError(error, "配置保存失败，请检查后重试。")
  },
})

const testMutation = useMutation({
  mutationFn: testAIProviderConfig,
  onSuccess: (result) => {
    apiKey.value = ""
    noticeTone.value = "success"
    notice.value = `连接成功 · ${Math.round(result.latency_ms)} ms`
    void configQuery.refetch()
  },
  onError: (error) => {
    apiKey.value = ""
    noticeTone.value = "error"
    notice.value = safeError(error, "连接失败，请检查配置。")
    void configQuery.refetch()
  },
})

const toggleMutation = useMutation({
  mutationFn: (enabled: boolean) => saveAIProviderConfig({
    provider: "deepseek",
    model: model.value,
    enabled,
    daily_budget_micros: budgetMicros(),
  }),
  onSuccess: (config) => {
    storeConfig(config)
    noticeTone.value = "success"
    notice.value = config.enabled ? "真实模型已启用。" : "真实模型已停用，不会发起真实请求。"
  },
  onError: (error) => {
    noticeTone.value = "error"
    notice.value = safeError(error, "状态更新失败，请重试。")
  },
})

const deleteMutation = useMutation({
  mutationFn: deleteAIProviderConfig,
  onSuccess: async () => {
    apiKey.value = ""
    await configQuery.refetch()
    noticeTone.value = "success"
    notice.value = "密钥已删除，真实模型已停用。"
  },
  onError: (error) => {
    noticeTone.value = "error"
    notice.value = safeError(error, "密钥删除失败，请重试。")
  },
})

function deleteKey(): void {
  if (!window.confirm("确认删除 DeepSeek API Key？删除后真实模型会立即停用。")) return
  deleteMutation.mutate()
}

const config = computed(() => configQuery.data.value)
const statusLabel = computed(() => {
  if (configQuery.isPending.value) return "正在读取配置"
  if (configQuery.isError.value) return "配置暂时无法读取"
  if (!config.value?.configured) return "需要配置 API Key"
  if (!config.value.enabled) return "真实模型已停用"
  if (config.value.last_error_code === "budget_exceeded") return "今日预估预算已用尽"
  if (config.value.last_error_code) return "连接需要处理"
  return "已启用真实模型"
})
const busy = computed(() => (
  saveMutation.isPending.value || testMutation.isPending.value
  || toggleMutation.isPending.value || deleteMutation.isPending.value
))
const formatUsd = (micros: number | null | undefined) => (
  micros === null || micros === undefined ? "未设置" : `$${(micros / 1_000_000).toFixed(6)}`
)
</script>

<template>
  <main class="ai-settings-page">
    <header class="ai-settings-heading">
      <div>
        <p class="eyebrow">管理员设置</p>
        <h1>AI 模型</h1>
        <p>连接组织自己的 DeepSeek 官方 API，并用预估费用上限控制每日调用。</p>
      </div>
      <RouterLink class="button button-quiet" to="/settings">返回设置中心</RouterLink>
    </header>

    <p v-if="notice" class="ai-notice" :class="`is-${noticeTone}`" role="status">{{ notice }}</p>
    <p v-if="configQuery.isError.value" class="ai-notice is-error" role="alert">配置读取失败，请稍后重试。</p>

    <div class="ai-settings-grid">
      <section class="ai-config-card" aria-labelledby="ai-config-title">
        <div class="card-title-row">
          <span class="card-icon"><AppIcon name="bot" :size="22" /></span>
          <div>
            <h2 id="ai-config-title">模型配置</h2>
            <p>密钥仅加密保存在服务器；保存后此页面不会回显。</p>
          </div>
        </div>

        <form aria-label="AI 模型配置" @submit.prevent="saveMutation.mutate()">
          <label>
            <span>Provider</span>
            <input aria-label="Provider" value="deepseek" readonly>
          </label>
          <label>
            <span>模型</span>
            <select v-model="model" aria-label="模型">
              <option value="deepseek-chat">deepseek-chat</option>
              <option value="deepseek-reasoner">deepseek-reasoner</option>
            </select>
          </label>
          <label class="full-field">
            <span>API Key</span>
            <input v-model="apiKey" aria-label="API Key" type="password" autocomplete="new-password" placeholder="输入新密钥；留空则保留现有密钥">
            <small>不会显示已保存密钥，也不会写入浏览器存储。</small>
          </label>
          <label class="full-field">
            <span>每日预估费用上限（USD）</span>
            <input v-model="budgetUsd" aria-label="每日预估费用上限（USD）" type="number" min="0.000001" step="0.000001" placeholder="留空表示不设置费用上限">
          </label>

          <div class="form-actions full-field">
            <button class="button" type="submit" :disabled="busy">{{ saveMutation.isPending.value ? "正在保存…" : "保存配置" }}</button>
            <button class="button button-quiet" type="button" :disabled="busy || !config?.configured" @click="testMutation.mutate()">
              {{ testMutation.isPending.value ? "正在测试…" : "测试连接" }}
            </button>
          </div>
        </form>
      </section>

      <aside class="ai-status-card" aria-label="AI 模型状态">
        <div class="status-orb"><AppIcon name="sparkles" :size="26" /></div>
        <p class="eyebrow">当前运行状态</p>
        <h2>{{ statusLabel }}</h2>
        <p class="status-copy">{{ config?.enabled ? "Agent 可在审批边界内使用真实模型。" : "当前不会发起任何真实模型请求。" }}</p>

        <dl>
          <div><dt>当前模型</dt><dd>{{ config?.model ?? model }}</dd></div>
          <div><dt>每日上限</dt><dd>{{ formatUsd(config?.daily_budget_micros) }} / 天</dd></div>
          <div><dt>今日已用（预估）</dt><dd>{{ formatUsd(config?.daily_spent_micros) }}</dd></div>
          <div><dt>计价版本</dt><dd>{{ config?.price_table_version ?? "—" }}</dd></div>
        </dl>

        <div class="status-actions">
          <button
            v-if="config?.configured"
            class="button button-quiet"
            type="button"
            :disabled="busy"
            @click="toggleMutation.mutate(!config.enabled)"
          >
            {{ config.enabled ? "停用真实模型" : "启用真实模型" }}
          </button>
          <button v-if="config?.configured" class="danger-action" type="button" :disabled="busy" @click="deleteKey">删除密钥</button>
        </div>
        <p class="cost-note">费用为按当前价格表与模型返回 Token 计算的估算值，实际账单以 DeepSeek 为准。</p>
      </aside>
    </div>
  </main>
</template>

<style scoped>
.ai-settings-page { display: grid; gap: 20px; }
.ai-settings-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.ai-settings-heading h1 { margin: 3px 0 8px; color: var(--sg-ink); }
.ai-settings-heading p { margin: 0; color: var(--sg-muted); }
.ai-settings-grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(300px, .8fr); gap: 18px; }
.ai-config-card, .ai-status-card { border: 1px solid var(--sg-line); border-radius: 18px; background: #fff; box-shadow: var(--sg-shadow); padding: 24px; }
.card-title-row { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; }
.card-title-row h2, .ai-status-card h2 { margin: 0 0 5px; color: var(--sg-ink); }
.card-title-row p, .status-copy { margin: 0; color: var(--sg-muted); font-size: .82rem; line-height: 1.5; }
.card-icon, .status-orb { display: grid; place-items: center; width: 46px; height: 46px; border-radius: 14px; background: var(--sg-brand-soft); color: var(--sg-brand); }
form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
label { display: grid; gap: 7px; color: var(--sg-ink); font-size: .78rem; font-weight: 800; }
label small { color: var(--sg-muted); font-size: .69rem; font-weight: 500; }
input, select { width: 100%; box-sizing: border-box; border: 1px solid var(--sg-line); border-radius: 10px; background: #fbfdff; padding: 11px 12px; color: var(--sg-ink); }
input:focus, select:focus { outline: 3px solid rgb(22 135 255 / 16%); border-color: var(--sg-brand); }
input[readonly] { background: var(--sg-brand-soft); color: var(--sg-brand-strong); font-weight: 800; }
.full-field { grid-column: 1 / -1; }
.form-actions, .status-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.ai-status-card { position: relative; overflow: hidden; }
.ai-status-card::after { content: ""; position: absolute; width: 180px; height: 180px; right: -80px; top: -80px; border-radius: 50%; background: rgb(22 135 255 / 8%); pointer-events: none; }
.status-orb { margin-bottom: 20px; background: linear-gradient(145deg, #1687ff, #43b8ff); color: #fff; box-shadow: 0 10px 24px rgb(22 135 255 / 24%); }
.ai-status-card dl { display: grid; gap: 0; margin: 22px 0; }
.ai-status-card dl div { display: flex; justify-content: space-between; gap: 16px; border-top: 1px solid var(--sg-line); padding: 12px 0; }
.ai-status-card dt { color: var(--sg-muted); font-size: .73rem; }
.ai-status-card dd { margin: 0; color: var(--sg-ink); font-size: .75rem; font-weight: 800; text-align: right; }
.danger-action { border: 0; background: transparent; padding: 9px 4px; color: var(--sg-danger); font-weight: 800; cursor: pointer; }
.cost-note { margin: 18px 0 0; border-radius: 10px; background: var(--sg-brand-soft); padding: 11px; color: var(--sg-muted); font-size: .69rem; line-height: 1.5; }
.ai-notice { margin: 0; border-radius: 11px; padding: 11px 14px; font-size: .8rem; }
.ai-notice.is-success { background: #e9fbf4; color: #19795b; }
.ai-notice.is-error { background: #fff0f0; color: #b43838; }
.ai-notice.is-info { background: var(--sg-brand-soft); color: var(--sg-brand-strong); }
@media (max-width: 900px) { .ai-settings-grid { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .ai-settings-heading, form { display: grid; grid-template-columns: 1fr; }.full-field { grid-column: auto; }.ai-config-card, .ai-status-card { padding: 18px; } }
</style>
