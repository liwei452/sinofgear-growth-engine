import { expect, it } from "vitest"

import { canOfferRetry, contentWorkflowGroup, contentWorkflowStage } from "./contentWorkflow"

it("routes content and publication facts into the correct operational stage", () => {
  expect(contentWorkflowStage({ contentStatus: "DRAFT", publishStatus: null })).toBe("AI_DRAFT")
  expect(contentWorkflowStage({ contentStatus: "IN_REVIEW", publishStatus: null })).toBe("REVIEW")
  expect(contentWorkflowStage({ contentStatus: "APPROVED", publishStatus: "SCHEDULED" })).toBe("SCHEDULED")
  expect(contentWorkflowStage({ contentStatus: "APPROVED", publishStatus: "SUBMISSION_UNKNOWN" })).toBe("SUBMITTED")
})

it("does not offer a duplicate publication retry when submission confirmation is unknown", () => {
  expect(canOfferRetry("SUBMISSION_UNKNOWN")).toBe(false)
  expect(canOfferRetry("FAILED")).toBe(true)
})

it("uses the neutral attention state for an unrecognized runtime status", () => {
  expect(contentWorkflowStage({ contentStatus: "APPROVED", publishStatus: "NEW_SERVER_STATUS" as never })).toBe("NEEDS_ATTENTION")
})

it("groups all seven operational statuses into three operator-facing stages", () => {
  expect(contentWorkflowGroup("AI_DRAFT")).toBe("PENDING")
  expect(contentWorkflowGroup("REVIEW")).toBe("PENDING")
  expect(contentWorkflowGroup("NEEDS_ATTENTION")).toBe("PENDING")
  expect(contentWorkflowGroup("PREPARE")).toBe("PLANNED")
  expect(contentWorkflowGroup("SCHEDULED")).toBe("PLANNED")
  expect(contentWorkflowGroup("SUBMITTED")).toBe("PLANNED")
  expect(contentWorkflowGroup("PUBLISHED")).toBe("COMPLETED")
})
