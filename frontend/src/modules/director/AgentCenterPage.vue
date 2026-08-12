<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"
import { RouterLink } from "vue-router"

import AppIcon, { type AppIconName } from "../../shared/components/AppIcon.vue"
import { aiProviderConfigurationQueryOptions } from "../aiSettings/api"
import { getChannelSummary, analyticsKeys } from "../analytics/api"
import { currentUserQueryOptions } from "../auth/auth"
import { directorKeys, getCockpit } from "./api"

type Readiness = "可用" | "需要配置" | "后续批次接入" | "正在核对"
type AgentCard = {
  name: string
  responsibility: string
  readiness: Readiness
  detail: string
  action: string
  to: string
  icon: AppIconName
}

const currentUser = useQuery(currentUserQueryOptions())
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

const aiConnected = computed(() => aiConfiguration.isSuccess.value
  && aiConfiguration.data.value?.connection_state === "CONNECTED")

function permissionReady(required: string[]): boolean {
  return required.every(has)
}

const cards = computed<AgentCard[]>(() => {
  const directorPending = cockpit.isPending.value && canReadDirector.value
  const aiPending = aiConfiguration.isPending.value && canManageCredentials.value
  const analyticsPending = analytics.isPending.value && canReadAnalytics.value
  const contentPermissions = permissionReady(["content.read", "campaigns.read"])
  const leadPermissions = permissionReady(["leads.read", "sources.manage"])
  const analyticsHasRecords = analytics.isSuccess.value && (analytics.data.value?.count ?? 0) > 0
  return [
    {
      name: "Growth Director", responsibility: "汇总今天需要人工决定的事项，并保留审批边界。",
      readiness: directorPending ? "正在核对" : cockpit.isSuccess.value ? "可用" : "需要配置",
      detail: cockpit.isSuccess.value ? "驾驶舱接口已可读取。" : "需要可读取的驾驶舱接口和权限。",
      action: "查看今天", to: "/", icon: "sparkles",
    },
    {
      name: "Content Agent", responsibility: "根据已确认的产品资料辅助生成推广内容。",
      readiness: aiPending ? "正在核对" : aiConnected.value && contentPermissions ? "可用" : "需要配置",
      detail: aiConnected.value && contentPermissions ? "DeepSeek 与内容读取能力均已就绪。" : "需要连接 DeepSeek 并授予内容读取权限。",
      action: canManageCredentials.value && !aiConnected.value ? "配置 DeepSeek" : "查看内容工作区",
      to: canManageCredentials.value && !aiConnected.value ? "/ai-settings" : "/content-factory", icon: "document",
    },
    {
      name: "Lead Agent", responsibility: "分析公开来源与客户信号，帮助筛选值得关注的机会。",
      readiness: aiPending ? "正在核对" : aiConnected.value && leadPermissions ? "可用" : "需要配置",
      detail: aiConnected.value && leadPermissions ? "DeepSeek、客户与来源权限均已就绪。" : "需要连接 DeepSeek 并授予客户及来源权限。",
      action: "查看客户机会", to: "/lead-radar", icon: "users",
    },
    {
      name: "AIEO Agent", responsibility: "帮助 AI 搜索服务正确理解公司实体、能力与证据。",
      readiness: "后续批次接入", detail: "设计已确认，后续批次接入",
      action: "检查产品资料", to: "/company-profile", icon: "globe",
    },
    {
      name: "Analytics Agent", responsibility: "基于真实跟踪记录解释推广效果并提出后续建议。",
      readiness: analyticsPending ? "正在核对" : canReadAnalytics.value && analyticsHasRecords ? "可用" : "需要配置",
      detail: analyticsHasRecords ? "已找到可用于分析的真实效果记录。" : "还没有可确认的效果记录，或当前账号无读取权限。",
      action: "查看效果", to: "/analytics", icon: "chart",
    },
  ]
})

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
        <RouterLink class="agent-action" :to="card.to">{{ card.action }}</RouterLink>
      </article>
    </section>
  </div>
</template>

<style scoped>
.agent-center{display:grid;gap:1.25rem}.agent-header{padding:1.25rem 1.35rem;border:1px solid var(--sg-line,#d8dee8);border-radius:1rem;background:linear-gradient(135deg,var(--sg-brand-soft,#eef6ff),#fff)}.agent-header h1{margin:.2rem 0}.agent-header p:last-child{max-width:52rem;margin-bottom:0;color:var(--sg-muted,#667085)}.agent-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.agent-card{display:grid;min-width:0;gap:1rem;padding:1.15rem;border:1px solid var(--sg-line,#d8dee8);border-radius:1rem;background:var(--sg-surface,#fff);box-shadow:0 8px 24px rgba(15,43,83,.05)}.agent-title{display:flex;align-items:flex-start;gap:.85rem}.agent-title h2{margin:0 0 .35rem;font-size:1.05rem}.agent-title p{margin:0;color:var(--sg-muted,#667085)}.agent-icon{display:grid;flex:0 0 2.5rem;width:2.5rem;height:2.5rem;place-items:center;border-radius:.75rem;background:var(--sg-brand-soft,#eef6ff);color:var(--sg-brand,#005ba8)}.agent-icon :deep(svg){width:1.2rem}.readiness-row{display:grid;gap:.45rem;color:var(--sg-muted,#667085)}.readiness{width:max-content;padding:.3rem .65rem;border-radius:999px;font-weight:700}.readiness-ready{background:#e9f8ef;color:#15703b}.readiness-setup{background:#fff4dc;color:#8a5600}.readiness-deferred{background:#eef1f5;color:#526071}.agent-action{width:max-content;color:var(--sg-brand,#005ba8);font-weight:700;text-decoration:none}.agent-action:hover{text-decoration:underline}@media(max-width:760px){.agent-grid{grid-template-columns:1fr}.agent-action{width:100%;padding:.65rem;text-align:center;border-radius:.65rem;background:var(--sg-brand-soft,#eef6ff)}}
</style>
