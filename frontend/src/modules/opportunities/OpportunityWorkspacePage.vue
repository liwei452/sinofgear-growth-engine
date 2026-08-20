<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"
import { useRoute, useRouter } from "vue-router"

import {
  addCandidateToFollowUp,
  createOpportunityDraft,
  discoveryQueryKeys,
  discoverySummaryQueryOptions,
  importCandidateList,
  prepareCandidateEnrichment,
  reviewDiscoveryCandidate,
  type CandidateEnrichmentPreview,
  type DiscoveryCandidate,
} from "../growth/api"
import {
  parseOpportunityFilters,
  serializeOpportunityFilters,
  type OpportunityFilters,
  type OpportunityStage,
} from "./opportunityFilters"

type CandidateWithPreview = DiscoveryCandidate & {
  latest_preview: CandidateEnrichmentPreview | null
}
type CandidateWorkflow = { account_id: string | null; follow_up_status: string | null; draft: { status: string; delivery: string; message_id: string | null; sent_at: string | null } | null }
type CandidateWithWorkflow = CandidateWithPreview & { workflow: CandidateWorkflow }

const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const opportunitiesQuery = useQuery(discoverySummaryQueryOptions())
const actionError = ref("")
const actionMessage = ref("")
const marketRecommendation = computed(() => typeof route.query.market === "string" ? route.query.market : "")
const importOpen = ref(Boolean(marketRecommendation.value))
const importContent = ref("")
const importMessage = ref("")

const filters = computed(() => parseOpportunityFilters(new URLSearchParams(route.fullPath.split("?")[1] ?? "")))
const candidates = computed<CandidateWithWorkflow[]>(() => {
  const summary = opportunitiesQuery.data.value
  if (!summary) return []
  const all = new Map<string, CandidateWithWorkflow>()
  for (const candidate of summary.candidates ?? []) {
    all.set(candidate.id, { ...candidate, latest_preview: null, workflow: emptyWorkflow() })
  }
  for (const candidate of summary.enrichment_candidates ?? []) {
    all.set(candidate.id, {
      ...candidate,
      latest_preview: candidate.latest_preview ?? null,
      workflow: candidate.workflow ?? emptyWorkflow(),
    })
  }
  return [...all.values()]
})

function stageFor(candidate: CandidateWithWorkflow): OpportunityStage {
  if (candidate.workflow.draft) return "DRAFT"
  if (candidate.workflow.follow_up_status) return "FOLLOW_UP"
  if (candidate.latest_preview || candidate.status === "ACCEPTED") return "ENRICHMENT"
  return "CANDIDATE"
}

const visibleCandidates = computed(() => {
  const { q, stage, sort } = filters.value
  return candidates.value
    .filter(candidate => !q || [candidate.company_name, candidate.country, candidate.industry].join(" ").toLowerCase().includes(q.toLowerCase()))
    .filter(candidate => stage === "ALL" || stageFor(candidate) === stage)
    .sort((left, right) => sort === "score"
      ? right.score - left.score
      : new Date(right.created_at).getTime() - new Date(left.created_at).getTime())
})
const selected = computed(() => candidates.value.find(candidate => candidate.id === filters.value.selected) ?? null)
const selectedMissing = computed(() => Boolean(filters.value.selected && !selected.value))

function licenseAwaitingConfirmation(candidate: CandidateWithPreview): boolean {
  return candidate.license_contract.includes("待人工确认")
}

function emptyWorkflow(): CandidateWorkflow {
  return { account_id: null, follow_up_status: null, draft: null }
}

function replaceFilters(next: OpportunityFilters): void {
  const query = Object.fromEntries(new URLSearchParams(serializeOpportunityFilters(next)))
  void router.replace({ query })
}

function select(candidateId: string): void {
  replaceFilters({ ...filters.value, selected: candidateId })
}

function backToList(): void {
  replaceFilters({ ...filters.value, selected: null })
}

function updateFilter<K extends keyof OpportunityFilters>(key: K, value: OpportunityFilters[K]): void {
  replaceFilters({ ...filters.value, [key]: value })
}

async function refresh(): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: discoveryQueryKeys.profile })
}

const reviewMutation = useMutation({
  mutationFn: ({ id, decision }: { id: string; decision: "ACCEPT" | "DISMISS" }) => reviewDiscoveryCandidate(id, decision),
  onSuccess: refresh,
})
const enrichmentMutation = useMutation({ mutationFn: prepareCandidateEnrichment, onSuccess: refresh })
const followUpMutation = useMutation({
  mutationFn: addCandidateToFollowUp,
  onSuccess: refresh,
})
const draftMutation = useMutation({
  mutationFn: ({ accountId }: { candidateId: string; accountId: string }) => createOpportunityDraft(accountId),
  onSuccess: refresh,
})
const importMutation = useMutation({
  mutationFn: importCandidateList,
  onSuccess: async (result) => {
    importMessage.value = `已导入 ${result.created_count} 条候选公司，等待人工审核。`
    importContent.value = ""
    await refresh()
  },
})

async function perform(action: () => Promise<unknown>): Promise<void> {
  actionError.value = ""
  actionMessage.value = ""
  await action().then(() => { actionMessage.value = "操作已保存；页面已从服务端重新读取当前阶段。" })
    .catch(() => { actionError.value = "操作未完成，当前没有新增客户、联系方式或联系结果。" })
}

function preview(candidate: CandidateWithPreview): CandidateEnrichmentPreview | null {
  return candidate.latest_preview
}

async function importCandidates(): Promise<void> {
  importMessage.value = ""
  await perform(async () => {
    await importMutation.mutateAsync({
      format: "CSV",
      content: importContent.value,
      source_owner: "人工提供候选名单",
      license_contract: "待人工确认使用范围",
      retention_days: 30,
      redistribution_allowed: false,
    })
  })
}
</script>

<template>
  <section class="opportunity-workspace">
    <p v-if="marketRecommendation" class="market-recommendation-context" role="status">市场推荐 {{ marketRecommendation }} 已带入；请导入有权使用的候选名单并进行人工审核。</p>
    <header class="workspace-header">
      <div><p class="eyebrow">CUSTOMER OPPORTUNITIES</p><h1>客户机会</h1><p>候选公司、意向信号、联系人和入站线索保持独立；仅展示已返回的资料与动作结果。</p></div><button type="button" @click="importOpen = !importOpen">导入候选名单</button>
    </header>

    <form v-if="importOpen" class="import-form" @submit.prevent="importCandidates"><label>候选名单内容<textarea v-model="importContent" aria-label="候选名单内容" required placeholder="company_name,country,website,industry" /></label><p>仅导入你提供且有权使用的名单；导入后必须人工审核，不会自动抓取或联系。</p><button type="submit" :disabled="importMutation.isPending.value || !importContent.trim()">导入并进入人工审核</button><p v-if="importMessage" role="status">{{ importMessage }}</p></form>

    <section class="filters" aria-label="客户机会筛选">
      <label>搜索客户机会<input :value="filters.q" type="search" role="searchbox" aria-label="搜索客户机会" @input="updateFilter('q', ($event.target as HTMLInputElement).value)" /></label>
      <label>阶段<select :value="filters.stage" @change="updateFilter('stage', ($event.target as HTMLSelectElement).value as OpportunityStage)"><option value="ALL">全部</option><option value="CANDIDATE">候选</option><option value="ENRICHMENT">资料补全</option></select></label>
      <label>排序<select :value="filters.sort" @change="updateFilter('sort', ($event.target as HTMLSelectElement).value as OpportunityFilters['sort'])"><option value="score">评分</option><option value="newest">最新</option></select></label>
    </section>

    <p v-if="opportunitiesQuery.isLoading.value" class="state">正在读取客户机会…</p>
    <p v-else-if="opportunitiesQuery.isError.value" class="state error" role="alert">暂时无法读取客户机会；未生成候选、抓取结果或联系结果。</p>
    <p v-else-if="!candidates.length" class="state">当前没有可展示的客户机会。</p>
    <div v-else class="workspace-grid" :class="{ 'detail-selected': selected }">
      <section class="opportunity-list-panel" :class="{ 'mobile-hidden': selected }">
        <ul class="opportunity-list" aria-label="客户机会列表">
          <li v-for="candidate in visibleCandidates" :key="candidate.id">
            <article class="opportunity-row">
              <div><strong>{{ candidate.company_name }}</strong><p>{{ candidate.country }} · {{ candidate.industry }}</p><p>需求信号：{{ candidate.intent_score }} 分 · 来源：{{ candidate.source_owner }}</p><p>发现时间：{{ new Date(candidate.created_at).toLocaleDateString('zh-CN') }} · 证据：{{ candidate.status_label }} · 阶段：{{ stageFor(candidate) }}</p></div>
              <button type="button" :aria-label="`查看 ${candidate.company_name} 的证据`" @click="select(candidate.id)">查看证据</button>
            </article>
          </li>
        </ul>
        <p v-if="!visibleCandidates.length" class="state">没有符合当前筛选条件的客户机会。</p>
      </section>

      <p v-if="selectedMissing" class="state error" role="alert">所选客户机会已不在当前结果中；筛选条件保持不变。</p>

      <section v-if="selected" class="opportunity-detail" role="region" aria-label="客户机会详情">
        <button class="back" type="button" aria-label="返回客户机会列表" @click="backToList">返回列表</button>
        <header><p class="eyebrow">{{ selected.grade }} · {{ stageFor(selected) }}</p><h2>{{ selected.company_name }}</h2><p>{{ selected.country }} · {{ selected.industry }} · {{ selected.website || '未提供公开网站' }}</p></header>
        <section><h3>推荐原因</h3><p>意向评分 {{ selected.intent_score }}，综合评分 {{ selected.score }}。评分构成：{{ Object.entries(selected.intent_breakdown).map(([name, score]) => `${name} ${score}`).join('；') || '尚未提供评分构成' }}。</p></section>
        <section><h3>证据与来源</h3><p>{{ selected.source_owner }} · 使用约束：{{ selected.license_contract }}。</p><p>当前没有可公开展示的证据链接。</p></section>
        <section><h3>公司资料</h3><p>国家：{{ selected.country }}；行业：{{ selected.industry }}；网站：{{ selected.website || '未提供' }}。</p></section>
        <section><h3>公开联系路径</h3><template v-if="preview(selected)?.public_contact_paths.length"><a v-for="(path, index) in preview(selected)?.public_contact_paths" :key="index" :href="path.url" target="_blank" rel="noreferrer">{{ path.label || path.url }}</a></template><p v-else>尚未补全公开联系路径</p></section>
        <section><h3>资料补全与活动</h3><p v-if="preview(selected)">{{ preview(selected)?.message }} · {{ preview(selected)?.data_label }}</p><p v-else>尚未准备资料补全；不会假定存在联系人、抓取结果或联系方式。</p><p v-if="licenseAwaitingConfirmation(selected)" class="license-block">候选名单的使用许可尚待人工确认，暂不能加入跟进或生成联系草稿。</p><p v-if="selected.workflow.follow_up_status">已加入跟进（{{ selected.workflow.follow_up_status }}），尚未外发联系。</p><p v-if="selected.workflow.draft">已生成联系草稿（{{ selected.workflow.draft.status }}），<template v-if="selected.workflow.draft.delivery === 'NEVER_SENT'">状态为未发送。</template><template v-else>已有投递结果：{{ selected.workflow.draft.delivery }}。</template></p></section>
        <div class="actions">
          <template v-if="selected.status === 'PENDING_REVIEW'"><button type="button" :disabled="reviewMutation.isPending.value" @click="perform(() => reviewMutation.mutateAsync({ id: selected!.id, decision: 'ACCEPT' }))">人工接受候选</button><button type="button" :disabled="reviewMutation.isPending.value" @click="perform(() => reviewMutation.mutateAsync({ id: selected!.id, decision: 'DISMISS' }))">人工驳回候选</button></template>
          <button v-if="selected.status === 'ACCEPTED' && !preview(selected)" type="button" :disabled="enrichmentMutation.isPending.value" @click="perform(() => enrichmentMutation.mutateAsync(selected!.id))">准备资料补全</button>
          <button v-if="preview(selected) && !licenseAwaitingConfirmation(selected) && !selected.workflow.follow_up_status" type="button" :disabled="followUpMutation.isPending.value" @click="perform(() => followUpMutation.mutateAsync(selected!.id))">加入跟进</button>
          <button v-if="selected.workflow.follow_up_status && selected.workflow.account_id && !selected.workflow.draft" type="button" :disabled="draftMutation.isPending.value" @click="perform(() => draftMutation.mutateAsync({ candidateId: selected!.id, accountId: selected!.workflow.account_id! }))">生成联系草稿</button>
        </div>
        <p v-if="actionMessage" role="status">{{ actionMessage }}</p>
        <p v-if="actionError" role="alert" class="error">{{ actionError }}</p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.opportunity-workspace{display:grid;gap:1rem}.market-recommendation-context{margin:0;border:1px solid #b7d8ef;border-radius:1rem;background:#f3f9fd;padding:1rem;color:#14577d}.workspace-header,.filters,.opportunity-row,.opportunity-detail,.state,.import-form{border:1px solid #dce6f0;border-radius:1rem;background:#fff;padding:1rem}.workspace-header{display:flex;align-items:start;justify-content:space-between;gap:1rem;background:linear-gradient(120deg,#0d3e69,#19689a);color:#fff}.workspace-header h1,.workspace-header p,.opportunity-detail h2,.opportunity-detail p{margin:.25rem 0}.workspace-header button,.import-form button{padding:.5rem .7rem;border:0;border-radius:.5rem;background:#fff;color:#14669a;font-weight:700;cursor:pointer}.import-form{display:grid;gap:.6rem}.import-form label{display:grid;gap:.35rem;font-weight:700}.import-form textarea{min-height:6rem;padding:.55rem;border:1px solid #b9c8d6;border-radius:.5rem}.import-form p{margin:0;color:#526779;font-size:.8rem}.import-form button{justify-self:start;background:#14669a;color:#fff}.eyebrow{font-size:.7rem;font-weight:800;letter-spacing:.08em}.filters{display:grid;grid-template-columns:2fr 1fr 1fr;gap:.75rem}.filters label{display:grid;gap:.35rem;font-size:.8rem;font-weight:700}.filters input,.filters select{min-height:44px;padding:.55rem;border:1px solid #b9c8d6;border-radius:.5rem}.workspace-grid{display:grid;grid-template-columns:minmax(320px,.9fr) minmax(420px,1.1fr);gap:1rem}.opportunity-list{display:grid;gap:.75rem;margin:0;padding:0;list-style:none}.opportunity-row{display:flex;align-items:center;justify-content:space-between;gap:.75rem}.opportunity-row p{margin:.25rem 0;color:#526779;font-size:.8rem}.opportunity-detail{display:grid;align-content:start;gap:1rem}.opportunity-detail section{border-top:1px solid #e7edf3;padding-top:.75rem}.opportunity-detail h3{margin:0 0 .4rem;font-size:.95rem}.opportunity-detail a{display:block;margin:.3rem 0}.actions{display:flex;flex-wrap:wrap;gap:.5rem}.actions button,.opportunity-row button,.back{padding:.5rem .7rem;border:0;border-radius:.5rem;background:#14669a;color:#fff;cursor:pointer}.actions button:disabled{opacity:.6}.state{color:#526779}.error{color:#9b2b20;background:#fff4f2}@media(max-width:760px){.workspace-header,.filters,.workspace-grid{grid-template-columns:1fr;flex-direction:column}.detail-selected .mobile-hidden{display:none}.opportunity-row{align-items:flex-start;flex-direction:column}.opportunity-row button{width:100%}}
</style>
