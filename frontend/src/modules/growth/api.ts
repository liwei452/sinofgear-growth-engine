import { queryOptions } from "@tanstack/vue-query"

import { apiRequest } from "../../api/client"

export type TargetAccount = {
  id: string
  name: string
  country: string
  industry: string
  employee_range: string
  website: string
  is_demo: boolean
  data_label: string
}

export type EvidenceEnvelope = {
  field_value: string
  source_url: string
  source_excerpt: string
  confidence: number
  observed_at: string
  source_cost_micros: number
  license_contract: string
  usage_rights: string
  review_status: string
  queue: string
  source_type?: "DIRECT_CUSTOMS" | "CARRIER_BOL" | "MIRROR_TRADE" | "AGGREGATE_TRADE" | "TENDER" | "COMPANY_WEB" | string
  matched_keywords?: string[]
  company_match_confidence?: number
  ai_exclusion_reasons?: string[]
}

export type IntentSignal = {
  id: string
  account_id: string
  signal_type: string
  source_label: string
  source_url: string
  evidence_text: string
  confidence: number
  observed_at: string
  data_label: string
  collection_method: "DEMO_FIXTURE" | "MANUAL_URL" | "LICENSED_API" | "INBOUND" | string
  collection_method_label: string
  content_hash: string
  score_breakdown: OpportunityScoreBreakdown
  scoring_rule_version: string
  uncertainty_notes: string[]
  evidence_envelope?: EvidenceEnvelope
  priority_label: "优先跟进" | "继续观察"
}

export type OpportunityScoreBreakdown = {
  icp_fit: number
  intent_strength: number
  recency: number
  role_relevance: number
  evidence_coverage: number
  risk_penalty: number
}

export type ManualOpportunityImportInput = {
  company_name: string
  country: string
  industry: string
  source_label: string
  source_url: string
  evidence_text: string
}

export type ManualOpportunityImportResult = {
  account: TargetAccount
  signal: IntentSignal
  created: boolean
}

export type FollowUp = {
  id: string
  account_id: string
  status: string
  created_at: string
  updated_at: string
}

export type OutreachDraft = {
  id: string
  account_id: string
  english_draft: string
  chinese_explanation: string
  status: string
  delivery: "NEVER_SENT"
  created_at: string
  updated_at: string
}

export type ChannelPackage = {
  id: string
  account_id: string | null
  channel: string
  payload: Record<string, unknown>
  status: string
  is_demo: boolean
  data_label: string
  delivery: "MANUAL_ONLY"
  created_at: string
  updated_at: string
}

export type MetricReceipt = {
  id: string
  channel: string
  payload: Record<string, unknown>
  is_demo: boolean
  created_at: string
  updated_at: string
}

export type FieldProvenance = {
  id: string
  field_name: string
  field_value: string
  source_label: string
  verification_status: string
  source_cost_micros: number
  created_at: string
  updated_at: string
}

export type PlatformConnection = {
  channel: "LINKEDIN" | "FACEBOOK" | "INSTAGRAM" | "TIKTOK"
  status: "NOT_CONNECTED" | "CONNECTED" | "REAUTHORIZATION_REQUIRED" | "CONFIGURATION_REQUIRED"
  connection_label: string
  recovery_action: string
  mode: "" | "DEMO_FAKE" | "OFFICIAL"
}

export type DiscoveryRunResult = {
  status: "RUNNING" | "SUCCEEDED" | "FAILED"
  finished_at: string | null
  found_count: number
  new_company_count: number
  new_signal_count: number
  duplicate_count: number
  skipped_count: number
  message: string
}

export type DiscoverySourceSummary = {
  code: "TED" | "GOOGLE_PLACES" | string
  label: string
  status: "ACTIVE" | "KEY_REQUIRED" | string
}

export type DiscoverySummary = {
  enabled: boolean
  source_label: string
  schedule_label: string
  product_scope_label: string
  next_run_at: string | null
  last_run: DiscoveryRunResult | null
  available_sources: DiscoverySourceSummary[]
}

export type MarketPilotSummary = {
  markets: Array<{
    country_code: string
    country_label: string
    status: "OBSERVATION_POOL" | "DATA_VALIDATION" | "SMALL_PILOT" | "ACTIVE_MARKET" | "PAUSED"
    route: string
    route_label: string
    recommended_wave: string
    source_types: string[]
    last_updated_at: string
    scores: Record<string, number | null>
    sample_quality: {
      raw_sample_count: number
      named_buyer_rate: number | null
      active_entity_match_rate: number | null
      duplicate_rate: number | null
      evidence_company_count: number
      evidence_company_threshold: number
    }
    recommendation_reasons: string[]
    hold_reasons: string[]
    metrics: {
      effective_customer_rate: number | null
      positive_reply_rate: number | null
      source_cost_micros: number
      raw_sample_count: number
    }
  }>
  score_weights: {
    data_availability: number
    demand_strength: number
    purchase_intent: number
    company_reachability: number
    commercial_execution: number
  }
  quality_gate: {
    minimum_raw_samples: number
    minimum_named_buyer_rate: number
    minimum_active_entity_match_rate: number
    maximum_median_record_age_days: number
    maximum_duplicate_rate: number
    license_required: boolean
  }
  search_policy: { hs_codes: string[]; include_terms: string[]; exclude_terms: string[] }
  validation_goals: {
    reviewed_valid_companies: number
    sales_conversations: number
    positive_intent_signals: number
    progressed_opportunities: number
    weeks: number
  }
}

export type GrowthWorkspace = {
  target_accounts: TargetAccount[]
  contacts: Array<Record<string, unknown>>
  intent_signals: IntentSignal[]
  inbound_leads: Array<Record<string, unknown>>
  follow_ups: FollowUp[]
  outreach_drafts: OutreachDraft[]
  channel_packages: ChannelPackage[]
  publish_batches: PublishBatch[]
  metric_receipts: MetricReceipt[]
  field_provenance: FieldProvenance[]
  connectors: PlatformConnection[]
  discovery?: DiscoverySummary
  market_pilots?: MarketPilotSummary
}

export type DraftActionResponse = {
  id: string
  status: string
  "English draft": string
  "Chinese explanation": string
  delivery: "NEVER_SENT"
}

export const growthQueryKeys = {
  workspace: ["growth", "workspace"] as const,
}

export function growthWorkspaceQueryOptions() {
  return queryOptions({
    queryKey: growthQueryKeys.workspace,
    queryFn: async () => {
      const workspace = await apiRequest<GrowthWorkspace>("/api/v1/growth/workspace")
      if (!workspace) throw new Error("增长工作区响应为空。")
      return workspace
    },
    staleTime: 15_000,
  })
}

export async function addOpportunityFollowUp(accountId: string): Promise<FollowUp> {
  const result = await apiRequest<FollowUp>(
    `/api/v1/growth/opportunities/${accountId}/follow-up`, { method: "POST", body: {} },
  )
  if (!result) throw new Error("跟进响应为空。")
  return result
}

export async function createOpportunityDraft(accountId: string): Promise<DraftActionResponse> {
  const result = await apiRequest<DraftActionResponse>(
    `/api/v1/growth/opportunities/${accountId}/draft`, { method: "POST", body: {} },
  )
  if (!result) throw new Error("草稿响应为空。")
  return result
}

export async function importManualOpportunity(
  input: ManualOpportunityImportInput,
): Promise<ManualOpportunityImportResult> {
  const result = await apiRequest<ManualOpportunityImportResult>(
    "/api/v1/growth/opportunity-imports/manual-url",
    { method: "POST", body: input },
  )
  if (!result) throw new Error("公开线索导入响应为空。")
  return result
}

export async function runAutomaticDiscovery(): Promise<DiscoveryRunResult> {
  const result = await apiRequest<DiscoveryRunResult>(
    "/api/v1/growth/discovery/run",
    { method: "POST", body: {} },
  )
  if (!result) throw new Error("自动查找响应为空。")
  return result
}

export async function updateAutomaticDiscovery(
  enabled: boolean,
): Promise<DiscoverySummary> {
  const result = await apiRequest<DiscoverySummary>(
    "/api/v1/growth/discovery/profile",
    { method: "PATCH", body: { enabled } },
  )
  if (!result) throw new Error("自动查找设置响应为空。")
  return result
}

export async function approveChannelPackage(packageId: string): Promise<{
  id: string
  status: "APPROVED"
  delivery: "MANUAL_ONLY"
}> {
  const result = await apiRequest<{
    id: string
    status: "APPROVED"
    delivery: "MANUAL_ONLY"
  }>(`/api/v1/growth/channel-packages/${packageId}/approve`, { method: "POST", body: {} })
  if (!result) throw new Error("内容包审批响应为空。")
  return result
}

export type ManualPackageExport = {
  package_id: string
  channel: string
  mode: "MANUAL_PACKAGE"
  data_label: string
  delivery: "MANUAL_ONLY"
  filename: string
  payload: Record<string, unknown>
}

export type PublishBatchItem = {
  id: string
  channel: string
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED"
  attempt_number: number
  external_post_url: string
  mode: "DEMO_FAKE" | "OFFICIAL"
  error_code: string
  retryable: boolean
  recovery_action: string
  created_at: string
  updated_at: string
}

export type PlatformAuthorizationStart = {
  status: "AUTHORIZATION_REQUIRED"
  authorization_url: string
  expires_at: string
}

export type PlatformConnectionCandidate = {
  candidate_id: string
  display_name: string
  channel: PlatformConnection["channel"]
  capability_label: string
  publication_mode: "PUBLIC" | "PRIVATE_ONLY"
}

export type PlatformConnectionSession = {
  id: string
  platform: PlatformConnection["channel"]
  platform_name: string
  expires_at: string
  candidates: PlatformConnectionCandidate[]
}

export type PlatformConnectionConfirmation = {
  platform: PlatformConnection["channel"]
  status: "CONNECTED"
  connection_label: string
  recovery_action: string
  mode: "OFFICIAL"
}

export async function getPlatformConnectionSession(
  sessionId: string,
): Promise<PlatformConnectionSession> {
  const result = await apiRequest<PlatformConnectionSession>(
    `/api/v1/platform-connection-sessions/${sessionId}`,
  )
  if (!result) throw new Error("账号选择响应为空。")
  return result
}

export async function confirmPlatformConnection(input: {
  sessionId: string
  candidateId: string
}): Promise<PlatformConnectionConfirmation> {
  const result = await apiRequest<PlatformConnectionConfirmation>(
    `/api/v1/platform-connection-sessions/${input.sessionId}/confirm`,
    { method: "POST", body: { candidate_id: input.candidateId } },
  )
  if (!result) throw new Error("账号连接响应为空。")
  return result
}

export async function authorizePlatformConnection(
  channel: PlatformConnection["channel"],
): Promise<PlatformAuthorizationStart> {
  const result = await apiRequest<PlatformAuthorizationStart>(
    `/api/v1/platform-connections/${channel}/authorize`,
    { method: "POST", body: { return_path: "/promotion" } },
  )
  if (!result) throw new Error("账号连接响应为空。")
  return result
}

export type PublishBatch = {
  id: string
  status: "QUEUED" | "RUNNING" | "PARTIAL_SUCCESS" | "SUCCEEDED" | "FAILED" | "CONFIGURATION_REQUIRED"
  is_demo: boolean
  data_label: string
  created_at: string
  updated_at: string
  items: PublishBatchItem[]
}

export async function createPublishBatch(
  packageIds: string[], idempotencyKey: string,
): Promise<PublishBatch> {
  const result = await apiRequest<PublishBatch>("/api/v1/growth/publish-batches", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: { package_ids: packageIds },
  })
  if (!result) throw new Error("一键发布响应为空。")
  return result
}

export async function getPublishBatch(batchId: string): Promise<PublishBatch> {
  const result = await apiRequest<PublishBatch>(`/api/v1/growth/publish-batches/${batchId}`)
  if (!result) throw new Error("发布结果响应为空。")
  return result
}

export async function retryFailedPublishBatch(batchId: string): Promise<PublishBatch> {
  const result = await apiRequest<PublishBatch>(
    `/api/v1/growth/publish-batches/${batchId}/retry-failed`,
    { method: "POST", body: {} },
  )
  if (!result) throw new Error("发布重试响应为空。")
  return result
}

export async function exportChannelPackage(packageId: string): Promise<ManualPackageExport> {
  const result = await apiRequest<ManualPackageExport>(
    `/api/v1/growth/channel-packages/${packageId}/manual-export`, { method: "POST", body: {} },
  )
  if (!result) throw new Error("手工发布包响应为空。")
  return result
}

export async function createMetricReceipt(input: {
  channel: string
  payload: Record<string, number>
  is_demo: boolean
}): Promise<MetricReceipt> {
  const result = await apiRequest<MetricReceipt>("/api/v1/growth/metric-receipts", {
    method: "POST",
    body: input,
  })
  if (!result) throw new Error("指标回填响应为空。")
  return result
}

export async function verifyCompanyFact(factId: string): Promise<{
  id: string
  verification_status: "VERIFIED"
}> {
  const result = await apiRequest<{ id: string; verification_status: "VERIFIED" }>(
    `/api/v1/growth/company-facts/${factId}/verify`, { method: "POST", body: {} },
  )
  if (!result) throw new Error("公司事实确认响应为空。")
  return result
}
