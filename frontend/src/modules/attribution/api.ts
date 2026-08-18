import { queryOptions } from "@tanstack/vue-query"

import { apiRequest } from "../../api/client"

export type AttributionTrace = {
  confidence: "CONFIRMED" | "ASSISTED" | "UNATTRIBUTED"
  type: string
  source_id: string
}

export type MissionAttribution = {
  outcomes: {
    emails_sent: number | null
    confirmed_replies: number
    confirmed_rfqs: number
    won_revenue: { amount: string }
    cost_per_result: number | null
  }
  diagnostics: { impressions: number }
  availability: { email: string }
  traces: AttributionTrace[]
}

export function missionAttributionQueryOptions(missionId: string) {
  return queryOptions({
    queryKey: ["growth", "attribution", missionId],
    queryFn: async () => {
      const result = await apiRequest<MissionAttribution>(
        `/api/v1/growth/attribution?mission=${missionId}`,
      )
      if (!result) throw new Error("归因响应为空。")
      return result
    },
    staleTime: 15_000,
  })
}
