<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"
import { RouterLink } from "vue-router"

import EmptyState from "../../shared/components/EmptyState.vue"
import WorkspaceHeader from "../../shared/components/WorkspaceHeader.vue"
import {
  addOpportunityFollowUp,
  createOpportunityDraft,
  growthQueryKeys,
  growthWorkspaceQueryOptions,
} from "../growth/api"
import { agentRunsQueryOptions } from "../growth/agentApi"
import { getProductAIStatus } from "../settings/api"
import TodayWorkInbox from "../workItems/TodayWorkInbox.vue"
import DashboardKpiStrip from "./DashboardKpiStrip.vue"
import DashboardSideRail, { type DashboardChannelIssue } from "./DashboardSideRail.vue"
import DashboardTrendCard from "./DashboardTrendCard.vue"
import TodayActionList from "./TodayActionList.vue"

type Opportunity = {
  id: string
  company: string
  country: string
  profile: string
  need: string
  summary: string
  source: string
  discovered: string
  intent: string
  evidence: string
  dataLabel: string
}

const queryClient = useQueryClient()
const workspaceQuery = useQuery(growthWorkspaceQueryOptions())
const agentRunsQuery = useQuery(agentRunsQueryOptions())
const providerQuery = useQuery({
  queryKey: ["ai", "provider-status"],
  queryFn: getProductAIStatus,
  staleTime: 15_000,
})
const locallyFollowed = ref(new Set<string>())
const actionError = ref("")
const draftFor = ref<{
  opportunity: Opportunity
  englishDraft: string
  chineseExplanation: string
} | null>(null)
const evidenceFor = ref(new Set<string>())

const countryLabels: Record<string, string> = {
  Germany: "德国", Italy: "意大利", Sweden: "瑞典", China: "中国", USA: "美国",
}
const channelNames = {
  FACEBOOK: "Facebook",
  INSTAGRAM: "Instagram",
  LINKEDIN: "LinkedIn",
  TIKTOK: "TikTok",
  YOUTUBE: "YouTube",
} as const

function isDemoLabel(value: string | undefined): boolean {
  return /demo|fake/i.test(value ?? "")
}

function recordedNumber(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key]
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null
}

const opportunities = computed<Opportunity[]>(() => {
  const workspace = workspaceQuery.data.value
  if (!workspace?.target_accounts.length) return []
  return workspace.target_accounts.filter((account) => !account.is_demo).flatMap((account) => {
    const signal = workspace.intent_signals
      .filter((candidate) => candidate.account_id === account.id && !isDemoLabel(candidate.data_label))
      .sort((left, right) => Date.parse(right.observed_at) - Date.parse(left.observed_at))[0]
    if (!signal) return []
    const confidence = signal?.confidence ?? 0
    return [{
      id: account.id,
      company: account.name,
      country: countryLabels[account.country] ?? account.country,
      profile: [account.industry || "行业待确认", account.employee_range ? `${account.employee_range} 人` : "规模待确认"].join(" · "),
      need: signal.evidence_text,
      summary: confidence >= 80
        ? "公开信号较强，建议人工核实采购范围、批量与时间。"
        : "当前证据有限，建议继续观察并补充可验证信息。",
      source: signal.source_label,
      discovered: new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(signal.observed_at)),
      intent: confidence >= 80 ? "高意向" : confidence >= 60 ? "中高意向" : "继续观察",
      evidence: signal.evidence_text,
      dataLabel: signal.data_label || account.data_label,
    }]
  })
})
const dashboardKpis = computed(() => {
  const workspace = workspaceQuery.data.value
  const runs = agentRunsQuery.data.value
  const recordedInquiries = (workspace?.metric_receipts ?? [])
    .filter(receipt => !receipt.is_demo)
    .map(receipt => recordedNumber(receipt.payload, "inquiries"))
    .filter((value): value is number => value !== null)
  return {
    opportunities: workspaceQuery.isSuccess.value ? opportunities.value.length : null,
    approvals: agentRunsQuery.isSuccess.value
      ? (runs ?? []).filter(run => run.status === "WAITING_APPROVAL").length
      : null,
    readyToPublish: workspaceQuery.isSuccess.value
      ? (workspace?.channel_packages ?? []).filter(item => !item.is_demo && item.status === "APPROVED").length
      : null,
    inquiries: recordedInquiries.length
      ? recordedInquiries.reduce((total, value) => total + value, 0)
      : null,
  }
})

const pendingRuns = computed(() => (agentRunsQuery.data.value ?? [])
  .filter(run => run.status === "WAITING_APPROVAL")
  .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
  .slice(0, 3))

const completedRuns = computed(() => (agentRunsQuery.data.value ?? [])
  .filter(run => run.status === "COMPLETED")
  .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
  .slice(0, 3))

const channelIssues = computed<DashboardChannelIssue[]>(() => {
  if (!workspaceQuery.isSuccess.value) return []
  const connectors = workspaceQuery.data.value?.connectors ?? []
  return Object.entries(channelNames).flatMap(([code, name]) => {
    const connection = connectors.find(item => item.channel === code)
    if (connection?.status === "CONNECTED" && connection.mode === "OFFICIAL") return []
    return [{
      code,
      name,
      status: connection?.connection_label || "未配置",
      recovery: connection?.recovery_action || "请管理员完成平台配置",
    }]
  })
})

const todayLabel = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric", month: "long", day: "numeric", weekday: "long",
}).format(new Date())
const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 9) return "早上好"
  if (hour < 12) return "上午好"
  if (hour < 18) return "下午好"
  return "晚上好"
})

const todayActions = computed(() => {
  const workspace = workspaceQuery.data.value
  const opportunityCount = opportunities.value.length
  const hasContent = (workspace?.channel_packages.length ?? 0) > 0
  const hasCompanyFacts = (workspace?.field_provenance.length ?? 0) > 0
  return [{
    id: "opportunities",
    icon: "users-round" as const,
    title: opportunityCount ? "跟进新采购机会" : "发现潜在客户",
    description: opportunityCount ? "先核实证据最完整的企业，再决定是否触达。" : "选择市场或导入有合法来源的企业名单。",
    count: opportunityCount || undefined,
    to: "/opportunities",
    tone: "primary" as const,
  }, {
    id: "content",
    icon: "sparkles" as const,
    title: hasContent ? "检查待发布内容" : "创建第一批专业内容",
    description: hasContent ? "核对事实、平台版本和人工审核状态。" : "从已确认的公司和产品事实生成内容。",
    to: hasContent ? "/reviews" : "/content-factory",
    tone: "accent" as const,
  }, {
    id: "company",
    icon: "building-2" as const,
    title: hasCompanyFacts ? "维护公司事实" : "补充公司事实",
    description: "完善可验证的能力、产品和交付信息，供 Agent 安全调用。",
    to: "/company",
    tone: "neutral" as const,
  }]
})

const persistedFollowed = computed(() => new Set(
  (workspaceQuery.data.value?.follow_ups ?? []).map((item) => item.account_id),
))

function isFollowed(id: string): boolean {
  return locallyFollowed.value.has(id) || persistedFollowed.value.has(id)
}

const followUpMutation = useMutation({
  mutationFn: addOpportunityFollowUp,
  onSuccess: async (_result, accountId) => {
    locallyFollowed.value = new Set([...locallyFollowed.value, accountId])
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => { actionError.value = "暂时无法加入跟进，请稍后重试。" },
})

const draftMutation = useMutation({ mutationFn: createOpportunityDraft })

async function addFollowUp(id: string): Promise<void> {
  actionError.value = ""
  if (!workspaceQuery.data.value?.target_accounts.some((account) => account.id === id && !account.is_demo)) return
  await followUpMutation.mutateAsync(id).catch(() => undefined)
}

async function generateDraft(opportunity: Opportunity): Promise<void> {
  actionError.value = ""
  if (!workspaceQuery.data.value?.target_accounts.some((account) => account.id === opportunity.id && !account.is_demo)) return
  try {
    const draft = await draftMutation.mutateAsync(opportunity.id)
    draftFor.value = {
      opportunity,
      englishDraft: draft["English draft"],
      chineseExplanation: draft["Chinese explanation"],
    }
  } catch {
    actionError.value = "联系草稿暂时无法生成，请稍后重试。"
  }
}

function toggleEvidence(id: string) {
  const next = new Set(evidenceFor.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  evidenceFor.value = next
}
</script>

<template>
  <div class="today-page">
    <WorkspaceHeader
      :eyebrow="todayLabel"
      :title="`${greeting}，今天先处理最重要的增长任务`"
      description="先完成需要你判断的事项；所有数量均来自已保存、可追溯的数据。"
    />

    <DashboardKpiStrip
      :opportunities="dashboardKpis.opportunities"
      :approvals="dashboardKpis.approvals"
      :ready-to-publish="dashboardKpis.readyToPublish"
      :inquiries="dashboardKpis.inquiries"
    />

    <p v-if="workspaceQuery.isPending.value" class="workspace-state" role="status">正在读取可持久化工作区…</p>
    <p v-else-if="workspaceQuery.isError.value" class="workspace-state" role="alert">暂时无法读取工作区，请稍后重试；页面不会使用演示数据替代。</p>
    <p v-if="actionError" class="workspace-state action-error" role="alert">{{ actionError }}</p>

    <div class="dashboard-workbench">
      <div class="dashboard-main">
        <TodayWorkInbox />
        <TodayActionList :items="todayActions" />

        <section class="workspace-card opportunities-panel" aria-labelledby="today-opportunities">
          <div class="panel-heading">
            <div>
              <h2 id="today-opportunities">今天发现的采购机会</h2>
              <p>按证据完整度和当前需求排序，不等同于已确认采购。</p>
            </div>
            <RouterLink to="/opportunities">查看全部</RouterLink>
          </div>

          <div v-if="opportunities.length" class="opportunity-list">
            <article
              v-for="opportunity in opportunities.slice(0, 5)"
              :key="opportunity.id"
              class="opportunity-card"
              :aria-label="`${opportunity.company} 采购机会`"
            >
              <div class="company-block">
                <span class="company-avatar" aria-hidden="true">{{ opportunity.company.slice(0, 1) }}</span>
                <strong>{{ opportunity.company }}</strong>
                <span>{{ opportunity.country }}</span>
                <span>{{ opportunity.profile }}</span>
              </div>
              <div class="signal-block">
                <div class="signal-topline">
                  <span class="demo-badge">{{ opportunity.dataLabel }}</span>
                  <span class="intent-badge">{{ opportunity.intent }}</span>
                </div>
                <h3>{{ opportunity.need }}</h3>
                <p>{{ opportunity.summary }}</p>
                <dl class="signal-meta">
                  <div><dt>信号来源</dt><dd>{{ opportunity.source }}</dd></div>
                  <div><dt>发现时间</dt><dd>{{ opportunity.discovered }}</dd></div>
                </dl>
                <div class="opportunity-actions">
                  <button
                    class="button button-primary"
                    type="button"
                    :disabled="isFollowed(opportunity.id) || followUpMutation.isPending.value"
                    @click="addFollowUp(opportunity.id)"
                  >
                    {{ isFollowed(opportunity.id) ? "已加入跟进" : "加入跟进" }}
                  </button>
                  <button
                    class="button button-secondary" type="button"
                    :disabled="draftMutation.isPending.value" @click="generateDraft(opportunity)"
                  >
                    {{ draftMutation.isPending.value ? "正在生成…" : "生成联系草稿" }}
                  </button>
                  <button class="evidence-button" type="button" @click="toggleEvidence(opportunity.id)">
                    {{ evidenceFor.has(opportunity.id) ? "收起证据" : "查看证据" }}
                  </button>
                </div>
                <div
                  v-if="evidenceFor.has(opportunity.id)"
                  class="evidence-box"
                  role="region"
                  :aria-label="`${opportunity.company} 原始证据`"
                >
                  <strong>原始证据摘要</strong>
                  <p>{{ opportunity.evidence }}</p>
                  <p>完整来源、观察时间与许可信息请在客户机会页复核。</p>
                </div>
              </div>
            </article>
          </div>
          <EmptyState
            v-else
            icon="users-round"
            title="今天还没有已验证的采购机会"
            description="只有带真实来源与观察时间、并通过人工核实的需求信号才会出现在这里。"
          >
            <RouterLink class="button button-primary" to="/opportunities">选择市场或导入合法名单</RouterLink>
          </EmptyState>
        </section>

        <DashboardTrendCard :receipts="workspaceQuery.data.value?.metric_receipts ?? []" />
      </div>

      <DashboardSideRail
        :model-status="providerQuery.data.value ?? null"
        :pending-runs="pendingRuns"
        :channel-issues="channelIssues"
        :completed-runs="completedRuns"
      />
    </div>

    <div v-if="draftFor" class="modal-backdrop" @click.self="draftFor = null">
      <section class="draft-dialog" role="dialog" aria-modal="true" aria-labelledby="draft-title">
        <span class="demo-badge">{{ draftFor.opportunity.dataLabel }}</span>
        <h2 id="draft-title">联系草稿</h2>
        <p class="safe-note">草稿不会自动发送，请人工核对事实和联系人后再自行使用。</p>
        <h3>English draft</h3>
        <p>{{ draftFor.englishDraft }}</p>
        <h3>中文说明</h3>
        <p>{{ draftFor.chineseExplanation }}</p>
        <button class="button button-secondary" type="button" @click="draftFor = null">关闭</button>
      </section>
    </div>
  </div>
</template>

<style scoped>
.today-page { display: grid; gap: 22px; }
.panel-heading, .signal-topline, .opportunity-actions { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.panel-heading p { margin: 7px 0 0; color: var(--sg-muted); }
.demo-badge, .intent-badge { display: inline-flex; border-radius: 999px; padding: 5px 9px; font-size: .72rem; font-weight: 800; white-space: nowrap; }
.demo-badge { background: #eef2f6; color: #4f5d6c; }
.intent-badge { background: #e7f8ed; color: #14733c; }
.dashboard-workbench { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); gap: 20px; align-items: start; }
.dashboard-main { display: grid; min-width: 0; gap: 18px; }
.workspace-card { border: 1px solid var(--sg-line); border-radius: 14px; background: white; padding: 22px; box-shadow: 0 3px 16px rgb(23 34 49 / 4%); }
.workspace-empty { display: grid; gap: 10px; justify-items: start; border: 1px dashed var(--sg-line); border-radius: 12px; padding: 20px; background: #fbfcfd; }
.workspace-empty h3, .workspace-empty p { margin: 0; }.workspace-empty p { color: var(--sg-muted); line-height: 1.6; }
.panel-heading { align-items: flex-start; border-bottom: 1px solid var(--sg-line); padding-bottom: 16px; }
.panel-heading h2 { margin: 0; font-size: 1.1rem; }
.panel-heading a { color: var(--sg-brand); font-weight: 750; text-decoration: none; }
.opportunity-list, .insight-column { display: grid; gap: 16px; }
.opportunity-list { margin-top: 16px; }
.opportunity-card { display: grid; grid-template-columns: 150px 1fr; gap: 20px; border: 1px solid var(--sg-line); border-radius: 12px; padding: 18px; }
.company-block { display: grid; align-content: start; gap: 6px; border-right: 1px solid var(--sg-line); padding-right: 18px; color: var(--sg-muted); font-size: .875rem; }
.company-block strong { color: var(--sg-ink); font-size: .95rem; }
.company-avatar { display: grid; width: 44px; height: 44px; place-items: center; margin-bottom: 6px; border-radius: 50%; background: var(--sg-brand-soft); color: var(--sg-brand); font-weight: 900; }
.signal-block h3 { margin: 12px 0 8px; font-size: 1rem; }
.signal-block > p { margin: 0; color: var(--sg-muted); line-height: 1.6; }
.signal-meta { display: flex; flex-wrap: wrap; gap: 18px; margin: 14px 0; }
.signal-meta div { display: grid; gap: 3px; }
.signal-meta dt { color: var(--sg-muted); font-size: .72rem; }
.signal-meta dd { margin: 0; font-size: .875rem; font-weight: 700; }
.opportunity-actions { justify-content: flex-start; flex-wrap: wrap; }
.evidence-button { min-height: 44px; border: 0; background: transparent; color: var(--sg-brand); font-weight: 750; cursor: pointer; }
.evidence-box { margin-top: 14px; border-left: 3px solid var(--sg-brand); border-radius: 6px; background: #f6f9fc; padding: 12px 14px; }
.evidence-box p { margin: 5px 0 0; font-size: .875rem; line-height: 1.55; }
.safe-note { margin: 9px 0 0; color: var(--sg-muted); font-size: .875rem; text-align: center; }
.channel-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 9px; margin-top: 16px; }
.channel-grid article { min-width: 0; border: 1px solid var(--sg-line); border-radius: 10px; padding: 11px; }
.channel-grid article > strong { font-size: .8rem; }
.channel-grid p { margin: 10px 0 4px; color: var(--sg-muted); font-size: .72rem; }
.channel-grid p b { display: block; margin-top: 3px; color: var(--sg-ink); font-size: 1rem; }
.channel-grid article > span { color: #0c8a55; font-size: .75rem; font-weight: 800; }
.modal-backdrop { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; background: rgb(17 31 47 / 48%); padding: 20px; }
.draft-dialog { width: min(100%, 620px); max-height: 90vh; overflow-y: auto; border-radius: 14px; background: white; padding: 26px; box-shadow: var(--sg-shadow); }
.draft-dialog h2 { margin: 10px 0 0; }.draft-dialog h3 { margin: 20px 0 6px; font-size: .95rem; }.draft-dialog p { line-height: 1.65; }.draft-dialog .safe-note { text-align: left; }
@media (max-width: 1100px) { .dashboard-workbench { grid-template-columns: 1fr; } }
@media (max-width: 680px) { .panel-heading { align-items: flex-start; flex-direction: column; }.workspace-card { padding: 16px; }.opportunity-card { grid-template-columns: 1fr; }.company-block { grid-template-columns: auto 1fr; border-right: 0; border-bottom: 1px solid var(--sg-line); padding: 0 0 14px; }.company-avatar { grid-row: span 3; }.knowledge-grid { grid-template-columns: 1fr; }.channel-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
