import { expect, it } from "vitest"

import { parseOpportunityFilters, serializeOpportunityFilters } from "./opportunityFilters"

it("normalizes opportunity URL filters and preserves a selected account", () => {
  expect(parseOpportunityFilters(new URLSearchParams("q=gear&stage=FOLLOW_UP&sort=newest"))).toEqual({
    q: "gear", stage: "FOLLOW_UP", sort: "newest", selected: null,
  })
  expect(serializeOpportunityFilters({ q: "", stage: "ALL", sort: "score", selected: "acct-1" }))
    .toBe("stage=ALL&sort=score&selected=acct-1")
})

it("falls back from unknown filters and omits blank values", () => {
  expect(parseOpportunityFilters(new URLSearchParams("q=%20%20&stage=UNKNOWN&sort=oldest&selected="))).toEqual({
    q: "", stage: "ALL", sort: "score", selected: null,
  })
  expect(serializeOpportunityFilters({ q: "  ", stage: "ALL", sort: "score", selected: null }))
    .toBe("stage=ALL&sort=score")
})
