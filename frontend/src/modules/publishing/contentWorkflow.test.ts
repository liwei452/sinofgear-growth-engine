import { expect, it } from "vitest"

import { canOfferRetry, contentWorkflowStage } from "./contentWorkflow"

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
