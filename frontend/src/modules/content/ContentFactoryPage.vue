<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { useQuery, useQueryClient } from "@tanstack/vue-query"

import { ApiError } from "../../api/client"
import { currentUserQueryOptions } from "../auth/auth"
import { listProducts, productQueryKeys } from "../products/api"
import ContentBriefWizard from "./ContentBriefWizard.vue"
import {
  cancelJob, contentQueryKeys, generateMaster, getJob, listAssets, listBriefs,
  listApprovedBriefConcepts, listCampaigns, listJobs, listMasterContents, listPlatformPage, markBriefReady,
  retryJob, reviseBrief, type ContentBrief, type Job,
} from "./api"
import { useCursorCollection } from "./useCursorCollection"

const queryClient = useQueryClient()
const currentUserQuery = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUserQuery.data.value?.organization.id ?? "")
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const has = (permission: string) => permissions.value.includes(permission)
const enabled = computed(() => Boolean(organizationId.value))
const wizardOpen = ref(false)
const notice = ref("")
const actionError = ref("")
const actionId = ref("")
const liveJobs = ref<Job[]>([])
const editingBrief = ref<ContentBrief | null>(null)
const timers = new Set<ReturnType<typeof setTimeout>>()
const pollingJobs = new Set<string>()
const jobTimers = new Map<string, ReturnType<typeof setTimeout>>()
let disposed = false

const campaignsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.campaigns(organizationId.value)), queryFn: listCampaigns, enabled: computed(() => enabled.value && has("campaigns.read")) })
const briefsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.briefs(organizationId.value)), queryFn: () => listBriefs(), enabled: computed(() => enabled.value && has("campaigns.read")) })
const productsQuery = useQuery({ queryKey: computed(() => productQueryKeys.list(organizationId.value, {})), queryFn: () => listProducts(), enabled: computed(() => enabled.value && has("products.read")) })
const platformsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.platforms(organizationId.value)), queryFn: listPlatformPage, enabled })
const assetsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.assets(organizationId.value)), queryFn: listAssets, enabled: computed(() => enabled.value && has("assets.read")) })
const conceptsQuery = useQuery({ queryKey: computed(() => [...contentQueryKeys.briefs(organizationId.value), "approved-concepts"]), queryFn: listApprovedBriefConcepts, enabled: computed(() => enabled.value && has("knowledge.read")) })
const jobsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.jobs(organizationId.value)), queryFn: () => listJobs(), enabled: computed(() => enabled.value && has("jobs.read")) })
const masterQuery = useQuery({ queryKey: computed(() => contentQueryKeys.masterContents(organizationId.value, {})), queryFn: () => listMasterContents(), enabled: computed(() => enabled.value && has("content.read")) })

const campaigns = useCursorCollection(campaignsQuery.data, "/api/v1/campaigns", organizationId, (item) => item.id)
const briefPages = useCursorCollection(briefsQuery.data, "/api/v1/content-briefs", organizationId, (item) => item.id)
const productPages = useCursorCollection(productsQuery.data, "/api/v1/products", organizationId, (item) => item.id)
const platformPages = useCursorCollection(platformsQuery.data, "/api/v1/platforms", organizationId, (item) => item.id)
const assetPages = useCursorCollection(assetsQuery.data, "/api/v1/assets", organizationId, (item) => item.id)
const jobPages = useCursorCollection(jobsQuery.data, "/api/v1/jobs", organizationId, (item) => item.job_id)
const masterPages = useCursorCollection(masterQuery.data, "/api/v1/master-contents", organizationId, (item) => item.id)
const briefs = briefPages.items
const jobs = computed(() => {
  const combined = [...jobPages.items.value, ...liveJobs.value]
  return [...new Map(combined.map((job) => [job.job_id, job])).values()]
})
const activeJobStatuses = new Set(["QUEUED", "RUNNING", "RETRY_QUEUED"])

function safeError(error: unknown): string {
  if (error instanceof ApiError) return error.status === 409
    ? "状态已经变化，已为你刷新最新信息。"
    : error.userMessage
  return "操作没有完成，请稍后重试。"
}

function queryError(error: unknown, label: string): string {
  return error instanceof ApiError ? error.userMessage : `${label}没有加载成功，请重试。`
}

function upsertJob(job: Job): void {
  liveJobs.value = [job, ...liveJobs.value.filter((item) => item.job_id !== job.job_id)]
}

async function pollJob(id: string): Promise<void> {
  if (disposed || !pollingJobs.has(id)) return
  try {
    const job = await getJob(id)
    if (disposed || !pollingJobs.has(id)) return
    upsertJob(job)
    if (job.status === "SUCCEEDED") {
      await queryClient.invalidateQueries({ queryKey: contentQueryKeys.masterContents(organizationId.value, {}) })
      if (disposed || !pollingJobs.has(id)) return
      stopPolling(id)
      return
    }
    if (!activeJobStatuses.has(job.status)) { stopPolling(id); return }
    const timer = setTimeout(() => {
      timers.delete(timer)
      jobTimers.delete(id)
      void pollJob(id)
    }, 2500)
    timers.add(timer)
    jobTimers.set(id, timer)
  } catch (error) {
    if (disposed || !pollingJobs.has(id)) return
    stopPolling(id)
    actionError.value = safeError(error)
  }
}

function stopPolling(id: string): void {
  const timer = jobTimers.get(id)
  if (timer) { clearTimeout(timer); timers.delete(timer); jobTimers.delete(id) }
  pollingJobs.delete(id)
}

function beginPolling(id: string): void {
  if (disposed || pollingJobs.has(id)) return
  pollingJobs.add(id)
  void pollJob(id)
}

async function refreshJob(id: string): Promise<void> {
  const job = await getJob(id)
  if (disposed) return
  upsertJob(job)
  if (activeJobStatuses.has(job.status)) beginPolling(job.job_id)
}

async function startGeneration(brief: ContentBrief): Promise<void> {
  if (brief.status !== "READY" || !has("content.manage") || actionId.value) return
  actionId.value = brief.id
  actionError.value = ""
  try {
    const accepted = await generateMaster(brief.id)
    if (!jobs.value.some((job) => job.job_id === accepted.job_id)) {
      upsertJob({ job_id: accepted.job_id, type: "CONTENT_GENERATE", status: accepted.status, progress: 0, attempt: 1, max_attempts: 3, created_at: new Date().toISOString(), finished_at: null, error: null, result_reference: null, generation_mode: accepted.generation_mode, generation_label: accepted.generation_label })
    }
    beginPolling(accepted.job_id)
  } catch (error) { actionError.value = safeError(error) } finally { actionId.value = "" }
}

async function ready(brief: ContentBrief): Promise<void> {
  if (brief.status !== "DRAFT" || !has("campaigns.review")) return
  actionId.value = brief.id
  try {
    await markBriefReady(brief.id)
    await queryClient.invalidateQueries({ queryKey: contentQueryKeys.briefs(organizationId.value) })
    notice.value = "需求已确认，可以开始生成。"
  } catch (error) { actionError.value = safeError(error) } finally { actionId.value = "" }
}

function openBriefEditor(brief: ContentBrief): void {
  if (brief.status !== "DRAFT" || !has("campaigns.manage")) return
  editingBrief.value = brief
}

async function createBriefRevision(brief: ContentBrief): Promise<void> {
  if (brief.status !== "READY" || !has("campaigns.manage")) return
  try {
    editingBrief.value = await reviseBrief(brief.id)
    await queryClient.invalidateQueries({ queryKey: contentQueryKeys.briefs(organizationId.value) })
    notice.value = "已从可生成需求创建新的草稿版本，请检查并保存。"
  } catch (error) { actionError.value = safeError(error) }
}

async function jobAction(job: Job, action: "cancel" | "retry"): Promise<void> {
  if (!has("jobs.manage")) return
  const legal = action === "cancel" ? activeJobStatuses.has(job.status) : job.status === "FAILED"
  if (!legal) return
  try {
    const updated = action === "cancel" ? await cancelJob(job.job_id) : await retryJob(job.job_id)
    upsertJob(updated)
    if (activeJobStatuses.has(updated.status)) beginPolling(updated.job_id)
    else stopPolling(updated.job_id)
  } catch (error) {
    actionError.value = safeError(error)
    if (error instanceof ApiError && error.status === 409) await refreshJob(job.job_id)
  }
}

async function saved(): Promise<void> {
  const wasEditing = Boolean(editingBrief.value)
  wizardOpen.value = false
  editingBrief.value = null
  notice.value = wasEditing ? "需求草稿已更新。" : "内容需求已创建，等待审核人员确认。"
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: contentQueryKeys.campaigns(organizationId.value) }),
    queryClient.invalidateQueries({ queryKey: contentQueryKeys.briefs(organizationId.value) }),
  ])
}

watch(jobs, (items) => {
  for (const job of items) if (activeJobStatuses.has(job.status)) beginPolling(job.job_id)
}, { immediate: true })

onBeforeUnmount(() => { disposed = true; for (const timer of timers) clearTimeout(timer); timers.clear(); jobTimers.clear(); pollingJobs.clear() })
</script>

<template>
  <main class="page-stack content-factory" aria-labelledby="factory-title">
    <header class="library-header"><div><p class="eyebrow">从需求到可审核内容</p><h1 id="factory-title">AI 内容工厂</h1><p>按“准备需求、提交审核、AI 生成、查看结果”四步完成内容生产。</p></div><button v-if="has('campaigns.manage')" class="primary-action" type="button" @click="wizardOpen = true">创建内容任务</button></header>
    <p v-if="notice" role="status" class="notice">{{ notice }}</p><p v-if="actionError" role="alert" class="form-alert">{{ actionError }}</p>
    <section class="query-errors" aria-label="数据加载问题">
      <p v-if="campaignsQuery.isError.value" role="alert">{{ queryError(campaignsQuery.error.value, '活动') }} <button type="button" @click="campaignsQuery.refetch()">重新加载活动</button></p>
      <p v-if="briefsQuery.isError.value" role="alert">{{ queryError(briefsQuery.error.value, '内容需求') }} <button type="button" @click="briefsQuery.refetch()">重新加载内容需求</button></p>
      <p v-if="productsQuery.isError.value" role="alert">{{ queryError(productsQuery.error.value, '产品') }} <button type="button" @click="productsQuery.refetch()">重新加载产品</button></p>
      <p v-if="platformsQuery.isError.value" role="alert">{{ queryError(platformsQuery.error.value, '平台') }} <button type="button" @click="platformsQuery.refetch()">重新加载平台</button></p>
      <p v-if="has('assets.read') && assetsQuery.isError.value" role="alert">{{ queryError(assetsQuery.error.value, '素材') }} <button type="button" @click="assetsQuery.refetch()">重新加载素材</button></p>
      <p v-if="has('jobs.read') && jobsQuery.isError.value" role="alert">{{ queryError(jobsQuery.error.value, '生成任务') }} <button type="button" @click="jobsQuery.refetch()">重新加载生成任务</button></p>
      <p v-if="has('content.read') && masterQuery.isError.value" role="alert">{{ queryError(masterQuery.error.value, '生成结果') }} <button type="button" @click="masterQuery.refetch()">重新加载生成结果</button></p>
    </section>
    <section class="summary-grid" aria-label="当前工作摘要"><article><strong>{{ campaigns.items.value.length }}</strong><span>活动</span></article><article><strong>{{ briefs.length }}</strong><span>内容需求</span></article><article><strong>{{ jobs.length }}</strong><span>生成任务</span></article><article><strong>{{ masterPages.items.value.length }}</strong><span>生成结果</span><button v-if="masterPages.next.value" type="button" @click="masterPages.loadMore">加载更多生成结果</button><span v-if="masterPages.error.value" role="alert">{{ masterPages.error.value }} <button type="button" @click="masterPages.loadMore">重试</button></span></article></section>

    <section aria-labelledby="briefs-title"><h2 id="briefs-title">内容需求</h2><p v-if="briefsQuery.isPending.value" role="status">正在加载内容需求…</p><div v-else-if="!briefs.length" class="state-panel"><h3>还没有内容需求</h3><p>从“创建内容任务”开始，向导会帮你准备完整信息。</p></div><div v-else class="card-grid"><article v-for="item in briefs" :key="item.id" class="workflow-card"><div class="card-heading"><h3>{{ campaigns.items.value.find(c => c.id === item.campaign_id)?.name || '内容需求' }}</h3><span class="status-chip">{{ item.status === 'READY' ? '可生成' : '需求草稿' }}</span></div><p>{{ item.target_country }} · {{ item.customer_type }} · {{ item.language }}</p><p v-if="item.status === 'DRAFT' && !has('campaigns.review')" class="muted">等待审核人员确认</p><div class="card-actions"><button v-if="item.status === 'DRAFT' && has('campaigns.manage')" type="button" @click="openBriefEditor(item)">编辑需求草稿</button><button v-if="item.status === 'DRAFT' && has('campaigns.review')" type="button" :disabled="actionId === item.id" @click="ready(item)">确认需求可生成</button><button v-if="item.status === 'READY' && has('campaigns.manage')" type="button" @click="createBriefRevision(item)">创建需求修订版</button><button v-if="item.status === 'READY' && has('content.manage')" class="primary-action" type="button" :disabled="Boolean(actionId)" @click="startGeneration(item)">开始AI生成</button></div></article></div><p v-if="briefPages.error.value" role="alert">{{ briefPages.error.value }} <button type="button" @click="briefPages.loadMore">重试</button></p><button v-else-if="briefPages.next.value" type="button" @click="briefPages.loadMore">加载更多内容需求</button></section>

    <section aria-labelledby="jobs-title"><h2 id="jobs-title">生成任务</h2><div v-if="jobs.length" class="card-grid"><article v-for="job in jobs" :key="job.job_id" class="workflow-card"><div class="card-heading"><h3>任务 {{ job.job_id }}</h3><span class="status-chip">{{ job.status }}</span></div><p>进度 {{ job.progress }}% · 第 {{ job.attempt }}/{{ job.max_attempts }} 次</p><p v-if="job.status === 'SUCCEEDED'" class="success">生成完成</p><p v-else-if="job.status === 'FAILED'" role="alert">{{ job.error?.message || '生成未完成，可以重试。' }}</p><div class="card-actions"><button v-if="has('jobs.manage') && activeJobStatuses.has(job.status)" type="button" @click="jobAction(job,'cancel')">取消任务</button><button v-if="has('jobs.manage') && job.status === 'FAILED'" type="button" @click="jobAction(job,'retry')">重新尝试</button></div></article></div><p v-else class="muted">提交生成后，进度会显示在这里。</p><p v-if="jobPages.error.value" role="alert">{{ jobPages.error.value }} <button type="button" @click="jobPages.loadMore">重试</button></p><button v-else-if="jobPages.next.value" type="button" @click="jobPages.loadMore">加载更多生成任务</button></section>

    <ContentBriefWizard v-if="wizardOpen || editingBrief" :brief="editingBrief" :campaigns="campaigns.items.value" :products="productPages.items.value" :platforms="platformPages.items.value" :assets="assetPages.items.value" :concepts="conceptsQuery.data.value?.results ?? []" :more="{ campaigns: Boolean(campaigns.next.value), products: Boolean(productPages.next.value), platforms: Boolean(platformPages.next.value), assets: Boolean(assetPages.next.value) }" :page-errors="{ campaigns: campaigns.error.value, products: productPages.error.value, platforms: platformPages.error.value, assets: assetPages.error.value }" @load-more="(kind) => ({ campaigns, products: productPages, platforms: platformPages, assets: assetPages })[kind].loadMore()" @close="wizardOpen = false; editingBrief = null" @saved="saved" />
    <section v-if="jobs.length" class="state-panel generation-disclosure" aria-label="生成模式">
      <h2>生成模式</h2>
      <p v-for="job in jobs" :key="`mode-${job.job_id}`">{{ job.generation_label || "生成方式尚未记录" }}</p>
      <small v-if="jobs.some(job => job.generation_mode === 'FAKE_OFFLINE')">该结果必须人工审核，不能视为真实模型结论。</small>
    </section>
  </main>
</template>

<style scoped>
.content-factory{display:grid;gap:1.5rem}.library-header,.card-heading,.card-actions{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start}.summary-grid,.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}.summary-grid article,.workflow-card{padding:1rem;border:1px solid #d8dee8;border-radius:1rem;background:#fff}.summary-grid article{display:grid}.summary-grid strong{font-size:1.8rem}.status-chip{padding:.25rem .55rem;border-radius:999px;background:#edf4f1;font-weight:700}.notice,.form-alert{padding:.8rem 1rem;border-radius:.75rem}.notice{background:#edf8f2;color:#225c42}.form-alert{background:#fff0ed;color:#79291d}.muted{color:#667085}.success{color:#187249;font-weight:700}.card-actions{justify-content:flex-end;flex-wrap:wrap}.dialog-backdrop{position:fixed;inset:0;z-index:40;display:grid;place-items:center;padding:1rem;background:rgba(20,31,45,.55)}.brief-editor{display:grid;gap:.8rem;width:min(560px,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.5rem;border-radius:1rem;background:#fff}.brief-editor label{display:grid;gap:.35rem}@media(max-width:600px){.library-header{display:grid}.card-actions{justify-content:stretch}.card-actions button{width:100%}}
</style>
