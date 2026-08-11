import { ApiError, apiRequest, type ApiRequestOptions } from "../../api/client"

export type CursorPage<T> = { next: string | null; previous: string | null; results: T[] }
export type Campaign = {
  id: string; name: string; description: string; status: "DRAFT" | "ACTIVE" | "ARCHIVED"
  version: number; product_ids: string[]; created_at: string; updated_at: string
}
export type ContentBrief = {
  id: string; campaign_id: string; previous_version_id: string | null; version: number
  status: "DRAFT" | "READY"; target_country: string; customer_type: string
  content_objective: string; cta: string; landing_page_url: string; language: string
  prohibited_claims: string[]; selling_points: string[]; advantages: string[]; keywords: string[]
  product_ids: string[]; asset_ids: string[]; platform_ids: string[]
  concept_links: Array<{ role: string; concept_id: string }>
  created_by: number; reviewed_by: number | null; reviewed_at: string | null
  created_at: string; updated_at: string
}
export type BriefInput = Pick<ContentBrief,
  "campaign_id" | "target_country" | "customer_type" | "content_objective" | "cta"
  | "landing_page_url" | "language" | "prohibited_claims" | "selling_points"
  | "advantages" | "keywords" | "product_ids" | "asset_ids" | "platform_ids"
  | "concept_links">
export type Platform = { id: string; code: string; name: string; capabilities: string[] }
export type BriefConcept = {
  id: string; code: string
  concept_type: "PRODUCT_TYPE" | "PARAMETER" | "MATERIAL" | "PROCESS" | "STANDARD"
    | "APPLICATION" | "INDUSTRY" | "CUSTOMER_TYPE" | "PURCHASE_INTENT"
  label_zh: string; label_en: string
  status: "SUGGESTED" | "APPROVED" | "REJECTED" | "DEPRECATED"
}
export type Asset = {
  id: string; asset_type: string; original_filename: string; mime_type: string
  size_bytes: number; language: string; status: string; tags: string[]; created_at: string
}
export type JobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "RETRY_QUEUED" | "CANCELED"
export type Job = {
  job_id: string; type: string; status: JobStatus; progress: number; attempt: number
  max_attempts: number; created_at: string; finished_at: string | null
  error: { code?: string; message?: string } | null; result_reference: Record<string, unknown> | null
}
export type ContentStatus = "DRAFT" | "IN_REVIEW" | "APPROVED" | "REJECTED" | "PUBLISHED" | "ARCHIVED"
export type MasterPayload = { title: string; body: string; cta: string; concept_codes: string[] }
export type PlatformPayload = MasterPayload & { platform_code: string }
export type MasterContent = {
  id: string; brief_id: string; brief_version: number; generation_job_id: string
  ai_run_id: string; lineage_id: string; previous_version_id: string | null; version: number
  payload: MasterPayload; provenance: Record<string, unknown>; status: ContentStatus
  is_current_head: boolean; created_by_id: number | null; created_at: string; updated_at: string
}
export type PlatformContent = {
  id: string; master_content_id: string; master_version: number; platform_id: string
  lineage_id: string; previous_version_id: string | null; version: number
  payload: PlatformPayload; provenance: Record<string, unknown>; status: ContentStatus
  is_current_head: boolean; created_by_id: number | null; created_at: string; updated_at: string
}
export type AIRun = {
  id: string; job_id: string; job_attempt: number; status: string
  prompt: { purpose: string; code: string; version: number; provider: string; model: string }
  provider: string; model: string; confidence: string | null
  human_correction: Record<string, unknown> | null
  reviewer: { id: number; username: string } | null
  created_at: string; started_at: string; finished_at: string | null; reviewed_at: string | null
  input_snapshot: Record<string, unknown>; output_json: Record<string, unknown> | null
  error: Record<string, unknown> | null; provider_metadata: Record<string, unknown>
}
export type ContentFilters = {
  status?: ContentStatus; campaign?: string; brief?: string; platform?: string
  page_size?: number
}

const root = (organizationId: string) => ["content-workflow", organizationId] as const
export const contentQueryKeys = {
  all: root,
  campaigns: (organizationId: string) => [...root(organizationId), "campaigns"] as const,
  briefs: (organizationId: string) => [...root(organizationId), "briefs"] as const,
  jobs: (organizationId: string) => [...root(organizationId), "jobs"] as const,
  masterContents: (organizationId: string, filters: ContentFilters) =>
    [...root(organizationId), "master-contents", filters] as const,
  platformContents: (organizationId: string, filters: ContentFilters) =>
    [...root(organizationId), "platform-contents", filters] as const,
  aiRuns: (organizationId: string) => [...root(organizationId), "ai-runs"] as const,
  aiRun: (organizationId: string, id: string) => [...root(organizationId), "ai-runs", id] as const,
  platforms: (organizationId: string) => [...root(organizationId), "platforms"] as const,
  assets: (organizationId: string) => [...root(organizationId), "assets"] as const,
}

function required<T>(value: T | undefined, message = "服务响应不完整，请重试。"): T {
  if (value === undefined) throw new ApiError(0, message)
  return value
}

function queryUrl(path: string, filters: Record<string, unknown> = {}): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value))
  }
  const query = params.toString()
  return `${path}${query ? `?${query}` : ""}`
}

export function safeCursorUrl(value: string | null, exactPath: string): string | null {
  if (!value) return null
  let target: URL
  try { target = new URL(value, window.location.origin) } catch { return null }
  if (target.origin !== window.location.origin || target.pathname !== exactPath) return null
  return `${target.pathname}${target.search}`
}

export async function getCursorPage<T>(url: string, exactPath: string): Promise<CursorPage<T>> {
  const safe = safeCursorUrl(url, exactPath)
  if (!safe) throw new ApiError(0, "分页地址无效，请从列表重新开始。")
  return required(await apiRequest<CursorPage<T>>(safe))
}

export const listCampaigns = async (): Promise<CursorPage<Campaign>> =>
  required(await apiRequest<CursorPage<Campaign>>("/api/v1/campaigns"))
export const listApprovedBriefConcepts = async (): Promise<CursorPage<BriefConcept>> =>
  required(await apiRequest<CursorPage<BriefConcept>>(
    "/api/v1/knowledge/concepts?status=APPROVED&page_size=50",
  ))
export const listBriefConcepts = async (): Promise<CursorPage<BriefConcept>> =>
  required(await apiRequest<CursorPage<BriefConcept>>("/api/v1/knowledge/concepts?page_size=50"))
export const createCampaign = async (input: { name: string; description: string }): Promise<Campaign> =>
  required(await apiRequest<Campaign>("/api/v1/campaigns", { method: "POST", body: { ...input, status: "DRAFT", product_ids: [] } }))
export const listBriefs = async (filters: { status?: string; campaign?: string } = {}): Promise<CursorPage<ContentBrief>> =>
  required(await apiRequest<CursorPage<ContentBrief>>(queryUrl("/api/v1/content-briefs", filters)))
export const createBrief = async (input: BriefInput): Promise<ContentBrief> =>
  required(await apiRequest<ContentBrief>("/api/v1/content-briefs", { method: "POST", body: input }))
export const getBrief = async (id: string): Promise<ContentBrief> =>
  required(await apiRequest<ContentBrief>(`/api/v1/content-briefs/${id}`))
export const patchBrief = async (id: string, input: Partial<Omit<BriefInput, "campaign_id">>): Promise<ContentBrief> =>
  required(await apiRequest<ContentBrief>(`/api/v1/content-briefs/${id}`, { method: "PATCH", body: input }))
export const markBriefReady = async (id: string): Promise<ContentBrief> =>
  required(await apiRequest<ContentBrief>(`/api/v1/content-briefs/${id}/ready`, { method: "POST", body: {} }))
export const reviseBrief = async (id: string): Promise<ContentBrief> =>
  required(await apiRequest<ContentBrief>(`/api/v1/content-briefs/${id}/revisions`, { method: "POST", body: {} }))

export const listPlatforms = async (): Promise<Platform[]> =>
  (required(await apiRequest<{ results: Platform[] }>("/api/v1/platforms"))).results
export const listPlatformPage = async (): Promise<CursorPage<Platform>> => {
  const page = required(await apiRequest<CursorPage<Platform>>("/api/v1/platforms"))
  return { next: page.next ?? null, previous: page.previous ?? null, results: page.results }
}
export const listAssets = async (): Promise<CursorPage<Asset>> =>
  required(await apiRequest<CursorPage<Asset>>("/api/v1/assets"))

export const listJobs = async (
  filters: { status?: JobStatus; job_id?: string } = {},
  options: Pick<ApiRequestOptions, "signal"> = {},
): Promise<CursorPage<Job>> =>
  required(await apiRequest<CursorPage<Job>>(queryUrl("/api/v1/jobs", filters), options))
export const getJob = async (id: string): Promise<Job> => required(await apiRequest<Job>(`/api/v1/jobs/${id}`))
export const cancelJob = async (id: string): Promise<Job> =>
  required(await apiRequest<Job>(`/api/v1/jobs/${id}/cancel`, { method: "POST", body: {} }))
export const retryJob = async (id: string): Promise<Job> =>
  required(await apiRequest<Job>(`/api/v1/jobs/${id}/retry`, { method: "POST", body: {} }))
export const generateMaster = async (briefId: string): Promise<{ job_id: string; status: JobStatus }> =>
  required(await apiRequest<{ job_id: string; status: JobStatus }>(
    `/api/v1/content-briefs/${briefId}/generate-master-content`, { method: "POST", body: {} },
  ))

export async function listMasterContents(filters: ContentFilters = {}): Promise<CursorPage<MasterContent>> {
  return required(await apiRequest<CursorPage<MasterContent>>(queryUrl("/api/v1/master-contents", filters)))
}
export async function listPlatformContents(filters: ContentFilters = {}): Promise<CursorPage<PlatformContent>> {
  return required(await apiRequest<CursorPage<PlatformContent>>(queryUrl("/api/v1/platform-contents", filters)))
}
export const getMasterContent = async (id: string): Promise<MasterContent> =>
  required(await apiRequest<MasterContent>(`/api/v1/master-contents/${id}`))
export const getPlatformContent = async (id: string): Promise<PlatformContent> =>
  required(await apiRequest<PlatformContent>(`/api/v1/platform-contents/${id}`))
export const reviseMasterContent = async (id: string, payload: MasterPayload): Promise<MasterContent> =>
  required(await apiRequest<MasterContent>(`/api/v1/master-contents/${id}/revisions`, { method: "POST", body: { payload } }))
export const revisePlatformContent = async (id: string, payload: PlatformPayload): Promise<PlatformContent> =>
  required(await apiRequest<PlatformContent>(`/api/v1/platform-contents/${id}/revisions`, { method: "POST", body: { payload } }))

export async function contentAction<T extends MasterContent | PlatformContent>(
  kind: "master" | "platform", id: string, action: "submit-review" | "approve" | "reject" | "archive",
  comment = "",
): Promise<T> {
  const path = kind === "master" ? "master-contents" : "platform-contents"
  return required(await apiRequest<T>(`/api/v1/${path}/${id}/${action}`, {
    method: "POST", body: { comment },
  }))
}
export const generatePlatformContent = async (masterId: string, platformId: string): Promise<PlatformContent> =>
  required(await apiRequest<PlatformContent>(`/api/v1/master-contents/${masterId}/generate-platform-content`, {
    method: "POST", body: { platform_id: platformId },
  }))

export const getAIRun = async (id: string): Promise<AIRun> =>
  required(await apiRequest<AIRun>(`/api/v1/ai-runs/${id}`))
