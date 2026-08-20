import type { ContentStatus } from "../content/api"

export type PublishStatus =
  | "SCHEDULED" | "QUEUED" | "RUNNING" | "SUBMITTED" | "SUBMISSION_UNKNOWN"
  | "SUCCEEDED" | "FAILED" | "CANCELED" | "NEEDS_ATTENTION" | null

export type ContentWorkflowStage =
  | "PREPARE" | "AI_DRAFT" | "REVIEW" | "SCHEDULED" | "SUBMITTED" | "PUBLISHED" | "NEEDS_ATTENTION"

export type ContentWorkflowGroup = "PENDING" | "PLANNED" | "COMPLETED"

export type ContentWorkflowFacts = {
  contentStatus: ContentStatus
  publishStatus: PublishStatus
}

export function contentWorkflowStage({ contentStatus, publishStatus }: ContentWorkflowFacts): ContentWorkflowStage {
  switch (publishStatus) {
    case "SCHEDULED": return "SCHEDULED"
    case "QUEUED":
    case "RUNNING":
    case "SUBMITTED":
    case "SUBMISSION_UNKNOWN": return "SUBMITTED"
    case "SUCCEEDED": return "PUBLISHED"
    case "FAILED":
    case "CANCELED": return "NEEDS_ATTENTION"
    case "NEEDS_ATTENTION": return "NEEDS_ATTENTION"
    case null:
      switch (contentStatus) {
        case "DRAFT": return "AI_DRAFT"
        case "IN_REVIEW": return "REVIEW"
        case "APPROVED": return "PREPARE"
        case "PUBLISHED": return "PUBLISHED"
        case "REJECTED":
        case "ARCHIVED": return "NEEDS_ATTENTION"
        default: return "NEEDS_ATTENTION"
      }
    default: return "NEEDS_ATTENTION"
  }
}

export function contentWorkflowGroup(stage: ContentWorkflowStage): ContentWorkflowGroup {
  switch (stage) {
    case "AI_DRAFT":
    case "REVIEW":
    case "NEEDS_ATTENTION":
      return "PENDING"
    case "PREPARE":
    case "SCHEDULED":
    case "SUBMITTED":
      return "PLANNED"
    case "PUBLISHED":
      return "COMPLETED"
  }
}

export function canOfferRetry(status: PublishStatus): boolean {
  switch (status) {
    case "FAILED":
    case "CANCELED": return true
    case "SCHEDULED":
    case "QUEUED":
    case "RUNNING":
    case "SUBMITTED":
    case "SUBMISSION_UNKNOWN":
    case "SUCCEEDED":
    case "NEEDS_ATTENTION":
    case null: return false
  }
}
