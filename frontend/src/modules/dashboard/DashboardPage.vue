<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"
import { RouterLink, useRouter } from "vue-router"

import { currentUserQueryOptions } from "../auth/auth"
import { getChannelSummary } from "../analytics/api"
import {
  listJobs, listMasterContents, listPlatformContents, type Job, type JobStatus,
} from "../content/api"
import { listLeadCandidates } from "../leads/api"
import { ordinaryScoreBand, ordinaryStatus } from "../../shared/presentation/ordinary"
import ActivityRow from "./components/ActivityRow.vue"
import DecisionCard from "./components/DecisionCard.vue"
import MetricCard from "./components/MetricCard.vue"

const router = useRouter()
const currentUserQuery = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUserQuery.data.value?.organization.id ?? "")
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const has = (permission: string): boolean => permissions.value.includes(permission)

const canReadLeads = computed(() => has("leads.read"))
const canReviewLeads = computed(() => has("leads.review"))
const canDecideLeads = computed(() => canReadLeads.value && canReviewLeads.value)
const canDecideContent = computed(() => has("content.read") && has("content.review"))
const canReadJobs = computed(() => has("jobs.read"))
const canReadAnalytics = computed(() => has("tracking.read"))

const isoDate = (date: Date): string => {
  const two = (value: number) => String(value).padStart(2, "0")
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}`
}
const recentResultsEnd = new Date()
const recentResultsStart = new Date(recentResultsEnd)
recentResultsStart.setDate(recentResultsStart.getDate() - 29)
const recentResultsFilters = {
  start: isoDate(recentResultsStart),
  end: isoDate(recentResultsEnd),
  limit: "5",
  offset: "0",
}

type ActiveJobStatus = Extract<JobStatus, "QUEUED" | "RUNNING" | "RETRY_QUEUED">

const dashboardKeys = {
  decisions: (organization: string) => ["dashboard", organization, "decisions"] as const,
  activeJobs: (organization: string, status: ActiveJobStatus) =>
    ["dashboard", organization, "active-jobs", status] as const,
  masterReviews: (organization: string) => ["dashboard", organization, "master-reviews"] as const,
  platformReviews: (organization: string) => ["dashboard", organization, "platform-reviews"] as const,
  recentResults: (organization: string) => ["dashboard", organization, "recent-results"] as const,
}

const decisionsQuery = useQuery({
  queryKey: computed(() => dashboardKeys.decisions(organizationId.value)),
  queryFn: ({ signal }) => listLeadCandidates({ review_state: "UNREVIEWED", page_size: 5 }, { signal }),
  enabled: computed(() => Boolean(organizationId.value) && canDecideLeads.value),
  retry: false,
})
const masterReviewsQuery = useQuery({
  queryKey: computed(() => dashboardKeys.masterReviews(organizationId.value)),
  queryFn: ({ signal }) => listMasterContents({ status: "IN_REVIEW", page_size: 5 }, { signal }),
  enabled: computed(() => Boolean(organizationId.value) && canDecideContent.value),
  retry: false,
})
const platformReviewsQuery = useQuery({
  queryKey: computed(() => dashboardKeys.platformReviews(organizationId.value)),
  queryFn: ({ signal }) => listPlatformContents({ status: "IN_REVIEW", page_size: 5 }, { signal }),
  enabled: computed(() => Boolean(organizationId.value) && canDecideContent.value),
  retry: false,
})
const queuedJobsQuery = useQuery({
  queryKey: computed(() => dashboardKeys.activeJobs(organizationId.value, "QUEUED")),
  queryFn: ({ signal }) => listJobs({ status: "QUEUED" }, { signal }),
  enabled: computed(() => Boolean(organizationId.value) && canReadJobs.value),
  retry: false,
})
const runningJobsQuery = useQuery({
  queryKey: computed(() => dashboardKeys.activeJobs(organizationId.value, "RUNNING")),
  queryFn: ({ signal }) => listJobs({ status: "RUNNING" }, { signal }),
  enabled: computed(() => Boolean(organizationId.value) && canReadJobs.value),
  retry: false,
})
const retryQueuedJobsQuery = useQuery({
  queryKey: computed(() => dashboardKeys.activeJobs(organizationId.value, "RETRY_QUEUED")),
  queryFn: ({ signal }) => listJobs({ status: "RETRY_QUEUED" }, { signal }),
  enabled: computed(() => Boolean(organizationId.value) && canReadJobs.value),
  retry: false,
})
const recentResultsQuery = useQuery({
  queryKey: computed(() => dashboardKeys.recentResults(organizationId.value)),
  queryFn: ({ signal }) => getChannelSummary(recentResultsFilters, { signal }),
  enabled: computed(() => Boolean(organizationId.value) && canReadAnalytics.value),
  retry: false,
})

type DecisionDestination = "lead" | "review"
type DashboardDecision = {
  id: string
  title: string
  explanation: string
  statusLabel: string
  statusTone: "warning"
  destination: DecisionDestination
  priority: number
  updatedAt: string
}

const leadBandPriority: Record<string, number> = { HIGH: 40, WATCH: 20, OBSERVE: 10, LOW: 0 }
const allDecisions = computed<DashboardDecision[]>(() => {
  const leads: DashboardDecision[] = (canDecideLeads.value ? decisionsQuery.data.value?.results ?? [] : []).map((candidate) => ({
    id: `lead:${candidate.id}`,
    title: `判断${candidate.company_name}是否值得联系`,
    explanation: candidate.latest_score === null
      ? "这条客户机会尚未完成人工判断；现在确认可让后续跟进继续。"
      : `AI 给出的参考分数为 ${candidate.latest_score}（${ordinaryScoreBand(candidate.latest_score_band)}）；现在确认可让后续跟进继续。`,
    statusLabel: "等待你的判断",
    statusTone: "warning",
    destination: "lead",
    priority: (candidate.latest_score ?? 0) + (leadBandPriority[candidate.latest_score_band ?? ""] ?? 0),
    updatedAt: candidate.updated_at,
  }))
  const masters: DashboardDecision[] = (canDecideContent.value ? masterReviewsQuery.data.value?.results ?? [] : []).map((item) => ({
    id: `master:${item.id}`,
    title: item.payload.title,
    explanation: "这项通用文案正在等待确认；确认后才能继续准备各推广渠道的版本。",
    statusLabel: "等待内容确认",
    statusTone: "warning",
    destination: "review",
    priority: 110,
    updatedAt: item.updated_at,
  }))
  const platforms: DashboardDecision[] = (canDecideContent.value ? platformReviewsQuery.data.value?.results ?? [] : []).map((item) => ({
    id: `platform:${item.id}`,
    title: item.payload.title,
    explanation: "这项渠道文案正在等待确认；确认后才能进入后续发布安排。",
    statusLabel: "等待内容确认",
    statusTone: "warning",
    destination: "review",
    priority: 110,
    updatedAt: item.updated_at,
  }))
  return [...leads, ...masters, ...platforms].sort((left, right) => (
    right.priority - left.priority
    || Date.parse(left.updatedAt) - Date.parse(right.updatedAt)
    || left.id.localeCompare(right.id)
  ))
})
const decisionCards = computed(() => allDecisions.value.slice(0, 3).map((decision, index) => ({
  ...decision,
  index: index + 1,
})))
const decisionCount = computed(() => allDecisions.value.length)
const accessibleDecisionQueries = computed(() => [
  ...(canDecideLeads.value ? [decisionsQuery] : []),
  ...(canDecideContent.value ? [masterReviewsQuery, platformReviewsQuery] : []),
])
const canDecideAnything = computed(() => accessibleDecisionQueries.value.length > 0)
const decisionsPending = computed(() => accessibleDecisionQueries.value.some((query) => (
  query.isPending.value && query.fetchStatus.value === "fetching"
)))
const decisionErrors = computed(() => accessibleDecisionQueries.value.filter((query) => query.isError.value))
const decisionsHaveMore = computed(() => [
  canDecideLeads.value ? decisionsQuery.data.value?.next : null,
  canDecideContent.value ? masterReviewsQuery.data.value?.next : null,
  canDecideContent.value ? platformReviewsQuery.data.value?.next : null,
].some(Boolean))
const decisionHeading = computed(() => {
  const qualifier = decisionsHaveMore.value ? "至少有" : "有"
  return `今天${qualifier} ${decisionCount.value} 件事需要你决定`
})

function retryDecisions(): void {
  for (const query of decisionErrors.value) void query.refetch()
}

const activeJobQueries = [queuedJobsQuery, runningJobsQuery, retryQueuedJobsQuery]
const activeJobs = computed(() => {
  const uniqueJobs = new Map<string, Job>()
  for (const query of activeJobQueries) {
    for (const job of query.data.value?.results ?? []) uniqueJobs.set(job.job_id, job)
  }
  return [...uniqueJobs.values()]
    .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
    .slice(0, 20)
})
const activeJobsPending = computed(() => activeJobQueries
  .some((query) => query.isPending.value && query.fetchStatus.value === "fetching"))
const activeJobsHasError = computed(() => activeJobQueries.some((query) => query.isError.value))
const activeJobsReady = computed(() => activeJobQueries.every((query) => query.isSuccess.value))

function retryActiveJobs(): void {
  for (const query of activeJobQueries) {
    if (query.isError.value) void query.refetch()
  }
}

const jobTypeLabels: Record<string, { active: string; complete: string }> = {
  SOURCE_IMPORT: { active: "正在筛选公开线索", complete: "公开线索筛选已完成" },
  SOURCE_NORMALIZE: { active: "正在整理公开线索", complete: "公开线索整理已完成" },
  EVIDENCE_EXTRACT: { active: "正在提取公开证据", complete: "公开证据提取已完成" },
  LEAD_ANALYZE: { active: "正在分析客户机会", complete: "客户机会分析已完成" },
  CONTENT_GENERATE: { active: "正在生成推广内容", complete: "推广内容生成已完成" },
  RETENTION_CLEANUP: { active: "正在清理到期数据", complete: "到期数据清理已完成" },
}

function activeJobLabel(job: Job): string {
  return jobTypeLabels[job.type]?.active ?? "正在执行后台任务"
}

function jobStatusTone(status: JobStatus): "brand" | "warning" | "neutral" {
  if (status === "RUNNING") return "brand"
  if (status === "RETRY_QUEUED") return "warning"
  return "neutral"
}

function activeJobDetail(job: Job): string {
  if (job.status === "QUEUED") return "任务正在等待开始。"
  if (job.status === "RETRY_QUEUED") return "任务正在等待重新执行。"
  return "任务正在处理，进度来自任务状态。"
}

const recentResults = computed(() => recentResultsQuery.data.value?.results ?? [])

function openDecision(destination: DecisionDestination): void {
  void router.push(destination === "lead" ? "/lead-radar" : "/reviews")
}
</script>

<template>
  <div class="page-stack dashboard-page">
    <header class="cockpit-hero">
      <div>
        <p class="eyebrow">今天</p>
        <h1 v-if="canDecideAnything && decisionCards.length">{{ decisionHeading }}</h1>
        <h1 v-else-if="canDecideAnything && decisionErrors.length && !decisionsPending">今天需要决定的内容暂未全部加载</h1>
        <h1 v-else-if="canDecideAnything && decisionsPending">正在整理今天需要你决定的事</h1>
        <h1 v-else>今天的工作概览</h1>
        <p>优先展示当前账号有权查看、并且需要你采取行动的真实工作；未知信息不会被补成数字。</p>
      </div>
    </header>

    <div class="cockpit-grid dashboard-cockpit-grid">
      <section class="cockpit-card cockpit-card-priority" role="region" aria-labelledby="decision-title">
        <div class="cockpit-card-heading">
          <div>
            <p class="eyebrow">优先处理</p>
            <h2 id="decision-title">需要你决定</h2>
          </div>
          <RouterLink v-if="canDecideLeads && !canDecideContent" class="text-link" to="/lead-radar">查看全部</RouterLink>
          <RouterLink v-else-if="canDecideContent" class="text-link" to="/reviews">查看全部</RouterLink>
        </div>
        <p v-if="!canDecideAnything" class="cockpit-empty">你没有可在这里处理的客户机会或待确认内容。</p>
        <p v-else-if="decisionsPending && !decisionCards.length" class="cockpit-empty" role="status">正在读取需要你决定的工作…</p>
        <div v-if="decisionErrors.length" class="cockpit-local-error" role="alert">
          <p>{{ decisionCards.length ? '部分待决定内容暂时没有加载成功。已加载的内容仍可处理。' : '待决定内容暂时没有加载成功。' }}</p>
          <button type="button" @click="retryDecisions">重新加载未确认内容</button>
        </div>
        <div v-if="canDecideAnything && !decisionsPending && !decisionErrors.length && !decisionCards.length" class="cockpit-empty">
          <p>当前没有等待你决定的客户机会或待确认内容。</p>
          <RouterLink v-if="canDecideLeads" class="text-link" to="/lead-radar">前往客户机会</RouterLink>
        </div>
        <div v-if="decisionCards.length" class="decision-card-list">
          <DecisionCard
            v-for="decision in decisionCards"
            :key="decision.id"
            :index="decision.index"
            :title="decision.title"
            :explanation="decision.explanation"
            :status-label="decision.statusLabel"
            :status-tone="decision.statusTone"
            :primary-action="decision.destination === 'lead' ? '查看并决定' : '查看并确认'"
            @primary="openDecision(decision.destination)"
          />
        </div>
      </section>

      <section class="cockpit-card" role="region" aria-labelledby="activity-title">
        <div class="cockpit-card-heading">
          <div>
            <p class="eyebrow">进行中</p>
            <h2 id="activity-title">AI 正在帮你工作</h2>
          </div>
        </div>
        <p v-if="!canReadJobs" class="cockpit-empty">你没有查看 AI 任务的权限。</p>
        <p v-else-if="activeJobsPending && !activeJobs.length && !activeJobsHasError" class="cockpit-empty" role="status">正在读取 AI 的工作进度…</p>
        <div v-if="canReadJobs && activeJobsHasError" class="cockpit-local-error" role="alert">
          <p>部分 AI 工作状态暂时无法确认；已确认的工作仍显示在下方。</p>
          <button type="button" @click="retryActiveJobs">重新加载未确认状态</button>
        </div>
        <div v-if="canReadJobs && activeJobsReady && !activeJobs.length" class="cockpit-empty">
          <p>当前没有正在执行的 AI 工作。添加公开线索后，AI 会在这里汇报进度。</p>
          <RouterLink class="text-link" to="/lead-radar">前往客户机会</RouterLink>
        </div>
        <div v-if="canReadJobs && activeJobs.length" class="activity-row-list">
          <ActivityRow
            v-for="job in activeJobs"
            :key="job.job_id"
            :title="activeJobLabel(job)"
            :detail="activeJobDetail(job)"
            :status-label="ordinaryStatus(job.status)"
            :status-tone="jobStatusTone(job.status)"
            :progress="Number.isInteger(job.progress) ? job.progress : null"
          />
        </div>
      </section>

      <section class="cockpit-card cockpit-card-results" role="region" aria-labelledby="results-title">
        <div class="cockpit-card-heading">
          <div>
            <p class="eyebrow">近期效果</p>
            <h2 id="results-title">最近结果</h2>
          </div>
        </div>
        <p v-if="!canReadAnalytics" class="cockpit-empty">你没有查看推广效果的权限。</p>
        <p v-else-if="recentResultsQuery.isPending.value" class="cockpit-empty" role="status">正在读取最近结果…</p>
        <div v-else-if="recentResultsQuery.isError.value" class="cockpit-local-error" role="alert">
          <p>最近结果暂时无法加载。</p>
          <button type="button" @click="recentResultsQuery.refetch()">重新加载最近结果</button>
        </div>
        <div v-else-if="!recentResults.length" class="cockpit-empty">
          <p>暂时没有已记录的推广效果。发布并使用追踪链接后，真实结果会在这里汇总。</p>
        </div>
        <template v-else>
          <div class="dashboard-metrics">
            <MetricCard
              label="推广内容获得的点击"
              :value="`${recentResultsQuery.data.value?.total_clicks ?? 0} 次`"
              conclusion="来自当前组织已记录的推广效果。"
            />
          </div>
          <ul class="cockpit-list cockpit-list-compact">
            <li v-for="(result, index) in recentResults.slice(0, 5)" :key="`${result.date}:${index}`">
              <div>
                <strong>{{ result.date }} 的推广内容获得 {{ result.clicks }} 次点击</strong>
                <p>{{ result.country ? `记录地区：${result.country}` : '未记录地区' }}</p>
              </div>
            </li>
          </ul>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.dashboard-cockpit-grid {
  align-items: start;
}

.cockpit-card-priority {
  grid-row: span 2;
}

.decision-card-list,
.activity-row-list {
  margin-top: 18px;
}

.dashboard-metrics {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  margin-top: 18px;
}

@media (max-width: 760px) {
  .cockpit-card-priority { grid-row: auto; }
}
</style>
