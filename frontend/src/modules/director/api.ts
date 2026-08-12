import type { components } from "../../api/generated/schema"
import { ApiError, apiRequest, type ApiRequestOptions } from "../../api/client"

export type DirectorCockpit = components["schemas"]["DirectorCockpit"]
export type DirectorDecision = components["schemas"]["DirectorDecisionSummary"]
export type DirectorAction = components["schemas"]["DirectorDecisionRequestActionEnum"]
export type DirectorDecisionInput = components["schemas"]["DirectorDecisionRequest"]
export type DirectorDecisionResult = components["schemas"]["DirectorDecisionResult"]

const allowedActions = new Set<DirectorAction>(["APPROVE", "REQUEST_ADJUSTMENT", "REJECT"])
const allowedTypes = new Set(["PROMOTION_PLAN", "CONTENT_APPROVAL", "LEAD_HANDOFF", "FACT_CONFLICT", "COST_APPROVAL"])
const allowedResultStatuses = new Set(["PENDING", "APPROVED", "ADJUSTMENT_REQUESTED", "REJECTED", "SUPERSEDED", "EXPIRED"])

export const directorKeys = {
  all: (organizationId: string) => ["director", organizationId] as const,
  cockpit: (organizationId: string) => [...directorKeys.all(organizationId), "cockpit"] as const,
}

function invalid(): never {
  throw new ApiError(0, "服务响应格式不正确，请刷新后重试。")
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function assertCockpit(value: unknown): asserts value is DirectorCockpit {
  if (!isRecord(value) || !Array.isArray(value.decisions) || !Array.isArray(value.active_work)
    || !Array.isArray(value.recent_outcomes) || typeof value.generated_at !== "string") invalid()
  if (value.decisions.length > 3 || value.active_work.length > 5 || value.recent_outcomes.length > 4
    || value.decisions.some((item) => !isRecord(item)
    || typeof item.id !== "string" || !allowedTypes.has(String(item.type))
    || typeof item.title !== "string" || typeof item.explanation !== "string"
    || typeof item.priority !== "number" || !Number.isInteger(item.version) || item.version < 1
    || !Array.isArray(item.actions) || item.actions.some((action) => !allowedActions.has(action as DirectorAction)))) invalid()
  if (value.active_work.some((item) => !isRecord(item) || typeof item.job_id !== "string"
    || typeof item.label !== "string" || typeof item.status !== "string"
    || typeof item.progress !== "number" || item.progress < 0 || item.progress > 100
    || typeof item.progress_is_determinate !== "boolean")) invalid()
  if (value.recent_outcomes.some((item) => !isRecord(item) || typeof item.kind !== "string"
    || typeof item.label !== "string" || typeof item.value !== "string" || typeof item.detail !== "string")) invalid()
}

export async function getCockpit(
  options: Pick<ApiRequestOptions, "signal"> = {},
): Promise<DirectorCockpit> {
  const result = await apiRequest<DirectorCockpit>("/api/v1/director/cockpit", options)
  if (result === undefined) throw new ApiError(0, "服务响应不完整，请重试。")
  assertCockpit(result)
  return result
}

export async function decideProposal(
  proposalId: string,
  input: DirectorDecisionInput,
): Promise<DirectorDecisionResult> {
  const result = await apiRequest<DirectorDecisionResult>(
    `/api/v1/director/proposals/${encodeURIComponent(proposalId)}/decisions`,
    { method: "POST", body: input },
  )
  if (result === undefined || !isRecord(result) || typeof result.id !== "string"
    || !allowedResultStatuses.has(String(result.status)) || !Number.isInteger(result.version) || Number(result.version) < 1) {
    throw new ApiError(0, "服务响应不完整，请重试。")
  }
  return result as DirectorDecisionResult
}
