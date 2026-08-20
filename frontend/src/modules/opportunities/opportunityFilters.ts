export const opportunityStages = ["ALL", "CANDIDATE", "ENRICHMENT", "FOLLOW_UP", "DRAFT"] as const
export const opportunitySorts = ["score", "newest"] as const

export type OpportunityStage = typeof opportunityStages[number]
export type OpportunitySort = typeof opportunitySorts[number]

export type OpportunityFilters = {
  q: string
  stage: OpportunityStage
  sort: OpportunitySort
  selected: string | null
}

function isStage(value: string | null): value is OpportunityStage {
  return opportunityStages.includes(value as OpportunityStage)
}

function isSort(value: string | null): value is OpportunitySort {
  return opportunitySorts.includes(value as OpportunitySort)
}

export function parseOpportunityFilters(query: URLSearchParams): OpportunityFilters {
  const q = query.get("q")?.trim() ?? ""
  const selected = query.get("selected")?.trim() || null
  const stage = query.get("stage")
  const sort = query.get("sort")
  return {
    q,
    stage: isStage(stage) ? stage : "ALL",
    sort: isSort(sort) ? sort : "score",
    selected,
  }
}

export function serializeOpportunityFilters(filters: OpportunityFilters): string {
  const query = new URLSearchParams({ stage: filters.stage, sort: filters.sort })
  const q = filters.q.trim()
  const selected = filters.selected?.trim()
  if (q) query.set("q", q)
  if (selected) query.set("selected", selected)
  return query.toString()
}
