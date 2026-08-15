import { queryOptions } from "@tanstack/vue-query"

import { apiBlobRequest, apiRequest } from "../../api/client"

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
  screenshot_reference?: {
    file_name: string
    captured_at: string
    source_url: string
    metadata_hash: string
  }
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
  screenshot_file_name?: string
  screenshot_captured_at?: string | null
}

export type ManualOpportunityImportResult = {
  account: TargetAccount
  signal: IntentSignal
  created: boolean
  account_id: string | null
}

export type CandidateFollowUpResult = {
  account_id: string
  follow_up_id: string
  status: "OPEN"
  created: boolean
  message: string
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

export type Reactivation = {
  id: string
  account_id: string
  account_name: string
  industry: string
  relationship_source: "EXISTING_CUSTOMER" | "PAST_INQUIRY" | "TRADE_SHOW" | "OWNED_CRM"
  last_interacted_at: string
  interaction_summary: string
  tier: "STRATEGIC" | "NURTURE" | "OBSERVATION"
  status: "SELECTED" | "DRAFTED" | "APPROVED"
  is_demo: boolean
  why_reactivate: string
  recommended_action: string
  evidence: string
  risk: string
  draft: null | {
    id: string
    english_draft: string
    chinese_explanation: string
    status: "DRAFT" | "APPROVED"
  }
  events: Array<{
    event_type: "REACTIVATION_SELECTED" | "REACTIVATION_DRAFTED" | "REACTIVATION_APPROVED"
    created_at: string
    delivery: "NEVER_SENT"
  }>
  delivery: "NEVER_SENT"
}

export type ReactivationDraftResult = {
  id: string
  draft_id: string
  status: "DRAFTED"
  draft_status: "DRAFT"
  english_draft: string
  chinese_explanation: string
  delivery: "NEVER_SENT"
}

export type OpportunityReview = {
  id: string
  account_id: string
  signal_id: string
  decision: "PRIORITIZE" | "OBSERVE" | "PROCESSED"
  status_label: "优先跟进" | "继续观察" | "已处理"
  reason: string
  original_confidence: number
  original_score_breakdown: OpportunityScoreBreakdown
  created_at: string
}

export type CRMHandoff = {
  id: string
  account_id: string
  review_id: string
  draft_id: string
  connector: "MOCK_CRM"
  status: "RECORDED"
  payload_snapshot: Record<string, unknown>
  delivery: "NEVER_SENT"
  created_at: string
}

export type ChannelPackage = {
  id: string
  account_id: string | null
  source_platform_content_id?: string | null
  channel: string
  payload: Record<string, unknown>
  status: string
  is_demo: boolean
  data_label: string
  delivery: "MANUAL_ONLY"
  created_at: string
  updated_at: string
}

export async function prepareChannelPackage(platformContentId: string): Promise<ChannelPackage> {
  const result = await apiRequest<ChannelPackage>(
    `/api/v1/growth/channel-packages/from-platform-content/${platformContentId}`,
    { method: "POST", body: {} },
  )
  if (!result) throw new Error("发布准备响应为空。")
  return result
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
  is_demo?: boolean
  created_at: string
  updated_at: string
}

export type PlatformConnection = {
  channel: "LINKEDIN" | "FACEBOOK" | "INSTAGRAM" | "TIKTOK" | "YOUTUBE"
  status: "NOT_CONNECTED" | "CONNECTED" | "REAUTHORIZATION_REQUIRED" | "CONFIGURATION_REQUIRED" | "WAITING_PLATFORM_REVIEW" | "PRIVATE_ONLY" | "PROVIDER_UNAVAILABLE" | "INSUFFICIENT_CAPABILITY"
  connection_label: string
  recovery_action: string
  mode: "" | "DEMO_FAKE" | "OFFICIAL"
  account_id?: string
  publication_mode?: "UNAVAILABLE" | "PUBLIC" | "PRIVATE_ONLY" | "UPLOAD"
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
  candidate_count?: number
  candidates?: DiscoveryCandidate[]
  enrichment_candidates?: EnrichmentCandidate[]
  available_sources: DiscoverySourceSummary[]
}

export type CandidateEnrichmentPreview = {
  candidate_id: string
  mode: "FAKE_PREVIEW" | "IMPORTED_FACTS_REVIEW" | "OFFICIAL" | "VERIFIED_MANUAL" | "WEBSITE_PUBLIC"
  data_label: string
  facts: Array<{ field: string; value: string; source: string }>
  public_contact_paths: Array<{ label?: string; url?: string }>
  uncertainties: string[]
  message: string
  created: boolean
}

export type EnrichmentCandidate = DiscoveryCandidate & {
  latest_preview: CandidateEnrichmentPreview | null
}

export type DiscoveryCandidate = {
  id: string
  company_name: string
  country: string
  website: string
  industry: string
  status: "PENDING_REVIEW" | "ACCEPTED" | "DISMISSED"
  status_label: string
  source_owner: string
  license_contract: string
  import_format: "CSV" | "JSON"
  is_demo: boolean
  score: number
  grade: "A" | "B" | "C"
  created_at: string
}

export type DiscoveryCandidateReviewResult = {
  id: string
  status: "ACCEPTED" | "DISMISSED"
  status_label: string
  message: string
}

export type CandidateListImportInput = {
  format: "CSV" | "JSON"
  content: string
  source_owner: string
  license_contract: string
  retention_days: number
  redistribution_allowed: boolean
}

export type CandidateListImportResult = {
  created_count: number
  duplicate_count: number
  invalid_count: number
  errors: Array<{ row: number; message: string }>
  queue_label: "待核实候选公司"
}

export type MarketPilotSummary = {
  markets: Array<{
    country_code: string
    country_label: string
    region?: string
    path_family?: "CUSTOMS_STRONG" | "MIXED_ACQUISITION"
    suitable_industries?: string[]
    data_availability_label?: string
    evidence_note?: string
    recommended_action?: string
    is_demo?: boolean
    is_watched?: boolean
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

export type TradeIndicator = {
  formula: string
  value_usd?: string | null
  value_percent?: string | null
  value_days?: number | null
  reason?: string
  inputs: Record<string, unknown>
}

export type TradeIndicatorResponse = {
  status: "NO_DATA" | "READY"
  is_demo: boolean
  scope_warning: string
  indicators: Record<string, TradeIndicator>
  evidence: Array<{
    id: string
    reporter_code: string
    partner_code: string
    hs_code: string
    period: string
    trade_value_usd: string
    source_url: string
    source_dataset: string
    dataset_version: string
    fetched_at: string
    is_demo: boolean
  }>
}

export type TradeSyncResponse = {
  mode: "FIXTURE" | "OFFICIAL_PUBLIC"
  is_demo: boolean
  run_ids: string[]
  snapshot_ids: string[]
  created_snapshot_count: number
  reused_snapshot_count: number
  scope_warning: string
}

export type GrowthWorkspace = {
  target_accounts: TargetAccount[]
  contacts: Array<Record<string, unknown>>
  intent_signals: IntentSignal[]
  inbound_leads: Array<Record<string, unknown>>
  follow_ups: FollowUp[]
  outreach_drafts: OutreachDraft[]
  reactivations?: Reactivation[]
  opportunity_reviews?: OpportunityReview[]
  crm_handoffs?: CRMHandoff[]
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

export async function selectReactivation(input: {
  account_id: string
  relationship_source: Reactivation["relationship_source"]
  last_interacted_at: string
  interaction_summary: string
  relationship_confirmed: boolean
}): Promise<Reactivation> {
  const result = await apiRequest<Reactivation>(
    "/api/v1/growth/reactivations", { method: "POST", body: input },
  )
  if (!result) throw new Error("重新激活响应为空。")
  return result
}

export async function createReactivationDraft(id: string): Promise<ReactivationDraftResult> {
  const result = await apiRequest<ReactivationDraftResult>(
    `/api/v1/growth/reactivations/${id}/draft`, { method: "POST", body: {} },
  )
  if (!result) throw new Error("重新激活草稿响应为空。")
  return result
}

export async function approveReactivationDraft(id: string): Promise<{
  id: string; status: "APPROVED"; draft_status: "APPROVED"; delivery: "NEVER_SENT"; message: string
}> {
  const result = await apiRequest<{
    id: string; status: "APPROVED"; draft_status: "APPROVED"; delivery: "NEVER_SENT"; message: string
  }>(`/api/v1/growth/reactivations/${id}/approve`, { method: "POST", body: {} })
  if (!result) throw new Error("重新激活批准响应为空。")
  return result
}

export async function reviewOpportunity(input: {
  accountId: string
  decision: OpportunityReview["decision"]
}): Promise<OpportunityReview> {
  const result = await apiRequest<OpportunityReview>(
    `/api/v1/growth/opportunities/${input.accountId}/review`,
    { method: "POST", body: { decision: input.decision } },
  )
  if (!result) throw new Error("人工判断响应为空。")
  return result
}

export async function handoffOpportunityToMockCRM(input: {
  accountId: string
  draftId: string
}): Promise<CRMHandoff> {
  const result = await apiRequest<CRMHandoff>(
    `/api/v1/growth/opportunities/${input.accountId}/crm-handoff`,
    { method: "POST", body: { draft_id: input.draftId } },
  )
  if (!result) throw new Error("CRM 交接响应为空。")
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

export async function importCandidateList(
  input: CandidateListImportInput,
): Promise<CandidateListImportResult> {
  const result = await apiRequest<CandidateListImportResult>(
    "/api/v1/growth/discovery/candidate-imports",
    { method: "POST", body: input },
  )
  if (!result) throw new Error("候选名单导入响应为空。")
  return result
}

export async function reviewDiscoveryCandidate(
  candidateId: string,
  decision: "ACCEPT" | "DISMISS",
): Promise<DiscoveryCandidateReviewResult> {
  const result = await apiRequest<DiscoveryCandidateReviewResult>(
    `/api/v1/growth/discovery/candidates/${candidateId}/review`,
    {
      method: "POST",
      body: {
        decision,
        note: decision === "ACCEPT"
          ? "人工确认公司资料可继续补全"
          : "人工判断暂不符合目标客户",
      },
    },
  )
  if (!result) throw new Error("候选公司审核响应为空。")
  return result
}

export async function prepareCandidateEnrichment(
  candidateId: string,
): Promise<CandidateEnrichmentPreview> {
  const result = await apiRequest<CandidateEnrichmentPreview>(
    `/api/v1/growth/enrichment/candidates/${candidateId}/prepare`,
    { method: "POST", body: {} },
  )
  if (!result) throw new Error("公司资料补全响应为空。")
  return result
}


export async function prepareWebsiteEnrichment(
  candidateId: string,
): Promise<CandidateEnrichmentPreview> {
  const result = await apiRequest<CandidateEnrichmentPreview>(
    `/api/v1/growth/enrichment/candidates/${candidateId}/website`,
    { method: "POST", body: {} },
  )
  if (!result) throw new Error("官网补全响应为空。")
  return result
}


export async function addCandidateToFollowUp(
  candidateId: string,
): Promise<CandidateFollowUpResult> {
  const result = await apiRequest<CandidateFollowUpResult>(
    `/api/v1/growth/enrichment/candidates/${candidateId}/follow-up`,
    { method: "POST", body: {} },
  )
  if (!result) throw new Error("加入跟进响应为空。")
  return result
}

export async function watchMarket(countryCode: string): Promise<{
  country_code: string
  is_watched: true
  message: string
}> {
  const result = await apiRequest<{ country_code: string; is_watched: true; message: string }>(
    `/api/v1/growth/markets/${countryCode}/watch`,
    { method: "POST", body: {} },
  )
  if (!result) throw new Error("观察市场响应为空。")
  return result
}

export async function createWatchMarket(input: {
  countryCode: string
  countryLabel: string
  pathFamily: "CUSTOMS_STRONG" | "MIXED_ACQUISITION"
}): Promise<{
  created: boolean
  market: {
    country_code: string
    country_label: string
    path_family: "CUSTOMS_STRONG" | "MIXED_ACQUISITION"
  }
}> {
  const result = await apiRequest<{
    created: boolean
    market: {
      country_code: string
      country_label: string
      path_family: "CUSTOMS_STRONG" | "MIXED_ACQUISITION"
    }
  }>("/api/v1/growth/markets/watch", {
    method: "POST",
    body: {
      country_code: input.countryCode.trim().toUpperCase(),
      country_label: input.countryLabel.trim(),
      path_family: input.pathFamily,
    },
  })
  if (!result) throw new Error("观察市场响应为空。")
  return result
}

export async function loadTradeIndicators(input: {
  countryCode: string
  hsCodes: string[]
  periods: string[]
}): Promise<TradeIndicatorResponse> {
  const query = new URLSearchParams({ country_code: input.countryCode })
  input.hsCodes.forEach(value => query.append("hs_code", value))
  input.periods.forEach(value => query.append("period", value))
  const result = await apiRequest<TradeIndicatorResponse>(
    `/api/v1/growth/trade-indicators?${query.toString()}`,
  )
  if (!result) throw new Error("公开贸易指标响应为空。")
  return result
}

export async function syncPublicTradeData(input: {
  countryCode: string
  hsCodes: string[]
  periods: string[]
}): Promise<TradeSyncResponse> {
  const result = await apiRequest<TradeSyncResponse>("/api/v1/growth/trade-syncs", {
    method: "POST",
    body: {
      country_code: input.countryCode,
      hs_codes: input.hsCodes,
      periods: input.periods,
    },
  })
  if (!result) throw new Error("公开贸易同步响应为空。")
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

export async function approveAllChannelPackages(packageIds: string[]): Promise<{
  status: "APPROVED"
  delivery: "MANUAL_ONLY"
  packages: Array<{ id: string, channel: string, status: "APPROVED" }>
}> {
  const result = await apiRequest<{
    status: "APPROVED"
    delivery: "MANUAL_ONLY"
    packages: Array<{ id: string, channel: string, status: "APPROVED" }>
  }>("/api/v1/growth/channel-packages/approve-all", {
    method: "POST", body: { package_ids: packageIds },
  })
  if (!result) throw new Error("四渠道内容审批响应为空。")
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

export async function disconnectPlatformConnection(accountId: string): Promise<void> {
  await apiRequest(`/api/v1/social-accounts/${accountId}/disconnect`, {
    method: "POST",
    body: { confirm: true },
  })
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

export type FourChannelManualExport = {
  blob: Blob
  filename: string
  contentHash: string
}

export async function exportFourChannelPackage(
  packageIds: string[],
): Promise<FourChannelManualExport> {
  const { blob, response } = await apiBlobRequest(
    "/api/v1/growth/channel-packages/manual-export-all",
    { method: "POST", body: { package_ids: packageIds } },
  )
  const disposition = response.headers.get("Content-Disposition") ?? ""
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  const candidate = match?.[1]?.replaceAll("\\", "/").split("/").at(-1) ?? ""
  const filename = /^[a-zA-Z0-9._-]+\.zip$/.test(candidate)
    ? candidate
    : "four-channel-manual-package.zip"
  return {
    blob,
    filename,
    contentHash: response.headers.get("X-Content-SHA256") ?? "",
  }
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
