import { ApiError, apiRequest } from "../../api/client"

export type KnowledgeStatus = "SUGGESTED" | "APPROVED" | "REJECTED" | "DEPRECATED"
export type KnowledgeScope = "SYSTEM" | "ORGANIZATION"
export type ConceptType =
  | "PRODUCT_TYPE" | "PARAMETER" | "MATERIAL" | "PROCESS" | "STANDARD"
  | "APPLICATION" | "INDUSTRY" | "CUSTOMER_TYPE" | "PURCHASE_INTENT"
  | "CAPABILITY" | "REQUIREMENT"

export type KnowledgeConcept = {
  id: string
  scope: KnowledgeScope
  organization: string | null
  concept_type: ConceptType
  code: string
  label_zh: string
  label_en: string
  description: string
  status: KnowledgeStatus
  version: number
  suggested_by_ai_run_id: string | null
  evidence: string[]
  created_by: number | null
  reviewed_by: number | null
  reviewed_at: string | null
  created_at: string
  updated_at: string
}

export type KnowledgeAlias = {
  id: string
  organization: string | null
  concept: string
  language: string
  alias: string
  normalized_alias: string
  alias_type: "SYNONYM" | "ABBREVIATION" | "MARKET_TERM"
  status: KnowledgeStatus
  version: number
}

export type KnowledgeRelation = {
  id: string
  scope?: KnowledgeScope
  organization: string | null
  subject_concept: string
  predicate: string
  object_concept: string
  status: KnowledgeStatus
  confidence: string
  version: number
  evidence: string[]
}

export type KnowledgeEvidence = {
  id: string
  organization: string | null
  evidence_type: string
  source_object_type: string
  source_object_id: string | null
  source_url: string | null
  excerpt: string
  captured_at: string | null
  status: KnowledgeStatus
  version: number
}

export type ConceptInput = {
  scope: "ORGANIZATION"
  concept_type: ConceptType
  code: string
  label_zh: string
  label_en: string
  description: string
  evidence?: string[]
}

export type ConceptMatch = {
  concept_id: string
  code: string
  concept_type: ConceptType
  scope: KnowledgeScope
  label_zh: string
  label_en: string
}

export type AliasResolution = {
  ambiguous: boolean
  selected: ConceptMatch | null
  candidates: ConceptMatch[]
}

type ListResponse<T> = { results: T[] }
export type ReviewAction = "submit-review" | "approve" | "reject" | "deprecate"

export const knowledgeQueryKeys = {
  all: (organizationId: string) => ["knowledge", organizationId] as const,
  concepts: (organizationId: string) => ["knowledge", organizationId, "concepts"] as const,
  productConcepts: (organizationId: string) =>
    ["knowledge", organizationId, "product-concepts"] as const,
  aliases: (organizationId: string) => ["knowledge", organizationId, "aliases"] as const,
  relations: (organizationId: string) => ["knowledge", organizationId, "relations"] as const,
  evidence: (organizationId: string) => ["knowledge", organizationId, "evidence"] as const,
}

async function list<T>(path: string): Promise<T[]> {
  const response = await apiRequest<ListResponse<T>>(path)
  if (!response) throw new ApiError(0, "知识库响应为空，请重试。")
  return response.results
}

export const listConcepts = () => list<KnowledgeConcept>("/api/v1/knowledge/concepts")
export const listAliases = () => list<KnowledgeAlias>("/api/v1/knowledge/aliases")
export const listRelations = () => list<KnowledgeRelation>("/api/v1/knowledge/relations")
export const listEvidence = () => list<KnowledgeEvidence>("/api/v1/knowledge/evidence")

export async function createConcept(input: ConceptInput): Promise<KnowledgeConcept> {
  const concept = await apiRequest<KnowledgeConcept>("/api/v1/knowledge/concepts", {
    method: "POST",
    body: input,
  })
  if (!concept) throw new ApiError(0, "新增知识建议响应为空，请刷新列表确认。")
  return concept
}

export async function reviewConcept(
  id: string,
  action: ReviewAction,
  comment = "",
): Promise<KnowledgeConcept> {
  const concept = await apiRequest<KnowledgeConcept>(
    `/api/v1/knowledge/concepts/${id}/${action}`,
    { method: "POST", body: { comment } },
  )
  if (!concept) throw new ApiError(0, "审核响应为空，请刷新列表确认。")
  return concept
}

export async function resolveAlias(input: { text: string; language: string }): Promise<AliasResolution> {
  const resolution = await apiRequest<AliasResolution>("/api/v1/knowledge/resolve", {
    method: "POST",
    body: input,
  })
  if (!resolution) throw new ApiError(0, "名称检查响应为空，请重试。")
  return resolution
}
