<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { useQuery, useQueryClient } from "@tanstack/vue-query"

import { ApiError } from "../../api/client"
import { formatOrdinaryError } from "../../shared/presentation/ordinary"
import { currentUserQueryOptions } from "../auth/auth"
import { listProducts, productQueryKeys } from "../products/api"
import { assetKeys, listAssets } from "../assets/api"
import ContentBriefWizard from "./ContentBriefWizard.vue"
import GuidedStepCard from "./components/GuidedStepCard.vue"
import {
  cancelJob, contentQueryKeys, generateMaster, getCursorPage, getJob, listBriefs,
  listApprovedBriefConcepts, listBriefConcepts, listCampaigns, listJobs, listMasterContents, listPlatformPage, markBriefReady,
  retryJob, reviseBrief, type ContentBrief, type Job,
} from "./api"
import { useCursorCollection } from "./useCursorCollection"

const props = withDefaults(defineProps<{
  experience?: "ordinary" | "advanced"
}>(), { experience: "advanced" })
const queryClient = useQueryClient()
const currentUserQuery = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUserQuery.data.value?.organization.id ?? "")
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const has = (permission: string) => permissions.value.includes(permission)
const enabled = computed(() => Boolean(organizationId.value))
const canReadCampaigns = computed(() => has("campaigns.read"))
const canManageCampaigns = computed(() => has("campaigns.manage"))
const canReadProducts = computed(() => has("products.read"))
const canReadAssets = computed(() => has("assets.read"))
const canReadKnowledge = computed(() => has("knowledge.read"))
const canReadJobs = computed(() => has("jobs.read"))
const canReadContent = computed(() => has("content.read"))
const canReadMemberships = computed(() => has("memberships.read"))
const campaignManagementMembershipId = computed(() => currentUserQuery.data.value?.membership.id ?? "")
let campaignManagementAuthorityGeneration = 0
watch(
  [organizationId, campaignManagementMembershipId, canManageCampaigns],
  () => { campaignManagementAuthorityGeneration += 1 },
  { flush: "sync" },
)
const wizardOpen = ref(false)
const notice = ref("")
const actionError = ref("")
const jobError = ref("")
const actionId = ref("")
const liveJobs = ref<Job[]>([])
type TrackedGeneration = { jobId: string; briefId: string; briefVersion: number; status: Job["status"] }
const trackedGeneration = ref<TrackedGeneration | null>(null)
type OrdinaryRecoveryPhase = "idle" | "checking" | "matched" | "exhausted" | "error"
const ordinaryRecoveryPageLimit = 100
const ordinaryRecoveryPhase = ref<OrdinaryRecoveryPhase>("idle")
const ordinaryRecoveryMessage = ref("")
let ordinaryRecoveryGeneration = 0
let ordinaryRecoveryController: AbortController | null = null
const editingBrief = ref<ContentBrief | null>(null)
const advancedRecordsOpen = ref(false)
const timers = new Set<ReturnType<typeof setTimeout>>()
const pollingJobs = new Map<string, string>()
const jobTimers = new Map<string, ReturnType<typeof setTimeout>>()
let disposed = false
const ordinaryExperience = computed(() => props.experience === "ordinary")
const ordinaryCreation = computed(() => ordinaryExperience.value && !editingBrief.value)
const promotionProductFilters = computed(() => ordinaryCreation.value ? { status: "ACTIVE" } as const : {})
const promotionAssetFilters = computed(() => ordinaryCreation.value ? { status: "ACTIVE" } as const : {})
const conceptQueryKey = computed(() => [
  ...contentQueryKeys.briefs(organizationId.value),
  ordinaryCreation.value ? "approved-concepts" : "all-concepts",
])
const showAdvancedRecords = computed(() => props.experience === "advanced" || advancedRecordsOpen.value)
const canObserveJobs = computed(() => canReadJobs.value && showAdvancedRecords.value)

const campaignsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.campaigns(organizationId.value)), queryFn: listCampaigns, enabled: computed(() => enabled.value && has("campaigns.read")) })
const briefsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.briefs(organizationId.value)), queryFn: () => listBriefs(), enabled: computed(() => enabled.value && has("campaigns.read")) })
const productsQuery = useQuery({ queryKey: computed(() => productQueryKeys.list(organizationId.value, promotionProductFilters.value)), queryFn: () => listProducts(promotionProductFilters.value), enabled: computed(() => enabled.value && has("products.read")) })
const platformsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.platforms(organizationId.value)), queryFn: listPlatformPage, enabled: computed(() => enabled.value && has("memberships.read")) })
const assetsQuery = useQuery({ queryKey: computed(() => assetKeys.list(organizationId.value, promotionAssetFilters.value)), queryFn: () => listAssets(promotionAssetFilters.value), enabled: computed(() => enabled.value && has("assets.read")) })
const conceptsQuery = useQuery({ queryKey: conceptQueryKey, queryFn: () => ordinaryCreation.value ? listApprovedBriefConcepts() : listBriefConcepts(), enabled: computed(() => enabled.value && has("knowledge.read")) })
const jobsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.jobs(organizationId.value)), queryFn: () => listJobs(), enabled: computed(() => enabled.value && canObserveJobs.value) })
const masterQuery = useQuery({ queryKey: computed(() => contentQueryKeys.masterContents(organizationId.value, {})), queryFn: () => listMasterContents(), enabled: computed(() => enabled.value && has("content.read")) })

const campaigns = useCursorCollection(campaignsQuery.data, "/api/v1/campaigns", organizationId, (item) => item.id)
const briefPages = useCursorCollection(briefsQuery.data, "/api/v1/content-briefs", organizationId, (item) => item.id)
const productPages = useCursorCollection(productsQuery.data, "/api/v1/products", organizationId, (item) => item.id)
const platformPages = useCursorCollection(platformsQuery.data, "/api/v1/platforms", organizationId, (item) => item.id)
const assetPages = useCursorCollection(assetsQuery.data, "/api/v1/assets", organizationId, (item) => item.id)
const conceptPages = useCursorCollection(conceptsQuery.data, "/api/v1/knowledge/concepts", organizationId, (item) => item.id)
const jobPages = useCursorCollection(jobsQuery.data, "/api/v1/jobs", organizationId, (item) => item.job_id)
const masterPages = useCursorCollection(masterQuery.data, "/api/v1/master-contents", organizationId, (item) => item.id)
const visibleCampaigns = computed(() => canReadCampaigns.value ? campaigns.items.value : [])
const briefs = computed(() => canReadCampaigns.value ? briefPages.items.value : [])
const visibleMasterContents = computed(() => canReadContent.value ? masterPages.items.value : [])
const visibleProducts = computed(() => canReadProducts.value ? productPages.items.value : [])
const visibleAssets = computed(() => canReadAssets.value ? assetPages.items.value : [])
const visibleConcepts = computed(() => canReadKnowledge.value ? conceptPages.items.value : [])
const eligibleProducts = computed(() => canReadProducts.value ? productPages.items.value.filter((product) => product.status === "ACTIVE") : [])
const eligibleAssets = computed(() => canReadAssets.value ? assetPages.items.value.filter((asset) => asset.status === "ACTIVE") : [])
const approvedConcepts = computed(() => canReadKnowledge.value ? conceptPages.items.value.filter((concept) => concept.status === "APPROVED") : [])
const jobs = computed(() => {
  if (!canObserveJobs.value && !trackedGeneration.value) return []
  const combined = [...(canObserveJobs.value ? jobPages.items.value : []), ...liveJobs.value]
  return [...new Map(combined.map((job) => [job.job_id, job])).values()]
})
const activeJobStatuses = new Set<Job["status"]>(["QUEUED", "RUNNING", "RETRY_QUEUED"])
const recoverableJobStatuses = new Set<Job["status"]>([...activeJobStatuses, "FAILED", "SUCCEEDED"])
const trackedJob = computed(() => trackedGeneration.value
  ? [...liveJobs.value, ...jobPages.items.value]
      .find((job) => job.job_id === trackedGeneration.value?.jobId) ?? null
  : null)
const generationInFlight = computed(() => Boolean(
  trackedGeneration.value && activeJobStatuses.has(trackedJob.value?.status ?? trackedGeneration.value.status),
))
const visibleJobError = computed(() => jobError.value || (jobsQuery.isError.value ? "生成记录暂时无法更新，请重新加载后再试。" : ""))
const visibleJobPageError = computed(() => jobPages.error.value
  ? ordinaryExperience.value ? "生成记录下一页暂时无法加载，请重新加载后再试。" : jobPages.error.value
  : "")
const proposalBlocker = computed(() => {
  if (!has("campaigns.manage")) return "你当前没有创建推广方案的权限，请联系管理员。"
  if (!has("products.read")) return "需要产品库查看权限，才能为真实产品准备推广方案。"
  if (!has("memberships.read")) return "需要组织成员查看权限，才能读取平台定义。"
  if (campaignsQuery.isPending.value && has("campaigns.read")) return "正在检查已有推广资料…"
  if (productsQuery.isPending.value || platformsQuery.isPending.value) return "正在检查产品和推广渠道…"
  if (campaignsQuery.isError.value && has("campaigns.read")) return "已有推广资料暂时没有加载成功，请重新检查后再试。"
  if (productsQuery.isError.value) return "产品资料暂时没有加载成功，请重新检查后再试。"
  if (platformsQuery.isError.value) return "推广渠道暂时没有加载成功，请重新检查后再试。"
  if (!eligibleProducts.value.length && productPages.next.value) return "还有产品资料未加载，请先加载后再继续。"
  if (!eligibleProducts.value.length) return "产品库还没有可推广的产品，请先补充产品资料。"
  if (!platformPages.items.value.length) return "还没有可用的推广渠道，请先请管理员完成渠道配置。"
  return ""
})
const canOpenProposal = computed(() => !proposalBlocker.value)
const latestBrief = computed(() => [...briefs.value].sort((left, right) => {
  const updatedDifference = Date.parse(right.updated_at) - Date.parse(left.updated_at)
  if (updatedDifference) return updatedDifference
  const createdDifference = Date.parse(right.created_at) - Date.parse(left.created_at)
  if (createdDifference) return createdDifference
  return right.version - left.version
})[0] ?? null)
const currentMaster = computed(() => {
  const brief = latestBrief.value
  if (!brief) return null
  return visibleMasterContents.value.find((master) => (
    master.brief_id === brief.id && master.brief_version === brief.version
  )) ?? null
})
const ordinaryRecoveryNeeded = computed(() => (
  ordinaryExperience.value && latestBrief.value?.status === "READY"
))
const ordinaryRecoveryScope = computed(() => {
  const brief = latestBrief.value
  if (!enabled.value || !ordinaryRecoveryNeeded.value || !canReadJobs.value || !brief) return ""
  return `${organizationId.value}:${brief.id}:${brief.version}`
})
const generationSubmissionBlocked = computed(() => generationInFlight.value || Boolean(
  trackedJob.value && ["FAILED", "SUCCEEDED"].includes(trackedJob.value.status),
) || Boolean(
  ordinaryRecoveryNeeded.value
  && (!canReadJobs.value || !["matched", "exhausted"].includes(ordinaryRecoveryPhase.value)),
))
const ordinaryRecoveryError = computed(() => ordinaryExperience.value && ordinaryRecoveryPhase.value === "error"
  ? ordinaryRecoveryMessage.value
  : "")
const guidedStep = computed(() => {
  if (currentMaster.value) return 6
  if (latestBrief.value?.status === "READY") return 5
  if (latestBrief.value) return 4
  return 1
})
const guidedState = (number: number): "current" | "complete" | "locked" => (
  number === guidedStep.value ? "current" : number < guidedStep.value ? "complete" : "locked"
)

const jobStatusLabels: Record<Job["status"], string> = {
  QUEUED: "等待开始",
  RUNNING: "正在生成",
  RETRY_QUEUED: "等待再次生成",
  SUCCEEDED: "生成完成",
  FAILED: "生成未完成",
  CANCELED: "已停止",
}

function jobStatusLabel(job: Job): string {
  return ordinaryExperience.value ? jobStatusLabels[job.status] : job.status
}

function openProposal(): void {
  if (!canOpenProposal.value) return
  wizardOpen.value = true
}

function safeError(error: unknown): string {
  if (ordinaryExperience.value) return formatOrdinaryError(error)
  if (error instanceof ApiError) return error.status === 409
    ? "状态已经变化，已为你刷新最新信息。"
    : error.userMessage
  return "操作没有完成，请稍后重试。"
}

function queryError(error: unknown, label: string): string {
  if (ordinaryExperience.value) return `${label}没有加载成功，请稍后重试。`
  return error instanceof ApiError ? error.userMessage : `${label}没有加载成功，请重试。`
}

function upsertJob(job: Job): void {
  liveJobs.value = [job, ...liveJobs.value.filter((item) => item.job_id !== job.job_id)]
}

function canPollJob(id: string): boolean {
  return canObserveJobs.value || Boolean(
    ordinaryExperience.value && canReadJobs.value && trackedGeneration.value?.jobId === id,
  )
}

function matchesCurrentBrief(job: Job, brief: ContentBrief): boolean {
  return job.type === "CONTENT_GENERATE"
    && job.source_reference?.brief_id === brief.id
    && job.source_reference.brief_version === brief.version
}

function cancelOrdinaryRecovery(): void {
  ordinaryRecoveryGeneration += 1
  ordinaryRecoveryController?.abort()
  ordinaryRecoveryController = null
}

async function startOrdinaryRecovery(): Promise<void> {
  cancelOrdinaryRecovery()
  ordinaryRecoveryMessage.value = ""
  const brief = latestBrief.value
  if (trackedGeneration.value && (!brief
    || trackedGeneration.value.briefId !== brief.id
    || trackedGeneration.value.briefVersion !== brief.version
  )) {
    stopPolling(trackedGeneration.value.jobId)
    trackedGeneration.value = null
  }

  const scope = ordinaryRecoveryScope.value
  if (!scope || !brief) {
    ordinaryRecoveryPhase.value = "idle"
    return
  }

  const generation = ordinaryRecoveryGeneration
  const controller = new AbortController()
  ordinaryRecoveryController = controller
  ordinaryRecoveryPhase.value = "checking"
  const stillCurrent = () => !disposed
    && ordinaryRecoveryGeneration === generation
    && ordinaryRecoveryController === controller
    && ordinaryRecoveryScope.value === scope

  try {
    let page = await listJobs(
      { type: "CONTENT_GENERATE", page_size: 50 },
      { signal: controller.signal },
    )
    const visitedCursors = new Set<string>()
    let scannedPages = 0
    while (stillCurrent()) {
      scannedPages += 1
      const recovered = page.results.find((job) => (
        matchesCurrentBrief(job, brief) && recoverableJobStatuses.has(job.status)
      ))
      if (recovered) {
        upsertJob(recovered)
        trackedGeneration.value = {
          jobId: recovered.job_id,
          briefId: brief.id,
          briefVersion: brief.version,
          status: recovered.status,
        }
        ordinaryRecoveryPhase.value = "matched"
        ordinaryRecoveryController = null
        if (activeJobStatuses.has(recovered.status)) beginPolling(recovered.job_id)
        else stopPolling(recovered.job_id)
        if (recovered.status === "SUCCEEDED" && !currentMaster.value && canReadContent.value) {
          void masterQuery.refetch()
        }
        return
      }

      if (!page.next) {
        ordinaryRecoveryPhase.value = "exhausted"
        ordinaryRecoveryController = null
        return
      }
      if (scannedPages >= ordinaryRecoveryPageLimit) throw new Error("Recovery page limit reached")
      if (visitedCursors.has(page.next)) throw new Error("Recovery cursor repeated")
      visitedCursors.add(page.next)
      page = await getCursorPage<Job>(page.next, "/api/v1/jobs", { signal: controller.signal })
    }
  } catch (error) {
    if (!stillCurrent() || (error && typeof error === "object" && "name" in error && error.name === "AbortError")) return
    ordinaryRecoveryPhase.value = "error"
    ordinaryRecoveryMessage.value = "生成记录暂时无法恢复，请重新检查后再试。"
    ordinaryRecoveryController = null
  }
}

function isActiveOrganization(scope: string): boolean {
  return !disposed && Boolean(scope) && organizationId.value === scope
}

function isActiveCampaignManagementSession(scope: string, membershipId: string, authorityGeneration: number): boolean {
  return isActiveOrganization(scope)
    && Boolean(membershipId)
    && currentUserQuery.data.value?.membership.id === membershipId
    && canManageCampaigns.value
    && campaignManagementAuthorityGeneration === authorityGeneration
}

async function pollJob(id: string, scope: string): Promise<void> {
  if (!canPollJob(id) || !isActiveOrganization(scope) || pollingJobs.get(id) !== scope) return
  try {
    const job = await getJob(id)
    if (!canPollJob(id) || !isActiveOrganization(scope) || pollingJobs.get(id) !== scope) return
    upsertJob(job)
    if (trackedGeneration.value?.jobId === id) trackedGeneration.value.status = job.status
    if (job.status === "SUCCEEDED") {
      if (canReadContent.value) await masterQuery.refetch()
      else await queryClient.invalidateQueries({ queryKey: contentQueryKeys.masterContents(scope, {}) })
      if (!isActiveOrganization(scope) || pollingJobs.get(id) !== scope) return
      stopPolling(id)
      return
    }
    if (!activeJobStatuses.has(job.status)) { stopPolling(id); return }
    const timer = setTimeout(() => {
      timers.delete(timer)
      jobTimers.delete(id)
      void pollJob(id, scope)
    }, 2500)
    timers.add(timer)
    jobTimers.set(id, timer)
  } catch {
    if (!isActiveOrganization(scope) || pollingJobs.get(id) !== scope) return
    stopPolling(id)
    jobError.value = "生成记录暂时无法更新，请重新加载后再试。"
  }
}

function stopPolling(id: string): void {
  const timer = jobTimers.get(id)
  if (timer) { clearTimeout(timer); timers.delete(timer); jobTimers.delete(id) }
  pollingJobs.delete(id)
}

function beginPolling(id: string): void {
  const scope = organizationId.value
  if (!canPollJob(id) || !isActiveOrganization(scope) || pollingJobs.get(id) === scope) return
  if (pollingJobs.has(id)) stopPolling(id)
  pollingJobs.set(id, scope)
  void pollJob(id, scope)
}

async function refreshJob(id: string): Promise<void> {
  const scope = organizationId.value
  const job = await getJob(id)
  if (!canPollJob(id) || !isActiveOrganization(scope)) return
  upsertJob(job)
  if (trackedGeneration.value?.jobId === id) trackedGeneration.value.status = job.status
  if (activeJobStatuses.has(job.status)) beginPolling(job.job_id)
}

async function startGeneration(brief: ContentBrief): Promise<void> {
  if (brief.status !== "READY" || !has("content.manage") || actionId.value || generationSubmissionBlocked.value) return
  actionId.value = brief.id
  jobError.value = ""
  const scope = organizationId.value
  try {
    const accepted = await generateMaster(brief.id)
    if (!isActiveOrganization(scope)) return
    if (ordinaryExperience.value) {
      trackedGeneration.value = {
        jobId: accepted.job_id, briefId: brief.id, briefVersion: brief.version, status: accepted.status,
      }
    }
    if (!liveJobs.value.some((job) => job.job_id === accepted.job_id)) {
      upsertJob({ job_id: accepted.job_id, type: "CONTENT_GENERATE", status: accepted.status, progress: 0, attempt: 1, max_attempts: 3, created_at: new Date().toISOString(), finished_at: null, error: null, result_reference: null, source_reference: { brief_id: brief.id, brief_version: brief.version } })
    }
    beginPolling(accepted.job_id)
  } catch (error) {
    if (isActiveOrganization(scope)) jobError.value = ordinaryExperience.value ? "生成请求暂时没有提交成功，请稍后再试。" : safeError(error)
  } finally {
    if (isActiveOrganization(scope)) actionId.value = ""
  }
}

async function ready(brief: ContentBrief): Promise<void> {
  if (brief.status !== "DRAFT" || !has("campaigns.review")) return
  actionId.value = brief.id
  const scope = organizationId.value
  try {
    await markBriefReady(brief.id)
    await queryClient.invalidateQueries({ queryKey: contentQueryKeys.briefs(scope) })
    if (!isActiveOrganization(scope)) return
    notice.value = "需求已确认，可以开始生成。"
  } catch (error) {
    if (isActiveOrganization(scope)) actionError.value = safeError(error)
  } finally {
    if (isActiveOrganization(scope)) actionId.value = ""
  }
}

function openBriefEditor(brief: ContentBrief): void {
  if (brief.status !== "DRAFT" || !has("campaigns.manage")) return
  editingBrief.value = brief
}

async function createBriefRevision(brief: ContentBrief): Promise<void> {
  if (brief.status !== "READY" || !has("campaigns.manage")) return
  const scope = organizationId.value
  const membershipId = campaignManagementMembershipId.value
  const authorityGeneration = campaignManagementAuthorityGeneration
  try {
    const revision = await reviseBrief(brief.id)
    if (!isActiveCampaignManagementSession(scope, membershipId, authorityGeneration)) return
    await queryClient.invalidateQueries({ queryKey: contentQueryKeys.briefs(scope) })
    if (!isActiveCampaignManagementSession(scope, membershipId, authorityGeneration)) return
    editingBrief.value = revision
    notice.value = "已从可生成需求创建新的草稿版本，请检查并保存。"
  } catch (error) {
    if (isActiveCampaignManagementSession(scope, membershipId, authorityGeneration)) actionError.value = safeError(error)
  }
}

async function jobAction(job: Job, action: "cancel" | "retry"): Promise<void> {
  if (!has("jobs.manage")) return
  const legal = action === "cancel" ? activeJobStatuses.has(job.status) : job.status === "FAILED"
  if (!legal) return
  const scope = organizationId.value
  try {
    const updated = action === "cancel" ? await cancelJob(job.job_id) : await retryJob(job.job_id)
    if (!isActiveOrganization(scope)) return
    upsertJob(updated)
    if (trackedGeneration.value?.jobId === updated.job_id) trackedGeneration.value.status = updated.status
    if (activeJobStatuses.has(updated.status)) beginPolling(updated.job_id)
    else stopPolling(updated.job_id)
  } catch (error) {
    if (!isActiveOrganization(scope)) return
    jobError.value = ordinaryExperience.value ? "生成记录暂时无法更新，请重新加载后再试。" : safeError(error)
    if (error instanceof ApiError && error.status === 409) await refreshJob(job.job_id)
  }
}

async function reloadJobs(): Promise<void> {
  jobError.value = ""
  await jobsQuery.refetch()
}

async function saved(): Promise<void> {
  const wasEditing = Boolean(editingBrief.value)
  wizardOpen.value = false
  editingBrief.value = null
  notice.value = ordinaryExperience.value
    ? wasEditing ? "推广方案已更新。" : "推广方案已保存，等待有权限的同事确认。"
    : wasEditing ? "需求草稿已更新。" : "内容需求已创建，等待审核人员确认。"
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: contentQueryKeys.campaigns(organizationId.value) }),
    queryClient.invalidateQueries({ queryKey: contentQueryKeys.briefs(organizationId.value) }),
  ])
}

watch(organizationId, (current, previous) => {
  if (!previous || current === previous) return
  for (const id of [...pollingJobs.keys()]) stopPolling(id)
  liveJobs.value = []
  trackedGeneration.value = null
  wizardOpen.value = false
  editingBrief.value = null
  notice.value = ""
  actionError.value = ""
  jobError.value = ""
  actionId.value = ""
})

function cancelAndClear(queryKey: readonly unknown[]): void {
  void queryClient.cancelQueries({ queryKey })
  queryClient.removeQueries({ queryKey })
}

watch(canReadCampaigns, (current, previous) => {
  if (!previous || current) return
  const scope = organizationId.value
  campaigns.reset()
  briefPages.reset()
  wizardOpen.value = false
  editingBrief.value = null
  cancelAndClear(contentQueryKeys.campaigns(scope))
  cancelAndClear(contentQueryKeys.briefs(scope))
}, { flush: "sync" })

watch(canReadProducts, (current, previous) => {
  if (!previous || current) return
  productPages.reset()
  wizardOpen.value = false
  editingBrief.value = null
  cancelAndClear(productQueryKeys.lists(organizationId.value))
}, { flush: "sync" })

watch(canReadAssets, (current, previous) => {
  if (!previous || current) return
  assetPages.reset()
  wizardOpen.value = false
  editingBrief.value = null
  cancelAndClear(assetKeys.all(organizationId.value))
}, { flush: "sync" })

watch(canReadKnowledge, (current, previous) => {
  if (!previous || current) return
  conceptPages.reset()
  wizardOpen.value = false
  editingBrief.value = null
  cancelAndClear(conceptQueryKey.value)
}, { flush: "sync" })

watch(canManageCampaigns, (current, previous) => {
  if (!previous || current) return
  wizardOpen.value = false
  editingBrief.value = null
  actionId.value = ""
}, { flush: "sync" })

watch(canReadJobs, (current, previous) => {
  if (!previous || current) return
  for (const id of [...pollingJobs.keys()]) stopPolling(id)
  liveJobs.value = []
  trackedGeneration.value = null
  jobError.value = ""
  jobPages.reset()
  cancelAndClear(contentQueryKeys.jobs(organizationId.value))
}, { flush: "sync" })

watch(canObserveJobs, (current, previous) => {
  if (!previous || current) return
  for (const id of [...pollingJobs.keys()]) if (!canPollJob(id)) stopPolling(id)
  if (!ordinaryExperience.value) {
    liveJobs.value = []
    jobError.value = ""
  }
}, { flush: "sync" })

watch(editingBrief, () => {
  productPages.reset()
  assetPages.reset()
  conceptPages.reset()
}, { flush: "sync" })

watch(ordinaryRecoveryScope, () => { void startOrdinaryRecovery() }, { immediate: true, flush: "sync" })

watch(canReadContent, (current, previous) => {
  if (!previous || current) return
  masterPages.reset()
  cancelAndClear(contentQueryKeys.masterContents(organizationId.value, {}))
}, { flush: "sync" })

watch(canReadMemberships, (current, previous) => {
  if (!previous || current) return
  platformPages.reset()
  wizardOpen.value = false
  editingBrief.value = null
  cancelAndClear(contentQueryKeys.platforms(organizationId.value))
}, { flush: "sync" })

watch(jobs, (items) => {
  for (const job of items) if (activeJobStatuses.has(job.status)) beginPolling(job.job_id)
}, { immediate: true })

onBeforeUnmount(() => { disposed = true; cancelOrdinaryRecovery(); for (const timer of timers) clearTimeout(timer); timers.clear(); jobTimers.clear(); pollingJobs.clear() })
</script>

<template>
  <div class="page-stack content-factory" aria-labelledby="factory-title">
    <template v-if="ordinaryExperience">
      <header class="promotion-header">
        <div><p class="eyebrow">AI 推广助手</p><h1 id="factory-title">你今天想推广什么？</h1><p>从现有产品和资料出发，AI 会陪你整理方案；只有你确认后，才会进入执行。</p></div>
        <button v-if="guidedStep > 1 && has('campaigns.manage')" type="button" :disabled="!canOpenProposal" @click="openProposal">开始新的推广</button>
      </header>

      <ol class="guided-flow" aria-label="推广流程">
        <GuidedStepCard :number="1" title="选择产品" description="先从真实产品库中选择这次要推广的产品。" :state="guidedState(1)">
          <div class="readiness-grid" aria-label="推广资料准备情况">
            <article><strong>{{ has('products.read') ? `已加载 ${eligibleProducts.length} 项` : '—' }}</strong><span>可推广产品</span><small>{{ has('products.read') ? '来自当前组织的可用产品；数字仅代表已加载页' : '没有产品库查看权限' }}</small><button v-if="has('products.read') && productsQuery.isError.value" type="button" @click="productsQuery.refetch()">重新检查产品资料</button><button v-else-if="has('products.read') && !eligibleProducts.length && productPages.next.value" type="button" @click="productPages.loadMore">加载更多产品资料</button></article>
            <article><strong>{{ has('memberships.read') ? `已加载 ${platformPages.items.value.length} 项` : '—' }}</strong><span>可选推广渠道</span><small>来自系统支持的渠道定义，不代表账号已连接</small><button v-if="has('memberships.read') && platformsQuery.isError.value" type="button" @click="platformsQuery.refetch()">重新检查渠道定义</button></article>
            <article><strong>{{ has('assets.read') ? `已加载 ${eligibleAssets.length} 项` : '—' }}</strong><span>可用素材</span><small>{{ has('assets.read') ? '来自当前可用素材；数字仅代表已加载页' : '没有素材库查看权限，不影响先整理方案' }}</small><button v-if="has('assets.read') && assetsQuery.isError.value" type="button" @click="assetsQuery.refetch()">重新检查素材</button></article>
            <article><strong>{{ has('knowledge.read') ? `已加载 ${approvedConcepts.length} 项` : '—' }}</strong><span>已批准知识</span><small>{{ has('knowledge.read') ? '仅包含已批准知识；数字仅代表已加载页' : '没有知识库查看权限，不会代填知识' }}</small><button v-if="has('knowledge.read') && conceptsQuery.isError.value" type="button" @click="conceptsQuery.refetch()">重新检查知识资料</button></article>
          </div>
          <div class="promotion-action"><button v-if="has('campaigns.manage')" class="primary-action" type="button" :disabled="!canOpenProposal" @click="openProposal">选择产品并继续</button><p v-if="proposalBlocker" class="muted" role="status">{{ proposalBlocker }}</p><button v-if="has('campaigns.read') && campaignsQuery.isError.value" type="button" @click="campaignsQuery.refetch()">重新检查已有推广资料</button></div>
        </GuidedStepCard>
        <GuidedStepCard :number="2" title="告诉 AI 目标" description="选择市场、受众和这次推广要达成的结果。" :state="guidedState(2)" />
        <GuidedStepCard :number="3" title="查看可用素材" description="核对来自素材库和知识库的真实资料。" :state="guidedState(3)" />
        <GuidedStepCard :number="4" title="确认方案" description="检查方案后，再交给有权限的同事确认。" :state="guidedState(4)">
          <div v-if="latestBrief" class="card-actions"><button v-if="latestBrief.status === 'DRAFT' && has('campaigns.manage')" type="button" @click="openBriefEditor(latestBrief)">查看并修改方案</button><button v-if="latestBrief.status === 'DRAFT' && has('campaigns.review')" class="primary-action" type="button" :disabled="actionId === latestBrief.id" @click="ready(latestBrief)">确认方案可生成</button><p v-else-if="latestBrief.status === 'DRAFT'" class="muted">方案正在等待有权限的同事确认。</p></div>
        </GuidedStepCard>
        <GuidedStepCard :number="5" title="生成内容" description="确认方案后，才会提交真实的内容生成任务。" :state="guidedState(5)"><p v-if="trackedJob" role="status">{{ jobStatusLabel(trackedJob) }}<span v-if="activeJobStatuses.has(trackedJob.status)"> · {{ trackedJob.progress }}%</span></p><p v-if="jobError" role="alert">{{ jobError }} <button v-if="trackedGeneration" type="button" @click="beginPolling(trackedGeneration.jobId)">重新检查生成进度</button></p><p v-if="ordinaryRecoveryError" role="alert">{{ ordinaryRecoveryError }} <button type="button" @click="startOrdinaryRecovery">重新检查生成记录</button></p><button v-if="trackedJob?.status === 'FAILED' && has('jobs.manage')" type="button" @click="jobAction(trackedJob, 'retry')">再次尝试</button><button v-if="latestBrief?.status === 'READY' && has('content.manage')" class="primary-action" type="button" :disabled="Boolean(actionId) || generationSubmissionBlocked" @click="startGeneration(latestBrief)">生成推广内容</button><p v-else class="muted">需要内容管理权限才能生成。</p></GuidedStepCard>
        <GuidedStepCard :number="6" title="批准发布" description="查看生成结果、填写拒绝原因或批准进入发布流程。" :state="guidedState(6)"><a class="primary-action button-link" href="/reviews">查看并确认</a></GuidedStepCard>
      </ol>

      <button class="advanced-disclosure" type="button" :aria-expanded="advancedRecordsOpen" @click="advancedRecordsOpen = !advancedRecordsOpen">
        {{ advancedRecordsOpen ? '收起高级记录' : '查看高级记录' }}
      </button>
    </template>
    <header v-else class="library-header"><div><p class="eyebrow">从需求到可审核内容</p><h1 id="factory-title">AI 内容工厂</h1><p>按“准备需求、提交审核、AI 生成、查看结果”四步完成内容生产。</p></div><button v-if="has('campaigns.manage')" class="primary-action" type="button" @click="wizardOpen = true">创建内容任务</button></header>
    <p v-if="notice" role="status" class="notice">{{ notice }}</p><p v-if="actionError" role="alert" class="form-alert">{{ actionError }}</p>
    <section v-if="showAdvancedRecords" class="query-errors" aria-label="数据加载问题">
      <p v-if="has('campaigns.read') && campaignsQuery.isError.value" role="alert">{{ queryError(campaignsQuery.error.value, '活动') }} <button type="button" @click="campaignsQuery.refetch()">重新加载活动</button></p>
      <p v-if="has('campaigns.read') && briefsQuery.isError.value" role="alert">{{ queryError(briefsQuery.error.value, '内容需求') }} <button type="button" @click="briefsQuery.refetch()">重新加载内容需求</button></p>
      <p v-if="has('products.read') && productsQuery.isError.value" role="alert">{{ queryError(productsQuery.error.value, '产品') }} <button type="button" @click="productsQuery.refetch()">重新加载产品</button></p>
      <p v-if="has('memberships.read') && platformsQuery.isError.value" role="alert">{{ queryError(platformsQuery.error.value, '平台') }} <button type="button" @click="platformsQuery.refetch()">重新加载平台</button></p>
      <p v-if="has('assets.read') && assetsQuery.isError.value" role="alert">{{ queryError(assetsQuery.error.value, '素材') }} <button type="button" @click="assetsQuery.refetch()">重新加载素材</button></p>
      <p v-if="has('content.read') && masterQuery.isError.value" role="alert">{{ queryError(masterQuery.error.value, '生成结果') }} <button type="button" @click="masterQuery.refetch()">重新加载生成结果</button></p>
    </section>
    <section v-if="showAdvancedRecords" class="summary-grid" aria-label="当前工作摘要"><article><strong>{{ visibleCampaigns.length }}</strong><span>活动</span></article><article><strong>{{ briefs.length }}</strong><span>内容需求</span></article><article><strong>{{ jobs.length }}</strong><span>生成任务</span></article><article><strong>{{ visibleMasterContents.length }}</strong><span>生成结果</span><button v-if="has('content.read') && masterPages.next.value" type="button" @click="masterPages.loadMore">加载更多生成结果</button><span v-if="has('content.read') && masterPages.error.value" role="alert">{{ masterPages.error.value }} <button type="button" @click="masterPages.loadMore">重试</button></span></article></section>

    <template v-if="showAdvancedRecords">
      <section v-if="has('campaigns.read')" aria-labelledby="campaigns-title"><h2 id="campaigns-title">推广活动</h2><p v-if="campaignsQuery.isPending.value" role="status">正在加载推广活动…</p><div v-else-if="visibleCampaigns.length" class="card-grid"><article v-for="campaign in visibleCampaigns" :key="campaign.id" class="workflow-card"><h3>{{ campaign.name }}</h3><p class="muted">{{ campaign.description || '没有补充说明' }}</p></article></div><p v-else class="muted">还没有推广活动。</p><p v-if="campaigns.error.value" role="alert">{{ campaigns.error.value }} <button type="button" @click="campaigns.loadMore">重试</button></p><button v-else-if="campaigns.next.value" type="button" @click="campaigns.loadMore">加载更多推广活动</button></section>

      <section v-if="has('campaigns.read')" aria-labelledby="briefs-title"><h2 id="briefs-title">内容需求</h2><p v-if="briefsQuery.isPending.value" role="status">正在加载内容需求…</p><div v-else-if="!briefs.length" class="state-panel"><h3>还没有内容需求</h3><p>从“创建内容任务”开始，向导会帮你准备完整信息。</p></div><div v-else class="card-grid"><article v-for="item in briefs" :key="item.id" class="workflow-card"><div class="card-heading"><h3>{{ visibleCampaigns.find(c => c.id === item.campaign_id)?.name || '内容需求' }}</h3><span class="status-chip">{{ item.status === 'READY' ? '可生成' : '需求草稿' }}</span></div><p>{{ item.target_country }} · {{ item.customer_type }} · {{ item.language }}</p><p v-if="item.status === 'DRAFT' && !has('campaigns.review')" class="muted">等待审核人员确认</p><div class="card-actions"><button v-if="item.status === 'DRAFT' && has('campaigns.manage')" type="button" @click="openBriefEditor(item)">编辑需求草稿</button><button v-if="item.status === 'DRAFT' && has('campaigns.review')" type="button" :disabled="actionId === item.id" @click="ready(item)">确认需求可生成</button><button v-if="item.status === 'READY' && has('campaigns.manage')" type="button" @click="createBriefRevision(item)">创建需求修订版</button><button v-if="item.status === 'READY' && has('content.manage')" class="primary-action" type="button" :disabled="Boolean(actionId)" @click="startGeneration(item)">开始AI生成</button></div></article></div><p v-if="briefPages.error.value" role="alert">{{ briefPages.error.value }} <button type="button" @click="briefPages.loadMore">重试</button></p><button v-else-if="briefPages.next.value" type="button" @click="briefPages.loadMore">加载更多内容需求</button></section>

      <section v-if="has('jobs.read')" aria-labelledby="jobs-title"><h2 id="jobs-title">生成任务</h2><p v-if="visibleJobError" role="alert">{{ visibleJobError }} <button type="button" @click="reloadJobs">重新加载生成记录</button></p><div v-if="jobs.length" class="card-grid"><article v-for="(job, index) in jobs" :key="job.job_id" class="workflow-card"><div class="card-heading"><h3>{{ ordinaryExperience ? `第 ${index + 1} 项生成记录` : `任务 ${job.job_id}` }}</h3><span class="status-chip">{{ jobStatusLabel(job) }}</span></div><p>进度 {{ job.progress }}% · 第 {{ job.attempt }}/{{ job.max_attempts }} 次</p><p v-if="job.status === 'SUCCEEDED'" class="success">生成完成</p><p v-else-if="job.status === 'FAILED'" role="alert">{{ ordinaryExperience ? '这次没有生成完成，你可以再次尝试。' : job.error?.message || '生成未完成，可以重试。' }}</p><div class="card-actions"><button v-if="has('jobs.manage') && activeJobStatuses.has(job.status)" type="button" @click="jobAction(job,'cancel')">{{ ordinaryExperience ? '停止生成' : '取消任务' }}</button><button v-if="has('jobs.manage') && job.status === 'FAILED'" type="button" @click="jobAction(job,'retry')">{{ ordinaryExperience ? '再次尝试' : '重新尝试' }}</button></div></article></div><p v-else class="muted">提交生成后，进度会显示在这里。</p><p v-if="visibleJobPageError" role="alert">{{ visibleJobPageError }} <button type="button" @click="jobPages.loadMore">{{ ordinaryExperience ? '重新加载更多生成记录' : '重试' }}</button></p><button v-else-if="jobPages.next.value" type="button" @click="jobPages.loadMore">加载更多生成任务</button></section>
    </template>

    <ContentBriefWizard v-if="wizardOpen || editingBrief" :experience="experience" :brief="editingBrief" :campaigns="visibleCampaigns" :products="ordinaryCreation ? eligibleProducts : visibleProducts" :platforms="platformPages.items.value" :assets="ordinaryCreation ? eligibleAssets : visibleAssets" :concepts="ordinaryCreation ? approvedConcepts : visibleConcepts" :more="{ campaigns: Boolean(campaigns.next.value), products: Boolean(productPages.next.value), platforms: Boolean(platformPages.next.value), assets: Boolean(assetPages.next.value), concepts: Boolean(conceptPages.next.value) }" :page-errors="{ campaigns: campaigns.error.value, products: productPages.error.value, platforms: platformPages.error.value, assets: assetPages.error.value, concepts: conceptPages.error.value }" @load-more="(kind) => ({ campaigns, products: productPages, platforms: platformPages, assets: assetPages, concepts: conceptPages })[kind].loadMore()" @close="wizardOpen = false; editingBrief = null" @saved="saved" />
  </div>
</template>

<style scoped>
.content-factory{display:grid;gap:1.5rem}.library-header,.promotion-header,.card-heading,.card-actions{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start}.promotion-header{padding:1.5rem;border-radius:1.25rem;background:linear-gradient(135deg,#f2f8f5,#f7f3ea)}.promotion-header>div:first-child{max-width:680px}.promotion-action{display:flex;align-items:center;flex-wrap:wrap;gap:.75rem}.promotion-action p{margin:0}.guided-flow{display:grid;gap:.8rem;padding:0;margin:0}.readiness-grid,.summary-grid,.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}.readiness-grid article,.summary-grid article,.workflow-card{padding:1rem;border:1px solid #d8dee8;border-radius:1rem;background:#fff}.readiness-grid article,.summary-grid article{display:grid;gap:.25rem}.readiness-grid strong,.summary-grid strong{font-size:1.35rem}.readiness-grid small{color:#667085}.advanced-disclosure{justify-self:start}.status-chip{padding:.25rem .55rem;border-radius:999px;background:#edf4f1;font-weight:700}.notice,.form-alert{padding:.8rem 1rem;border-radius:.75rem}.notice{background:#edf8f2;color:#225c42}.form-alert{background:#fff0ed;color:#79291d}.muted{color:#667085}.success{color:#187249;font-weight:700}.card-actions{justify-content:flex-end;flex-wrap:wrap}.button-link{display:inline-flex;width:max-content;text-decoration:none}.dialog-backdrop{position:fixed;inset:0;z-index:40;display:grid;place-items:center;padding:1rem;background:rgba(20,31,45,.55)}.brief-editor{display:grid;gap:.8rem;width:min(560px,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.5rem;border-radius:1rem;background:#fff}.brief-editor label{display:grid;gap:.35rem}@media(max-width:700px){.library-header,.promotion-header{display:grid}.card-actions{justify-content:stretch}.card-actions button{width:100%}.readiness-grid{grid-template-columns:1fr}}
</style>
