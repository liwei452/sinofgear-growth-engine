<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { useQuery, useQueryClient } from "@tanstack/vue-query"

import { ApiError } from "../../api/client"
import { currentUserQueryOptions } from "../auth/auth"
import { listProducts, productQueryKeys } from "../products/api"
import ContentBriefWizard from "./ContentBriefWizard.vue"
import {
  cancelJob, contentQueryKeys, generateMaster, getJob, listAssets, listBriefs,
  listCampaigns, listJobs, listMasterContents, listPlatforms, markBriefReady,
  patchBrief, retryJob, reviseBrief, type ContentBrief, type Job,
} from "./api"

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
const editForm = ref({ target_country: "", customer_type: "", content_objective: "", cta: "", landing_page_url: "", language: "" })
const timers = new Set<ReturnType<typeof setTimeout>>()
const pollingJobs = new Set<string>()
const jobTimers = new Map<string, ReturnType<typeof setTimeout>>()

const campaignsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.campaigns(organizationId.value)), queryFn: listCampaigns, enabled })
const briefsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.briefs(organizationId.value)), queryFn: () => listBriefs(), enabled })
const productsQuery = useQuery({ queryKey: computed(() => productQueryKeys.list(organizationId.value, {})), queryFn: () => listProducts(), enabled })
const platformsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.platforms(organizationId.value)), queryFn: listPlatforms, enabled })
const assetsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.assets(organizationId.value)), queryFn: listAssets, enabled: computed(() => enabled.value && has("assets.read")) })
const jobsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.jobs(organizationId.value)), queryFn: () => listJobs(), enabled: computed(() => enabled.value && has("jobs.read")) })
const masterQuery = useQuery({ queryKey: computed(() => contentQueryKeys.masterContents(organizationId.value, {})), queryFn: () => listMasterContents(), enabled: computed(() => enabled.value && has("content.read")) })

const briefs = computed(() => briefsQuery.data.value?.results ?? [])
const jobs = computed(() => {
  const combined = [...(jobsQuery.data.value?.results ?? []), ...liveJobs.value]
  return [...new Map(combined.map((job) => [job.job_id, job])).values()]
})
const activeJobStatuses = new Set(["QUEUED", "RUNNING", "RETRY_QUEUED"])

function safeError(error: unknown): string {
  if (error instanceof ApiError) return error.status === 409
    ? "状态已经变化，已为你刷新最新信息。"
    : error.userMessage
  return "操作没有完成，请稍后重试。"
}

function upsertJob(job: Job): void {
  liveJobs.value = [job, ...liveJobs.value.filter((item) => item.job_id !== job.job_id)]
}

async function pollJob(id: string): Promise<void> {
  try {
    const job = await getJob(id)
    upsertJob(job)
    if (job.status === "SUCCEEDED") {
      await queryClient.invalidateQueries({ queryKey: contentQueryKeys.masterContents(organizationId.value, {}) })
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
  } catch (error) { stopPolling(id); actionError.value = safeError(error) }
}

function stopPolling(id: string): void {
  const timer = jobTimers.get(id)
  if (timer) { clearTimeout(timer); timers.delete(timer); jobTimers.delete(id) }
  pollingJobs.delete(id)
}

function beginPolling(id: string): void {
  if (pollingJobs.has(id)) return
  pollingJobs.add(id)
  void pollJob(id)
}

async function startGeneration(brief: ContentBrief): Promise<void> {
  if (brief.status !== "READY" || !has("content.manage") || actionId.value) return
  actionId.value = brief.id
  actionError.value = ""
  try {
    const accepted = await generateMaster(brief.id)
    if (!jobs.value.some((job) => job.job_id === accepted.job_id)) {
      upsertJob({ job_id: accepted.job_id, type: "CONTENT_GENERATE", status: accepted.status, progress: 0, attempt: 1, max_attempts: 3, created_at: new Date().toISOString(), finished_at: null, error: null, result_reference: null })
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
  editForm.value = {
    target_country: brief.target_country, customer_type: brief.customer_type,
    content_objective: brief.content_objective, cta: brief.cta,
    landing_page_url: brief.landing_page_url, language: brief.language,
  }
}

async function saveBrief(): Promise<void> {
  if (!editingBrief.value || editingBrief.value.status !== "DRAFT" || !has("campaigns.manage")) return
  try {
    await patchBrief(editingBrief.value.id, editForm.value)
    editingBrief.value = null
    await queryClient.invalidateQueries({ queryKey: contentQueryKeys.briefs(organizationId.value) })
    notice.value = "需求草稿已更新。"
  } catch (error) { actionError.value = safeError(error) }
}

async function createBriefRevision(brief: ContentBrief): Promise<void> {
  if (brief.status !== "READY" || !has("campaigns.manage")) return
  try {
    await reviseBrief(brief.id)
    await queryClient.invalidateQueries({ queryKey: contentQueryKeys.briefs(organizationId.value) })
    notice.value = "已从可生成需求创建新的草稿版本。"
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
    if (error instanceof ApiError && error.status === 409) await pollJob(job.job_id)
  }
}

async function created(): Promise<void> {
  wizardOpen.value = false
  notice.value = "内容需求已创建，等待审核人员确认。"
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: contentQueryKeys.campaigns(organizationId.value) }),
    queryClient.invalidateQueries({ queryKey: contentQueryKeys.briefs(organizationId.value) }),
  ])
}

watch(jobs, (items) => {
  for (const job of items) if (activeJobStatuses.has(job.status)) beginPolling(job.job_id)
}, { immediate: true })

onBeforeUnmount(() => { for (const timer of timers) clearTimeout(timer); timers.clear(); jobTimers.clear(); pollingJobs.clear() })
</script>

<template>
  <main class="page-stack content-factory" aria-labelledby="factory-title">
    <header class="library-header"><div><p class="eyebrow">从需求到可审核内容</p><h1 id="factory-title">AI 内容工厂</h1><p>按“准备需求、提交审核、AI 生成、查看结果”四步完成内容生产。</p></div><button v-if="has('campaigns.manage')" class="primary-action" type="button" @click="wizardOpen = true">创建内容任务</button></header>
    <p v-if="notice" role="status" class="notice">{{ notice }}</p><p v-if="actionError" role="alert" class="form-alert">{{ actionError }}</p>
    <section class="summary-grid" aria-label="当前工作摘要"><article><strong>{{ campaignsQuery.data.value?.results.length ?? 0 }}</strong><span>活动</span></article><article><strong>{{ briefs.length }}</strong><span>内容需求</span></article><article><strong>{{ jobs.length }}</strong><span>生成任务</span></article><article><strong>{{ masterQuery.data.value?.results.length ?? 0 }}</strong><span>生成结果</span></article></section>

    <section aria-labelledby="briefs-title"><h2 id="briefs-title">内容需求</h2><p v-if="briefsQuery.isPending.value" role="status">正在加载内容需求…</p><div v-else-if="!briefs.length" class="state-panel"><h3>还没有内容需求</h3><p>从“创建内容任务”开始，向导会帮你准备完整信息。</p></div><div v-else class="card-grid"><article v-for="item in briefs" :key="item.id" class="workflow-card"><div class="card-heading"><h3>{{ campaignsQuery.data.value?.results.find(c => c.id === item.campaign_id)?.name || '内容需求' }}</h3><span class="status-chip">{{ item.status === 'READY' ? '可生成' : '需求草稿' }}</span></div><p>{{ item.target_country }} · {{ item.customer_type }} · {{ item.language }}</p><p v-if="item.status === 'DRAFT' && !has('campaigns.review')" class="muted">等待审核人员确认</p><div class="card-actions"><button v-if="item.status === 'DRAFT' && has('campaigns.manage')" type="button" @click="openBriefEditor(item)">编辑需求草稿</button><button v-if="item.status === 'DRAFT' && has('campaigns.review')" type="button" :disabled="actionId === item.id" @click="ready(item)">确认需求可生成</button><button v-if="item.status === 'READY' && has('campaigns.manage')" type="button" @click="createBriefRevision(item)">创建需求修订版</button><button v-if="item.status === 'READY' && has('content.manage')" class="primary-action" type="button" :disabled="Boolean(actionId)" @click="startGeneration(item)">开始AI生成</button></div></article></div></section>

    <div v-if="editingBrief" class="dialog-backdrop"><form class="brief-editor" role="dialog" aria-modal="true" aria-labelledby="brief-editor-title" @submit.prevent="saveBrief"><h2 id="brief-editor-title">编辑需求草稿</h2><label>目标国家<input v-model="editForm.target_country" required></label><label>客户类型<input v-model="editForm.customer_type" required></label><label>内容目标<input v-model="editForm.content_objective" required></label><label>行动号召<input v-model="editForm.cta" required></label><label>落地页<input v-model="editForm.landing_page_url" type="url" required></label><label>语言<input v-model="editForm.language" required></label><div class="card-actions"><button type="button" @click="editingBrief = null">取消</button><button class="primary-action" type="submit">保存需求草稿</button></div></form></div>

    <section aria-labelledby="jobs-title"><h2 id="jobs-title">生成任务</h2><div v-if="jobs.length" class="card-grid"><article v-for="job in jobs" :key="job.job_id" class="workflow-card"><div class="card-heading"><h3>任务 {{ job.job_id }}</h3><span class="status-chip">{{ job.status }}</span></div><p>进度 {{ job.progress }}% · 第 {{ job.attempt }}/{{ job.max_attempts }} 次</p><p v-if="job.status === 'SUCCEEDED'" class="success">生成完成</p><p v-else-if="job.status === 'FAILED'" role="alert">{{ job.error?.message || '生成未完成，可以重试。' }}</p><div class="card-actions"><button v-if="has('jobs.manage') && activeJobStatuses.has(job.status)" type="button" @click="jobAction(job,'cancel')">取消任务</button><button v-if="has('jobs.manage') && job.status === 'FAILED'" type="button" @click="jobAction(job,'retry')">重新尝试</button></div></article></div><p v-else class="muted">提交生成后，进度会显示在这里。</p></section>

    <ContentBriefWizard v-if="wizardOpen" :campaigns="campaignsQuery.data.value?.results ?? []" :products="productsQuery.data.value?.results ?? []" :platforms="platformsQuery.data.value ?? []" :assets="assetsQuery.data.value?.results ?? []" @close="wizardOpen = false" @saved="created" />
  </main>
</template>

<style scoped>
.content-factory{display:grid;gap:1.5rem}.library-header,.card-heading,.card-actions{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start}.summary-grid,.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}.summary-grid article,.workflow-card{padding:1rem;border:1px solid #d8dee8;border-radius:1rem;background:#fff}.summary-grid article{display:grid}.summary-grid strong{font-size:1.8rem}.status-chip{padding:.25rem .55rem;border-radius:999px;background:#edf4f1;font-weight:700}.notice,.form-alert{padding:.8rem 1rem;border-radius:.75rem}.notice{background:#edf8f2;color:#225c42}.form-alert{background:#fff0ed;color:#79291d}.muted{color:#667085}.success{color:#187249;font-weight:700}.card-actions{justify-content:flex-end;flex-wrap:wrap}.dialog-backdrop{position:fixed;inset:0;z-index:40;display:grid;place-items:center;padding:1rem;background:rgba(20,31,45,.55)}.brief-editor{display:grid;gap:.8rem;width:min(560px,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.5rem;border-radius:1rem;background:#fff}.brief-editor label{display:grid;gap:.35rem}@media(max-width:600px){.library-header{display:grid}.card-actions{justify-content:stretch}.card-actions button{width:100%}}
</style>
