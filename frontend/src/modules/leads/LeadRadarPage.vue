<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, onUnmounted, ref, shallowRef, watch } from "vue"

import { currentUserQueryOptions } from "../auth/auth"
import {
  getLeadCandidate,
  getLeadCandidatePage,
  leadKeys,
  listLeadCandidates,
  safeLeadPageUrl,
  type LeadCandidateDetail,
  type LeadCandidateList,
  type LeadFilters,
} from "./api"
import SourceImportDialog from "./SourceImportDialog.vue"

const emit = defineEmits<{ "select-candidate": [candidateId: string] }>()
const queryClient = useQueryClient()
const currentUserQuery = useQuery(currentUserQueryOptions())
const scoreBand = ref<"" | NonNullable<LeadFilters["score_band"]>>("")
const reviewState = ref<"" | NonNullable<LeadFilters["review_state"]>>("")
const platform = ref("")
const country = ref("")
const pageUrl = ref<string | null>(null)
const importOpen = ref(false)
const details = shallowRef<Record<string, LeadCandidateDetail>>({})
const detailStates = shallowRef<Record<string, "loading" | "success" | "error">>({})
let detailLoad = 0
let activeScopeOrganization = ""
// Enforce the API page contract at runtime; four workers hydrate its 50-item maximum without flooding the API.
const maxLeadPageSize = 50
const detailConcurrency = 4

const organizationId = computed(() => currentUserQuery.data.value?.organization.id ?? "")
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const canRead = computed(() => permissions.value.includes("leads.read"))
const canManageSources = computed(() => permissions.value.includes("sources.manage"))
const filters = computed<LeadFilters>(() => ({
  ...(scoreBand.value ? { score_band: scoreBand.value } : {}),
  ...(platform.value.trim() ? { platform: platform.value.trim() } : {}),
  ...(country.value.trim() ? { country: country.value.trim() } : {}),
  ...(reviewState.value ? { review_state: reviewState.value } : {}),
}))
const hasFilters = computed(() => Boolean(
  scoreBand.value || reviewState.value || platform.value.trim() || country.value.trim(),
))

function cancelLeadReads(organization: string): void {
  if (!organization) return
  void queryClient.cancelQueries({ queryKey: [...leadKeys.all(organization), "list"] })
  cancelDetailReads(organization)
}

function cancelDetailReads(organization: string): void {
  if (!organization) return
  void queryClient.cancelQueries({ queryKey: [...leadKeys.all(organization), "detail"] })
}

watch(filters, () => { pageUrl.value = null }, { flush: "sync" })

watch([organizationId, filters, pageUrl, canRead], ([currentOrganization, , , readable]) => {
  detailLoad += 1
  cancelLeadReads(activeScopeOrganization)
  details.value = {}
  detailStates.value = {}
  activeScopeOrganization = readable ? currentOrganization : ""
}, { flush: "sync", immediate: true })

const leadsQuery = useQuery({
  queryKey: computed(() => [...leadKeys.list(organizationId.value, filters.value), pageUrl.value]),
  queryFn: ({ queryKey, signal }) => {
    const requestFilters = queryKey[3] as LeadFilters
    const cursor = queryKey[4]
    return typeof cursor === "string"
      ? getLeadCandidatePage(cursor, { signal })
      : listLeadCandidates(requestFilters, { signal })
  },
  enabled: computed(() => Boolean(organizationId.value) && canRead.value),
  retry: false,
})
const leads = computed(() => (leadsQuery.data.value?.results ?? []).slice(0, maxLeadPageSize))
const safeNext = computed(() => safeLeadPageUrl(leadsQuery.data.value?.next ?? null))
const safePrevious = computed(() => safeLeadPageUrl(leadsQuery.data.value?.previous ?? null))
const analyzingStatuses = new Set<LeadCandidateList["status"]>(["DISCOVERED", "ANALYZING"])
const handledStatuses = new Set<LeadCandidateList["status"]>([
  "REVIEWED", "READY_FOR_HANDOFF", "HANDED_OFF", "DISMISSED",
])
const onlyAnalyzing = computed(() => leads.value.length > 0
  && leads.value.every((candidate) => analyzingStatuses.has(candidate.status)))
function evidenceGateResult(candidateId: string): boolean | null {
  if (detailStates.value[candidateId] !== "success") return null
  const insight = details.value[candidateId]?.latest_insight
  if (!insight) return null
  const gates = Object.values(insight.gates ?? {})
  if (!gates.length || gates.some((gate) => typeof gate !== "boolean")) return null
  return gates.every(Boolean)
}

const evidenceSummary = computed<number | string>(() => {
  const states = leads.value.map((candidate) => detailStates.value[candidate.id])
  if (states.some((state) => state === "loading" || !state)) return "核对中"
  if (states.some((state) => state === "error")) return "暂不可用"
  if (leads.value.some((candidate) => !details.value[candidate.id]?.latest_insight)) return "等待分析"
  return leads.value.filter((candidate) => evidenceGateResult(candidate.id) === false).length
})
const summaries = computed(() => [
  { label: "等待分析", count: leads.value.filter((item) => analyzingStatuses.has(item.status)).length },
  {
    label: "高价值待决定",
    count: leads.value.filter((item) => item.latest_score_band === "HIGH"
      && !handledStatuses.has(item.status)).length,
  },
  {
    label: "需要补证据",
    count: evidenceSummary.value,
  },
  { label: "已经处理", count: leads.value.filter((item) => handledStatuses.has(item.status)).length },
])

watch([organizationId, leads, canRead], async ([currentOrganization, currentLeads, readable]) => {
  const token = ++detailLoad
  cancelDetailReads(activeScopeOrganization)
  details.value = {}
  detailStates.value = Object.fromEntries(currentLeads.map((candidate) => [candidate.id, "loading"]))
  if (!currentOrganization || !readable || !currentLeads.length) return
  let nextCandidate = 0
  async function hydrateDetails(): Promise<void> {
    while (token === detailLoad && currentOrganization === organizationId.value) {
      const candidate = currentLeads[nextCandidate]
      nextCandidate += 1
      if (!candidate) return
      try {
        const candidateDetail = await queryClient.fetchQuery({
          queryKey: leadKeys.detail(currentOrganization, candidate.id),
          queryFn: ({ signal }) => getLeadCandidate(candidate.id, { signal }),
          retry: false,
        })
        if (token !== detailLoad || currentOrganization !== organizationId.value) return
        details.value = { ...details.value, [candidate.id]: candidateDetail }
        detailStates.value = { ...detailStates.value, [candidate.id]: "success" }
      } catch {
        if (token !== detailLoad || currentOrganization !== organizationId.value) return
        detailStates.value = { ...detailStates.value, [candidate.id]: "error" }
      }
    }
  }
  const workerCount = Math.min(detailConcurrency, currentLeads.length)
  await Promise.all(Array.from({ length: workerCount }, () => hydrateDetails()))
}, { immediate: true })

onUnmounted(() => {
  detailLoad += 1
  cancelLeadReads(activeScopeOrganization)
})

function moveTo(url: string | null): void {
  const safeUrl = safeLeadPageUrl(url)
  if (safeUrl) pageUrl.value = safeUrl
}

function clearFilters(): void {
  scoreBand.value = ""
  reviewState.value = ""
  platform.value = ""
  country.value = ""
  pageUrl.value = null
}

function scoreLabel(candidate: LeadCandidateList): string {
  const labels: Record<string, string> = {
    HIGH: "高价值机会",
    WATCH: "值得关注",
    OBSERVE: "继续观察",
    LOW: "当前价值较低",
  }
  return candidate.latest_score_band ? labels[candidate.latest_score_band] ?? "等待判断" : "等待判断"
}

function evidenceLabel(candidate: LeadCandidateList): string {
  const state = detailStates.value[candidate.id]
  if (state === "loading" || !state) return "正在核对证据…"
  if (state === "error") return "证据状态暂时无法加载"
  if (!details.value[candidate.id]?.latest_insight) return "等待分析证据"
  const gateResult = evidenceGateResult(candidate.id)
  if (gateResult === null) return "证据状态待确认"
  return gateResult ? "证据已达到判断门槛" : "证据还不够"
}

function sourceCopy(candidateId: string): string {
  const state = detailStates.value[candidateId]
  if (state === "loading" || !state) return "正在读取公开来源…"
  if (state === "error") return "公开来源暂时无法加载"
  const platforms = [...new Set((details.value[candidateId]?.evidence ?? [])
    .map((item) => item.platform.trim()).filter(Boolean))]
  return `公开来源：${platforms.length ? platforms.join("、") : "待补充"}`
}

function explanation(candidateId: string): string {
  const state = detailStates.value[candidateId]
  if (state === "loading" || !state) return "正在读取 AI 理由…"
  if (state === "error") return "AI 理由暂时无法加载。"
  const insight = details.value[candidateId]?.latest_insight
  if (!insight) return "等待 AI 完成分析。"
  const value = insight.explanation
  if (typeof value === "string" && value.trim()) return value.trim()
  if (value && typeof value === "object") {
    for (const key of ["summary", "reason", "text"]) {
      const candidate = (value as Record<string, unknown>)[key]
      if (typeof candidate === "string" && candidate.trim()) return candidate.trim()
    }
  }
  return "AI 尚未给出可展示的简要理由。"
}

function statusLabel(status: LeadCandidateList["status"]): string {
  const labels: Record<LeadCandidateList["status"], string> = {
    DISCOVERED: "等待分析",
    ANALYZING: "正在筛选",
    ANALYZED: "等待决定",
    REVIEWED: "已经处理",
    READY_FOR_HANDOFF: "可交给后续跟进",
    HANDED_OFF: "已交给后续跟进",
    DISMISSED: "已忽略",
  }
  return labels[status]
}

async function importCompleted(): Promise<void> {
  importOpen.value = false
  pageUrl.value = null
  await queryClient.invalidateQueries({ queryKey: leadKeys.all(organizationId.value) })
}
</script>

<template>
  <main class="lead-radar" aria-labelledby="lead-radar-title">
    <header class="page-header">
      <div>
        <p class="eyebrow">从公开信息中发现需求</p>
        <h1 id="lead-radar-title">客户机会</h1>
        <p>先收集指定范围内的公开线索，再由 AI 筛选值得你查看的机会。</p>
      </div>
      <button v-if="canManageSources" class="primary-action" type="button" @click="importOpen = true">
        添加公开线索
      </button>
    </header>

    <section v-if="canRead && leadsQuery.isSuccess.value" class="summary-section" aria-labelledby="summary-title">
      <div class="section-heading">
        <h2 id="summary-title">当前机会概况</h2>
        <p>当前列表结果，不代表全部机会</p>
      </div>
      <div class="summary-grid">
        <article v-for="summary in summaries" :key="summary.label" class="summary-card">
          <span>{{ summary.label }}</span>
          <strong>{{ summary.count }}</strong>
        </article>
      </div>
    </section>

    <section v-if="canRead" class="filter-panel" aria-label="客户机会筛选">
      <label>
        机会价值
        <select v-model="scoreBand">
          <option value="">全部价值</option>
          <option value="HIGH">高价值机会</option>
          <option value="WATCH">值得关注</option>
          <option value="OBSERVE">继续观察</option>
          <option value="LOW">当前价值较低</option>
        </select>
      </label>
      <label>
        处理状态
        <select v-model="reviewState">
          <option value="">全部状态</option>
          <option value="UNREVIEWED">等待我处理</option>
          <option value="REVIEWED">已经处理</option>
        </select>
      </label>
      <label>
        公开平台
        <input v-model="platform" type="search" placeholder="例如 LinkedIn">
      </label>
      <label>
        国家或地区
        <input v-model="country" type="search" placeholder="例如 DE">
      </label>
      <button v-if="hasFilters" type="button" class="text-action" @click="clearFilters">清除筛选</button>
    </section>

    <section v-if="!canRead && !currentUserQuery.isPending.value" class="state-panel" role="status">
      <h2>当前账号不能查看客户机会</h2>
      <p>如需访问，请联系管理员开通客户机会读取权限。</p>
    </section>
    <p v-else-if="leadsQuery.isPending.value" class="loading-state" role="status" aria-live="polite">
      正在加载客户机会…
    </p>
    <section v-else-if="leadsQuery.isError.value" class="state-panel error-state" role="alert">
      <h2>客户机会没有加载成功</h2>
      <p>服务暂时不可用，请稍后重新加载。</p>
      <button type="button" @click="leadsQuery.refetch()">重新加载</button>
    </section>
    <section v-else-if="onlyAnalyzing" class="state-panel analyzing-state" role="status" aria-live="polite">
      <h2>正在筛选公开线索</h2>
      <p>分析完成后，值得查看的机会会出现在这里。</p>
    </section>
    <section v-else-if="!leads.length && hasFilters" class="state-panel empty-state">
      <h2>当前筛选没有结果</h2>
      <p>这些条件下还没有机会，可以清除筛选后查看当前列表。</p>
      <button type="button" @click="clearFilters">清除筛选</button>
    </section>
    <section v-else-if="!leads.length" class="state-panel empty-state">
      <h2>还没有公开线索</h2>
      <p>添加你指定范围内的公开内容，AI 才会开始筛选机会。</p>
      <button v-if="canManageSources" class="primary-action" type="button" @click="importOpen = true">
        添加公开线索
      </button>
    </section>
    <section v-else class="opportunity-list" aria-label="客户机会列表" aria-live="polite">
      <article v-for="candidate in leads" :key="candidate.id" class="opportunity-card">
        <div class="opportunity-heading">
          <div>
            <div class="company-line">
              <h2>{{ candidate.company_name || "待确认" }}</h2>
              <span v-if="candidate.company_name" class="uncertain-label">待确认</span>
            </div>
            <p>{{ sourceCopy(candidate.id) }}</p>
          </div>
          <span class="status-label">{{ statusLabel(candidate.status) }}</span>
        </div>
        <div class="decision-signals">
          <div class="signal value-signal">
            <span>机会价值</span>
            <strong>{{ scoreLabel(candidate) }}</strong>
            <small v-if="candidate.latest_score !== null">评分 {{ candidate.latest_score }}</small>
          </div>
          <div class="signal evidence-signal">
            <span>证据充足度</span>
            <strong>{{ evidenceLabel(candidate) }}</strong>
          </div>
        </div>
        <p class="explanation">{{ explanation(candidate.id) }}</p>
        <div class="card-footer">
          <span>{{ candidate.country_hint || "地区待确认" }}</span>
          <button type="button" @click="emit('select-candidate', candidate.id)">查看依据</button>
        </div>
      </article>
    </section>

    <nav v-if="leads.length && !onlyAnalyzing" class="pagination" aria-label="客户机会分页">
      <button type="button" :disabled="!safePrevious" @click="moveTo(safePrevious)">上一页</button>
      <button type="button" :disabled="!safeNext" @click="moveTo(safeNext)">下一页</button>
    </nav>

    <SourceImportDialog
      :organization-id="organizationId"
      :open="importOpen"
      @close="importOpen = false"
      @completed="importCompleted"
    />
  </main>
</template>

<style scoped>
.lead-radar{display:grid;gap:1.5rem}.page-header,.section-heading,.opportunity-heading,.company-line,.card-footer,.pagination{display:flex;align-items:center;justify-content:space-between;gap:1rem}.page-header{align-items:flex-start}.page-header h1,.section-heading h2,.opportunity-card h2{margin:.2rem 0}.page-header p,.section-heading p,.opportunity-heading p,.card-footer,.explanation{color:var(--sg-muted)}.eyebrow{margin:0;color:var(--sg-brand);font-weight:800;letter-spacing:.04em}.primary-action{border-color:var(--sg-brand);background:var(--sg-brand);color:#fff}.summary-section,.filter-panel,.state-panel,.opportunity-card{border:1px solid var(--sg-line);border-radius:var(--sg-radius-md);background:var(--sg-surface)}.summary-section{padding:1rem}.section-heading p{margin:0;font-size:.85rem}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.75rem;margin-top:.8rem}.summary-card{display:grid;gap:.4rem;padding:.9rem;border-radius:var(--sg-radius-sm);background:var(--sg-canvas)}.summary-card span{color:var(--sg-muted)}.summary-card strong{font-size:1.65rem;color:var(--sg-ink)}.filter-panel{display:grid;grid-template-columns:repeat(4,minmax(0,1fr)) auto;gap:.8rem;padding:1rem;align-items:end}.filter-panel label{display:grid;gap:.35rem;font-weight:700}.filter-panel input,.filter-panel select{box-sizing:border-box;width:100%;min-height:2.7rem}.text-action{background:transparent;color:var(--sg-brand)}.loading-state,.state-panel{padding:1.4rem}.state-panel{text-align:center}.error-state{border-color:#efc7c7;background:var(--sg-danger-soft)}.opportunity-list{display:grid;gap:1rem}.opportunity-card{padding:1.1rem;box-shadow:0 8px 24px rgb(23 34 49 / 6%)}.opportunity-heading{align-items:flex-start}.company-line{justify-content:flex-start;flex-wrap:wrap}.uncertain-label,.status-label{display:inline-flex;padding:.25rem .55rem;border-radius:999px;background:var(--sg-brand-soft);color:var(--sg-brand);font-size:.78rem;font-weight:800}.decision-signals{display:grid;grid-template-columns:1fr 1fr;gap:.8rem;margin:1rem 0}.signal{display:grid;gap:.25rem;padding:.8rem;border:1px solid var(--sg-line);border-radius:var(--sg-radius-sm)}.signal span,.signal small{color:var(--sg-muted)}.value-signal{border-left:4px solid var(--sg-brand)}.evidence-signal{border-left:4px solid #c17d16;background:#fffaf0}.explanation{margin:.8rem 0}.card-footer{border-top:1px solid var(--sg-line);padding-top:.8rem}.pagination{justify-content:flex-end}@media(max-width:900px){.summary-grid,.filter-panel{grid-template-columns:repeat(2,minmax(0,1fr))}.filter-panel .text-action{justify-self:start}}@media(max-width:600px){.page-header,.section-heading,.opportunity-heading,.card-footer{align-items:stretch;flex-direction:column}.page-header .primary-action{width:100%}.summary-grid,.filter-panel,.decision-signals{grid-template-columns:1fr}.pagination{display:grid;grid-template-columns:1fr 1fr}.card-footer button{width:100%}}
</style>
