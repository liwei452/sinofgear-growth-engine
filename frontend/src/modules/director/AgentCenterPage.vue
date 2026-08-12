<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, watch } from "vue"
import { RouterLink } from "vue-router"

import AppIcon, { type AppIconName } from "../../shared/components/AppIcon.vue"
import { aiProviderConfigurationQueryOptions } from "../aiSettings/api"
import { getChannelSummary, analyticsKeys } from "../analytics/api"
import { currentUserQueryOptions } from "../auth/auth"
import { directorKeys, getCockpit } from "./api"

type AgentState = "ready" | "checking" | "unavailable" | "unauthorized" | "provider-configuration-required"
  | "permission-required" | "configuring" | "no-records" | "deferred"
type Readiness = "可用" | "需要配置" | "配置进行中" | "后续批次接入" | "正在核对" | "无权核对" | "暂时无法核对"
type RetryQuery = "director" | "provider" | "analytics"
type AgentAction =
  | { kind: "link"; label: string; to: string }
  | { kind: "retry"; label: string; query: RetryQuery }
  | { kind: "disabled"; label: string }
type AgentCard = {
  name: string
  responsibility: string
  readiness: Readiness
  detail: string
  action: AgentAction
  icon: AppIconName
}

const currentUser = useQuery(currentUserQueryOptions())
const queryClient = useQueryClient()
const organizationId = computed(() => currentUser.data.value?.organization.id ?? "")
const permissions = computed(() => currentUser.data.value?.membership.permissions ?? [])
const has = (permission: string) => permissions.value.includes(permission)
const canReadDirector = computed(() => has("director.read"))
const canManageCredentials = computed(() => has("credentials.manage"))
const canReadAnalytics = computed(() => has("tracking.read"))

const cockpit = useQuery(computed(() => ({
  queryKey: directorKeys.cockpit(organizationId.value),
  queryFn: ({ signal }: { signal: AbortSignal }) => getCockpit({ signal }),
  enabled: Boolean(organizationId.value) && canReadDirector.value,
  staleTime: 30_000,
})))
const aiConfiguration = useQuery(computed(() => aiProviderConfigurationQueryOptions(
  organizationId.value, canManageCredentials.value,
)))
const analytics = useQuery(computed(() => ({
  queryKey: analyticsKeys.summary(organizationId.value, {}),
  queryFn: ({ signal }: { signal: AbortSignal }) => getChannelSummary({}, { signal }),
  enabled: Boolean(organizationId.value) && canReadAnalytics.value,
  staleTime: 30_000,
})))

watch(canReadDirector, (allowed, wasAllowed) => {
  if (wasAllowed && !allowed && organizationId.value) {
    queryClient.cancelQueries({ queryKey: directorKeys.all(organizationId.value) })
    queryClient.removeQueries({ queryKey: directorKeys.all(organizationId.value) })
  }
})
watch(canReadAnalytics, (allowed, wasAllowed) => {
  if (wasAllowed && !allowed && organizationId.value) {
    queryClient.cancelQueries({ queryKey: analyticsKeys.all(organizationId.value) })
    queryClient.removeQueries({ queryKey: analyticsKeys.all(organizationId.value) })
  }
})

function permissionReady(required: string[]): boolean {
  return required.every(has)
}

function queryState(allowed: boolean, query: typeof cockpit): AgentState {
  if (!allowed) return "unauthorized"
  if (query.isPending.value) return "checking"
  if (query.isError.value) return "unavailable"
  return "ready"
}

function providerState(): AgentState {
  if (!canManageCredentials.value) return "unauthorized"
  if (aiConfiguration.isPending.value) return "checking"
  if (aiConfiguration.isError.value || !aiConfiguration.isSuccess.value) return "unavailable"
  if (aiConfiguration.data.value?.connection_state === "CONFIGURING") return "configuring"
  if (aiConfiguration.data.value?.connection_state !== "CONNECTED") return "provider-configuration-required"
  return "ready"
}

function cardAction(state: AgentState, readyLabel: string, readyTo: string, retryQuery: RetryQuery): AgentAction {
  if (state === "checking") return { kind: "disabled", label: "正在核对状态" }
  if (state === "unavailable") return { kind: "retry", label: "重新核对", query: retryQuery }
  if (state === "unauthorized" || state === "permission-required") return { kind: "disabled", label: "联系管理员" }
  if (state === "configuring") return { kind: "disabled", label: "等待配置完成" }
  if (state === "provider-configuration-required") return { kind: "link", label: "配置 DeepSeek", to: "/ai-settings" }
  return { kind: "link", label: readyLabel, to: readyTo }
}

const cards = computed<AgentCard[]>(() => {
  const contentPermissions = permissionReady(["content.read", "content.manage", "campaigns.read", "campaigns.manage"])
  const leadPermissions = permissionReady(["sources.read", "sources.manage", "leads.read", "leads.analyze"])
  const directorState = queryState(canReadDirector.value, cockpit)
  const provider = providerState()
  const contentState: AgentState = provider === "ready" ? contentPermissions ? "ready" : "permission-required" : provider
  const leadState: AgentState = provider === "ready" ? leadPermissions ? "ready" : "permission-required" : provider
  const analyticsQueryState = queryState(canReadAnalytics.value, analytics)
  const analyticsState: AgentState = analyticsQueryState === "ready" && (analytics.data.value?.count ?? 0) === 0
    ? "no-records" : analyticsQueryState
  const readiness = (state: AgentState): Readiness => ({
    ready: "可用", checking: "正在核对", unavailable: "暂时无法核对", unauthorized: "无权核对",
    "provider-configuration-required": "需要配置", "permission-required": "需要配置",
    configuring: "配置进行中", "no-records": "需要配置", deferred: "后续批次接入",
  })[state] as Readiness
  const providerDetail = (state: AgentState) => state === "checking" ? "正在核对 DeepSeek 连接状态。"
    : state === "unavailable" ? "DeepSeek 状态暂时无法读取，请重新核对。"
      : state === "unauthorized" ? "请联系管理员确认 DeepSeek 连接状态。"
        : state === "configuring" ? "正在配置 DeepSeek，请等待配置完成。"
          : state === "provider-configuration-required" ? "DeepSeek 尚未连接，需要管理员完成配置。"
            : "DeepSeek 连接已确认。"
  return [
    {
      name: "Growth Director", responsibility: "汇总今天需要人工决定的事项，并保留审批边界。",
      readiness: readiness(directorState),
      detail: directorState === "unauthorized" ? "当前账号无权读取驾驶舱，请联系管理员。" : directorState === "checking" ? "正在核对驾驶舱状态。" : directorState === "unavailable" ? "驾驶舱状态暂时无法读取，请重新核对。" : "驾驶舱接口已可读取。",
      action: cardAction(directorState, "查看今天", "/", "director"), icon: "sparkles",
    },
    {
      name: "Content Agent", responsibility: "根据已确认的产品资料辅助生成推广内容。",
      readiness: readiness(contentState),
      detail: contentState === "permission-required" ? "需要 content.manage、campaigns.manage 及相应读取权限。" : contentState === "ready" ? "DeepSeek 与内容生成权限均已就绪。" : providerDetail(contentState),
      action: cardAction(contentState, "查看内容工作区", "/content-factory", "provider"), icon: "document",
    },
    {
      name: "Lead Agent", responsibility: "分析公开来源与客户信号，帮助筛选值得关注的机会。",
      readiness: readiness(leadState),
      detail: leadState === "permission-required" ? "需要 leads.analyze、leads.read、sources.read 和 sources.manage 权限。" : leadState === "ready" ? "DeepSeek、客户分析与来源权限均已就绪。" : providerDetail(leadState),
      action: cardAction(leadState, "查看客户机会", "/lead-radar", "provider"), icon: "users",
    },
    {
      name: "AIEO Agent", responsibility: "帮助 AI 搜索服务正确理解公司实体、能力与证据。",
      readiness: "后续批次接入", detail: "设计已确认，后续批次接入",
      action: { kind: "link", label: "检查产品资料", to: "/company-profile" }, icon: "globe",
    },
    {
      name: "Analytics Agent", responsibility: "基于真实跟踪记录解释推广效果并提出后续建议。",
      readiness: readiness(analyticsState),
      detail: analyticsState === "unauthorized" ? "当前账号无权读取效果记录，请联系管理员。" : analyticsState === "checking" ? "正在核对效果记录状态。" : analyticsState === "unavailable" ? "效果记录暂时无法读取，请重新核对。" : analyticsState === "no-records" ? "还没有可确认的效果记录。" : "已找到可用于分析的真实效果记录。",
      action: cardAction(analyticsState, "查看效果", "/analytics", "analytics"), icon: "chart",
    },
  ]
})

function retry(card: AgentCard): void {
  if (card.action.kind !== "retry") return
  if (card.action.query === "director") void cockpit.refetch()
  if (card.action.query === "provider") void aiConfiguration.refetch()
  if (card.action.query === "analytics") void analytics.refetch()
}

function tone(readiness: Readiness): string {
  if (readiness === "可用") return "ready"
  if (readiness === "后续批次接入") return "deferred"
  return "setup"
}
</script>

<template>
  <div class="agent-center page-stack">
    <header class="agent-header">
      <div>
        <p class="eyebrow">管理员视图</p>
        <h1>AI Agent 中心</h1>
        <p>这里仅展示当前真实具备的能力与下一步配置，不代表后台自动调度已经开启。</p>
      </div>
    </header>

    <section class="agent-grid" aria-label="AI Agent 准备状态">
      <article v-for="card in cards" :key="card.name" class="agent-card">
        <div class="agent-title">
          <span class="agent-icon" aria-hidden="true"><AppIcon :name="card.icon" /></span>
          <div><h2>{{ card.name }}</h2><p>{{ card.responsibility }}</p></div>
        </div>
        <div class="readiness-row">
          <span class="readiness" :class="`readiness-${tone(card.readiness)}`">{{ card.readiness }}</span>
          <span>{{ card.detail }}</span>
        </div>
        <RouterLink v-if="card.action.kind === 'link'" class="agent-action" :to="card.action.to">{{ card.action.label }}</RouterLink>
        <button v-else-if="card.action.kind === 'retry'" class="agent-action agent-action-button" type="button" @click="retry(card)">{{ card.action.label }}</button>
        <span v-else class="agent-action agent-action-disabled" aria-disabled="true">{{ card.action.label }}</span>
      </article>
    </section>
  </div>
</template>

<style scoped>
.agent-center{display:grid;gap:1.25rem}.agent-header{padding:1.25rem 1.35rem;border:1px solid var(--sg-line,#d8dee8);border-radius:1rem;background:linear-gradient(135deg,var(--sg-brand-soft,#eef6ff),#fff)}.agent-header h1{margin:.2rem 0}.agent-header p:last-child{max-width:52rem;margin-bottom:0;color:var(--sg-muted,#667085)}.agent-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.agent-card{display:grid;min-width:0;gap:1rem;padding:1.15rem;border:1px solid var(--sg-line,#d8dee8);border-radius:1rem;background:var(--sg-surface,#fff);box-shadow:0 8px 24px rgba(15,43,83,.05)}.agent-title{display:flex;align-items:flex-start;gap:.85rem}.agent-title h2{margin:0 0 .35rem;font-size:1.05rem}.agent-title p{margin:0;color:var(--sg-muted,#667085)}.agent-icon{display:grid;flex:0 0 2.5rem;width:2.5rem;height:2.5rem;place-items:center;border-radius:.75rem;background:var(--sg-brand-soft,#eef6ff);color:var(--sg-brand,#005ba8)}.agent-icon :deep(svg){width:1.2rem}.readiness-row{display:grid;gap:.45rem;color:var(--sg-muted,#667085)}.readiness{width:max-content;padding:.3rem .65rem;border-radius:999px;font-weight:700}.readiness-ready{background:#e9f8ef;color:#15703b}.readiness-setup{background:#fff4dc;color:#8a5600}.readiness-deferred{background:#eef1f5;color:#526071}.agent-action{width:max-content;color:var(--sg-brand,#005ba8);font-weight:700;text-decoration:none}.agent-action:hover{text-decoration:underline}.agent-action-button{padding:0;border:0;background:transparent;cursor:pointer;font:inherit}.agent-action-disabled{color:var(--sg-muted,#667085);cursor:not-allowed}@media(max-width:760px){.agent-grid{grid-template-columns:1fr}.agent-action{width:100%;padding:.65rem;text-align:center;border-radius:.65rem;background:var(--sg-brand-soft,#eef6ff)}}
</style>
