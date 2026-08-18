import { queryOptions } from "@tanstack/vue-query"

import { apiRequest } from "../../api/client"

export type MissionLaneCounts = {
  ACQUISITION: number
  OUTREACH: number
  SOCIAL: number
  ATTRIBUTION: number
}

export type MissionPlan = {
  id: string
  version: number
  status: "DRAFT" | "APPROVED" | "SUPERSEDED"
  snapshot: Record<string, unknown>
  generation_mode: "AUTOMATION" | "AI_GENERATION"
  provider: string
  model: string
  approved_by: number | null
  approved_at: string | null
  created_at: string
}

export type GrowthMission = {
  id: string
  title: string
  objective: string
  target_countries: string[]
  target_industries: string[]
  customer_profile: string
  primary_product_id: string
  start_date: string
  end_date: string
  target_account_count: number
  target_reply_count: number
  target_rfq_count: number
  budget_micros: number
  allowed_channels: string[]
  attribution_code: string
  status: "DRAFT" | "PENDING_APPROVAL" | "RUNNING" | "PAUSED" | "COMPLETED" | "TERMINATED"
  health_status: string
  health_reason: string
  created_by: number
  created_at: string
  latest_plan: MissionPlan | null
  lane_counts: MissionLaneCounts
  available_actions: string[]
}

export type MissionCreateInput = {
  title: string
  objective: string
  target_countries: string[]
  target_industries: string[]
  customer_profile: string
  primary_product_id: string
  start_date: string
  end_date: string
  target_account_count: number
  target_reply_count: number
  target_rfq_count: number
  budget_micros: number
  allowed_channels: string[]
}

export type MissionTimelineItem = {
  occurred_at: string
  lane: string
  state: string
  title: string
  summary: string
  evidence_type: string
  evidence_id: string
}

export const missionQueryKeys = {
  list: ["growth", "missions"] as const,
  detail: (id: string) => ["growth", "missions", id] as const,
  timeline: (id: string) => ["growth", "missions", id, "timeline"] as const,
}

export function missionsQueryOptions() {
  return queryOptions({
    queryKey: missionQueryKeys.list,
    queryFn: async () => {
      const missions = await apiRequest<GrowthMission[]>("/api/v1/growth/missions")
      if (!missions) throw new Error("增长任务响应为空。")
      return missions
    },
    staleTime: 15_000,
  })
}

export function missionQueryOptions(id: string) {
  return queryOptions({
    queryKey: missionQueryKeys.detail(id),
    queryFn: async () => {
      const mission = await apiRequest<GrowthMission>(`/api/v1/growth/missions/${id}`)
      if (!mission) throw new Error("增长任务响应为空。")
      return mission
    },
    staleTime: 15_000,
  })
}

export function missionTimelineQueryOptions(id: string) {
  return queryOptions({
    queryKey: missionQueryKeys.timeline(id),
    queryFn: async () => {
      const timeline = await apiRequest<MissionTimelineItem[]>(
        `/api/v1/growth/missions/${id}/timeline`,
      )
      if (!timeline) throw new Error("执行时间线响应为空。")
      return timeline
    },
    staleTime: 15_000,
  })
}

export async function createMission(input: MissionCreateInput): Promise<GrowthMission> {
  const mission = await apiRequest<GrowthMission>("/api/v1/growth/missions", {
    method: "POST",
    body: input,
  })
  if (!mission) throw new Error("增长任务创建失败。")
  return mission
}

export async function generateMissionPlan(id: string): Promise<MissionPlan> {
  const plan = await apiRequest<MissionPlan>(`/api/v1/growth/missions/${id}/generate-plan`, {
    method: "POST",
    body: {},
  })
  if (!plan) throw new Error("执行计划生成失败。")
  return plan
}

export async function approveMissionPlan(id: string, planId: string): Promise<MissionPlan> {
  const plan = await apiRequest<MissionPlan>(`/api/v1/growth/missions/${id}/approve-plan`, {
    method: "POST",
    body: { plan_id: planId },
  })
  if (!plan) throw new Error("执行计划批准失败。")
  return plan
}

export async function transitionMission(
  id: string,
  status: "PAUSED" | "RUNNING" | "COMPLETED" | "TERMINATED",
): Promise<GrowthMission> {
  const mission = await apiRequest<GrowthMission>(`/api/v1/growth/missions/${id}/status`, {
    method: "POST",
    body: { status },
  })
  if (!mission) throw new Error("增长任务状态更新失败。")
  return mission
}

export async function startMissionOutreach(
  missionId: string,
  candidateId: string,
): Promise<Record<string, unknown>> {
  return await apiRequest<Record<string, unknown>>(
    `/api/v1/growth/missions/${missionId}/candidates/${candidateId}/start-outreach`,
    { method: "POST", body: {} },
  ) ?? {}
}

export async function startMissionContentStrategy(
  missionId: string,
): Promise<Record<string, unknown>> {
  return await apiRequest<Record<string, unknown>>(
    `/api/v1/growth/missions/${missionId}/start-content-strategy`,
    { method: "POST", body: {} },
  ) ?? {}
}
