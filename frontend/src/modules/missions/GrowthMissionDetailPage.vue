<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed } from "vue"
import { useRoute } from "vue-router"

import { apiRequest } from "../../api/client"
import { currentUserQueryOptions } from "../auth/auth"
import {
  approveMissionPlan,
  generateMissionPlan,
  missionQueryOptions,
  missionTimelineQueryOptions,
  startMissionContentStrategy,
  startMissionOutreach,
  transitionMission,
} from "./api"
import MissionLaneBoard from "./MissionLaneBoard.vue"

const route = useRoute()
const queryClient = useQueryClient()
const missionId = computed(() => String(route.params.missionId ?? ""))

const currentUserQuery = useQuery(currentUserQueryOptions())
const missionQuery = useQuery(missionQueryOptions(missionId.value))
const timelineQuery = useQuery(missionTimelineQueryOptions(missionId.value))
const candidatesQuery = useQuery({
  queryKey: ["growth", "workspace", "mission-candidates"],
  queryFn: async () => {
    const workspace = await apiRequest<{
      discovery?: { candidates?: Array<{ id: string; company_name: string; status: string }> }
    }>("/api/v1/growth/workspace")
    return (workspace?.discovery?.candidates ?? []).filter(
      candidate => candidate.status === "ACCEPTED",
    )
  },
  staleTime: 30_000,
  retry: false,
})

const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const canManage = computed(() => permissions.value.includes("missions.manage"))
const canReview = computed(() => permissions.value.includes("missions.review"))
const canRun = computed(() => permissions.value.includes("agents.run"))

const mission = computed(() => missionQuery.data.value)
const view = computed(() => (typeof route.query.view === "string" ? route.query.view : "overview"))

const notices = {
  overview: "总览",
  customer: "客户开发",
  social: "社媒增长",
  timeline: "执行时间线",
  attribution: "结果与归因",
} as const

const refresh = () => {
  void queryClient.invalidateQueries({ queryKey: ["growth", "missions"] })
  void queryClient.invalidateQueries({ queryKey: ["growth", "work-items"] })
}

const generateMutation = useMutation({
  mutationFn: () => generateMissionPlan(missionId.value),
  onSuccess: refresh,
})

const approveMutation = useMutation({
  mutationFn: (planId: string) => approveMissionPlan(missionId.value, planId),
  onSuccess: refresh,
})

const transitionMutation = useMutation({
  mutationFn: (status: "PAUSED" | "RUNNING" | "COMPLETED" | "TERMINATED") => (
    transitionMission(missionId.value, status)
  ),
  onSuccess: refresh,
})

const outreachMutation = useMutation({
  mutationFn: (candidateId: string) => startMissionOutreach(missionId.value, candidateId),
  onSuccess: refresh,
})

const strategyMutation = useMutation({
  mutationFn: () => startMissionContentStrategy(missionId.value),
  onSuccess: refresh,
})
</script>

<template>
  <main class="mission-detail-page">
    <header class="detail-hero">
      <div>
        <p class="eyebrow">GROWTH MISSION</p>
        <h1>{{ mission?.title ?? "增长任务" }}</h1>
        <p>{{ mission?.objective }}</p>
      </div>
      <span class="status-chip">{{ mission?.status }}</span>
    </header>

    <nav class="section-nav" aria-label="任务分区">
      <RouterLink
        v-for="(label, key) in notices"
        :key="key"
        :to="{ query: { view: key } }"
        :class="{ active: view === key }"
      >
        {{ label }}
      </RouterLink>
    </nav>

    <div v-if="missionQuery.isLoading.value" class="empty-card">正在读取增长任务…</div>
    <div v-else-if="!mission" class="empty-card error">未找到该增长任务。</div>
    <template v-else>
      <section v-if="view === 'overview'" class="panel">
        <h2>总览</h2>
        <dl class="facts">
          <div><dt>国家</dt><dd>{{ mission.target_countries.join(", ") }}</dd></div>
          <div><dt>行业</dt><dd>{{ mission.target_industries.join(", ") }}</dd></div>
          <div><dt>周期</dt><dd>{{ mission.start_date }} ~ {{ mission.end_date }}</dd></div>
          <div><dt>健康状态</dt><dd>{{ mission.health_status }}</dd></div>
          <div><dt>归因码</dt><dd>{{ mission.attribution_code }}</dd></div>
        </dl>
        <div class="actions">
          <button
            v-if="canManage && ['DRAFT', 'PENDING_APPROVAL'].includes(mission.status)"
            class="button button-primary"
            type="button"
            :disabled="generateMutation.isPending.value"
            @click="generateMutation.mutate()"
          >
            生成执行计划
          </button>
          <button
            v-if="canReview && mission.status === 'PENDING_APPROVAL' && mission.latest_plan"
            class="button button-primary"
            type="button"
            :disabled="approveMutation.isPending.value"
            @click="approveMutation.mutate(mission.latest_plan.id)"
          >
            批准并启动
          </button>
          <button
            v-if="canManage && mission.status === 'RUNNING'"
            class="button button-quiet"
            type="button"
            @click="transitionMutation.mutate('PAUSED')"
          >
            暂停
          </button>
          <button
            v-if="canManage && mission.status === 'PAUSED'"
            class="button button-quiet"
            type="button"
            @click="transitionMutation.mutate('RUNNING')"
          >
            恢复
          </button>
          <button
            v-if="canManage && !['COMPLETED', 'TERMINATED'].includes(mission.status)"
            class="button button-danger"
            type="button"
            @click="transitionMutation.mutate('TERMINATED')"
          >
            终止
          </button>
        </div>
      </section>

      <MissionLaneBoard
        v-if="['overview', 'customer', 'social'].includes(view)"
        :mission="mission"
        :can-run="canRun"
        :candidates="candidatesQuery.data.value ?? []"
        @start-outreach="outreachMutation.mutate"
        @start-content-strategy="strategyMutation.mutate"
      />

      <section v-if="view === 'timeline'" class="panel">
        <h2>执行时间线</h2>
        <ol class="timeline">
          <li v-for="item in timelineQuery.data.value ?? []" :key="item.evidence_id">
            <time>{{ item.occurred_at }}</time>
            <strong>{{ item.title }}</strong>
            <p>{{ item.summary }}</p>
          </li>
        </ol>
        <p v-if="!timelineQuery.data.value?.length" class="empty-card">暂无执行记录。</p>
      </section>

      <section v-if="view === 'attribution'" class="panel">
        <h2>结果与归因</h2>
        <p>有效回复、RFQ、报价与订单的归因将在数据归因驾驶舱中呈现。</p>
      </section>
    </template>
  </main>
</template>

<style scoped>
.mission-detail-page { display: grid; gap: 16px; }
.detail-hero { display: flex; align-items: center; justify-content: space-between; gap: 20px; border-radius: 20px; background: linear-gradient(120deg, #0b3b8f 0%, #0875eb 60%, #3eb6ff 100%); padding: 24px 28px; color: #fff; }
.detail-hero h1 { margin: 4px 0 7px; font-size: clamp(1.45rem, 2vw, 1.85rem); }
.detail-hero p { margin: 0; color: #eaf5ff; font-size: .82rem; line-height: 1.55; }
.eyebrow { margin: 0; color: #bfe0ff; font-size: .65rem; font-weight: 900; letter-spacing: .1em; }
.status-chip { border-radius: 999px; border: 1px solid rgb(255 255 255 / 40%); padding: 5px 11px; font-size: .72rem; }
.section-nav { display: flex; flex-wrap: wrap; gap: 6px; }
.section-nav a { border-radius: 999px; padding: 7px 12px; color: var(--sg-muted); text-decoration: none; font-size: .76rem; }
.section-nav a.active { background: var(--sg-brand); color: #fff; }
.panel { display: grid; gap: 12px; border: 1px solid #e5ecf6; border-radius: 16px; background: #fff; padding: 18px; }
.panel h2 { margin: 0; font-size: 1rem; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 0; }
.facts dt { color: var(--sg-muted); font-size: .68rem; }
.facts dd { margin: 2px 0 0; font-size: .8rem; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.timeline { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.timeline li { display: grid; gap: 3px; border-left: 2px solid #bfd9f4; padding-left: 12px; }
.timeline time { color: var(--sg-muted); font-size: .68rem; }
.timeline p { margin: 0; color: var(--sg-muted); font-size: .76rem; }
.empty-card { margin: 0; border: 1px dashed #bfd9f4; border-radius: 12px; padding: 18px; color: var(--sg-muted); }
.error { color: var(--sg-danger); }
.button-danger { border: 1px solid #f3c2c2; background: #fff; color: #c0392b; }
</style>
