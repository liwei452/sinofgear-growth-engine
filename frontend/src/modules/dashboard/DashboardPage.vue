<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"
import { RouterLink } from "vue-router"

import { assetKeys, listAssets } from "../assets/api"
import { currentUserQueryOptions } from "../auth/auth"
import { listJobs, type Job } from "../content/api"
import { knowledgeQueryKeys, listConcepts } from "../knowledge/api"
import { listLeadCandidates } from "../leads/api"
import { listProducts, productQueryKeys } from "../products/api"

const currentUserQuery = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUserQuery.data.value?.organization.id ?? "")
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const has = (permission: string): boolean => permissions.value.includes(permission)

const canReadLeads = computed(() => has("leads.read"))
const canReadJobs = computed(() => has("jobs.read"))
const canReadProducts = computed(() => has("products.read"))
const canReadKnowledge = computed(() => has("knowledge.read"))
const canReadAssets = computed(() => has("assets.read"))
const canCheckCompany = computed(() => canReadProducts.value || canReadKnowledge.value || canReadAssets.value)

const dashboardKeys = {
  decisions: (organization: string) => ["dashboard", organization, "decisions"] as const,
  activeJobs: (organization: string) => ["dashboard", organization, "active-jobs"] as const,
  recentResults: (organization: string) => ["dashboard", organization, "recent-results"] as const,
}

const decisionsQuery = useQuery({
  queryKey: computed(() => dashboardKeys.decisions(organizationId.value)),
  queryFn: () => listLeadCandidates({ review_state: "UNREVIEWED", page_size: 5 }),
  enabled: computed(() => Boolean(organizationId.value) && canReadLeads.value),
  retry: false,
})
const activeJobsQuery = useQuery({
  queryKey: computed(() => dashboardKeys.activeJobs(organizationId.value)),
  queryFn: () => listJobs(),
  enabled: computed(() => Boolean(organizationId.value) && canReadJobs.value),
  retry: false,
})
const recentResultsQuery = useQuery({
  queryKey: computed(() => dashboardKeys.recentResults(organizationId.value)),
  queryFn: () => listJobs({ status: "SUCCEEDED" }),
  enabled: computed(() => Boolean(organizationId.value) && canReadJobs.value),
  retry: false,
})
const productsQuery = useQuery({
  queryKey: computed(() => productQueryKeys.list(organizationId.value, {})),
  queryFn: () => listProducts(),
  enabled: computed(() => Boolean(organizationId.value) && canReadProducts.value),
  retry: false,
})
const knowledgeQuery = useQuery({
  queryKey: computed(() => knowledgeQueryKeys.concepts(organizationId.value)),
  queryFn: listConcepts,
  enabled: computed(() => Boolean(organizationId.value) && canReadKnowledge.value),
  retry: false,
})
const assetsQuery = useQuery({
  queryKey: computed(() => assetKeys.list(organizationId.value, {})),
  queryFn: () => listAssets(),
  enabled: computed(() => Boolean(organizationId.value) && canReadAssets.value),
  retry: false,
})

const activeStatuses = new Set<Job["status"]>(["QUEUED", "RUNNING", "RETRY_QUEUED"])
const activeJobs = computed(() => (activeJobsQuery.data.value?.results ?? [])
  .filter((job) => activeStatuses.has(job.status)))

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

function completedJobLabel(job: Job): string {
  return jobTypeLabels[job.type]?.complete ?? "后台任务已完成"
}

function activeJobState(job: Job): string {
  if (job.status === "QUEUED") return "等待开始"
  if (job.status === "RETRY_QUEUED") return "等待重新执行"
  return "执行中"
}

type CompanyGap = { label: string; detail: string; to: string; action: string }
const companyGaps = computed<CompanyGap[]>(() => {
  const gaps: CompanyGap[] = []
  if (canReadProducts.value && productsQuery.isSuccess.value && !productsQuery.data.value?.results.length) {
    gaps.push({ label: "还缺产品资料", detail: "先补充要推广的产品与交付能力。", to: "/products", action: "补充产品" })
  }
  if (canReadKnowledge.value && knowledgeQuery.isSuccess.value && !knowledgeQuery.data.value?.length) {
    gaps.push({ label: "还缺公司知识", detail: "补充卖点、工艺、市场术语和表达边界。", to: "/knowledge", action: "补充知识" })
  }
  if (canReadAssets.value && assetsQuery.isSuccess.value && !assetsQuery.data.value?.results.length) {
    gaps.push({ label: "还缺可用素材", detail: "上传真实图片、视频或文档，供后续推广使用。", to: "/assets", action: "补充素材" })
  }
  return gaps
})
const companyPending = computed(() => [productsQuery, knowledgeQuery, assetsQuery]
  .some((query) => query.isPending.value && query.fetchStatus.value === "fetching"))
const companyHasError = computed(() => [productsQuery, knowledgeQuery, assetsQuery]
  .some((query) => query.isError.value))
const companyReady = computed(() => [
  !canReadProducts.value || productsQuery.isSuccess.value,
  !canReadKnowledge.value || knowledgeQuery.isSuccess.value,
  !canReadAssets.value || assetsQuery.isSuccess.value,
].every(Boolean))

function retryCompanySources(): void {
  if (productsQuery.isError.value) void productsQuery.refetch()
  if (knowledgeQuery.isError.value) void knowledgeQuery.refetch()
  if (assetsQuery.isError.value) void assetsQuery.refetch()
}
</script>

<template>
  <div class="page-stack dashboard-page">
    <header class="cockpit-hero">
      <div>
        <p class="eyebrow">今天</p>
        <h1>需要处理的事，都在这里</h1>
        <p>只显示当前账号有权查看的真实工作与资料；没有数据时会直接说明。</p>
      </div>
    </header>

    <div class="cockpit-grid">
      <section class="cockpit-card cockpit-card-priority" role="region" aria-labelledby="decision-title">
        <div class="cockpit-card-heading">
          <div>
            <p class="eyebrow">待办</p>
            <h2 id="decision-title">今天需要你决定</h2>
          </div>
          <RouterLink v-if="canReadLeads" class="text-link" to="/lead-radar">查看全部</RouterLink>
        </div>
        <p v-if="!canReadLeads" class="cockpit-empty">你没有查看客户机会的权限。</p>
        <p v-else-if="decisionsQuery.isPending.value" class="cockpit-empty" role="status">正在读取待决定事项…</p>
        <div v-else-if="decisionsQuery.isError.value" class="cockpit-local-error" role="alert">
          <p>待决定事项暂时无法加载。</p>
          <button type="button" @click="decisionsQuery.refetch()">重新加载待决定事项</button>
        </div>
        <p v-else-if="!decisionsQuery.data.value?.results.length" class="cockpit-empty">今天没有等待你处理的客户机会。</p>
        <ul v-else class="cockpit-list">
          <li v-for="candidate in decisionsQuery.data.value.results" :key="candidate.id">
            <div>
              <strong>{{ candidate.company_name }}</strong>
              <p>这条客户机会还没有完成人工判断。</p>
            </div>
            <RouterLink class="button button-secondary" to="/lead-radar">查看并决定</RouterLink>
          </li>
        </ul>
      </section>

      <section class="cockpit-card" role="region" aria-labelledby="running-title">
        <div class="cockpit-card-heading">
          <div>
            <p class="eyebrow">进行中</p>
            <h2 id="running-title">AI 正在执行</h2>
          </div>
        </div>
        <p v-if="!canReadJobs" class="cockpit-empty">你没有查看 AI 任务的权限。</p>
        <p v-else-if="activeJobsQuery.isPending.value" class="cockpit-empty" role="status">正在读取执行情况…</p>
        <div v-else-if="activeJobsQuery.isError.value" class="cockpit-local-error" role="alert">
          <p>AI 执行情况暂时无法加载。</p>
          <button type="button" @click="activeJobsQuery.refetch()">重新加载执行情况</button>
        </div>
        <p v-else-if="!activeJobs.length" class="cockpit-empty">当前没有正在执行的 AI 任务。</p>
        <ul v-else class="cockpit-list cockpit-list-compact">
          <li v-for="job in activeJobs" :key="job.job_id">
            <div>
              <strong>{{ activeJobLabel(job) }}</strong>
              <p>{{ activeJobState(job) }}</p>
            </div>
          </li>
        </ul>
      </section>

      <section class="cockpit-card" role="region" aria-labelledby="results-title">
        <div class="cockpit-card-heading">
          <div>
            <p class="eyebrow">刚刚完成</p>
            <h2 id="results-title">近期结果</h2>
          </div>
        </div>
        <p v-if="!canReadJobs" class="cockpit-empty">你没有查看近期 AI 结果的权限。</p>
        <p v-else-if="recentResultsQuery.isPending.value" class="cockpit-empty" role="status">正在读取近期结果…</p>
        <div v-else-if="recentResultsQuery.isError.value" class="cockpit-local-error" role="alert">
          <p>近期结果暂时无法加载。</p>
          <button type="button" @click="recentResultsQuery.refetch()">重新加载近期结果</button>
        </div>
        <p v-else-if="!recentResultsQuery.data.value?.results.length" class="cockpit-empty">当前页没有最近完成的 AI 任务。</p>
        <ul v-else class="cockpit-list cockpit-list-compact">
          <li v-for="job in recentResultsQuery.data.value.results" :key="job.job_id">
            <div>
              <strong>{{ completedJobLabel(job) }}</strong>
              <p>可前往对应工作区查看真实结果。</p>
            </div>
          </li>
        </ul>
      </section>

      <section class="cockpit-card" role="region" aria-labelledby="company-gap-title">
        <div class="cockpit-card-heading">
          <div>
            <p class="eyebrow">AI 的资料基础</p>
            <h2 id="company-gap-title">公司资料还缺什么</h2>
          </div>
          <RouterLink class="text-link" to="/company-profile">查看资料</RouterLink>
        </div>
        <p v-if="!canCheckCompany" class="cockpit-empty">当前权限下无法检查公司资料完整度。</p>
        <p v-else-if="companyPending" class="cockpit-empty" role="status">正在检查当前可见的公司资料…</p>
        <div v-else-if="companyHasError" class="cockpit-local-error" role="alert">
          <p>部分公司资料暂时无法检查，已读取的其他区域仍可使用。</p>
          <button type="button" @click="retryCompanySources">重新检查公司资料</button>
        </div>
        <p v-if="companyReady && !companyGaps.length" class="cockpit-empty cockpit-success">当前可见资料中没有发现空白项。</p>
        <ul v-else-if="companyGaps.length" class="cockpit-list">
          <li v-for="gap in companyGaps" :key="gap.to">
            <div>
              <strong>{{ gap.label }}</strong>
              <p>{{ gap.detail }}</p>
            </div>
            <RouterLink class="button button-secondary" :to="gap.to">{{ gap.action }}</RouterLink>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
