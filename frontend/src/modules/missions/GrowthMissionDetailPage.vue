<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"
import { useRoute } from "vue-router"

import { apiRequest } from "../../api/client"
import { currentUserQueryOptions } from "../auth/auth"
import { getPlatformContent, listPlatforms, type PlatformContent } from "../content/api"
import { approveAgentRun } from "../growth/agentApi"
import {
  approveMissionPlan,
  generateMissionPlan,
  missionContentSummaryQueryOptions,
  missionOutreachSummaryQueryOptions,
  missionQueryOptions,
  missionTimelineQueryOptions,
  publishMission,
  startMissionContentStrategy,
  startMissionOutreach,
  transitionMission,
} from "./api"
import ContentReviewDialog from "../content/ContentReviewDialog.vue"
import MissionLaneBoard from "./MissionLaneBoard.vue"

const route = useRoute()
const queryClient = useQueryClient()
const missionId = computed(() => String(route.params.missionId ?? ""))

const currentUserQuery = useQuery(currentUserQueryOptions())
const missionQuery = useQuery(missionQueryOptions(missionId.value))
const timelineQuery = useQuery(missionTimelineQueryOptions(missionId.value))
const contentSummaryQuery = useQuery(missionContentSummaryQueryOptions(missionId.value))
const outreachSummaryQuery = useQuery(missionOutreachSummaryQueryOptions(missionId.value))
const candidatesQuery = useQuery({
  queryKey: ["growth", "missions", missionId.value, "candidates"],
  queryFn: async () => {
    const candidates = await apiRequest<Array<{ id: string; company_name: string }>>(
      `/api/v1/growth/missions/${missionId.value}/candidates`,
    )
    return candidates ?? []
  },
  staleTime: 30_000,
  retry: false,
})

const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const canManage = computed(() => permissions.value.includes("missions.manage"))
const canReview = computed(() => permissions.value.includes("missions.review"))
const canRun = computed(() => permissions.value.includes("agents.run"))
const canApprove = computed(() => permissions.value.includes("agents.approve"))

const mission = computed(() => missionQuery.data.value)
const contentSummary = computed(() => contentSummaryQuery.data.value)
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
  onSuccess: async () => {
    refresh()
    await queryClient.invalidateQueries({
      queryKey: ["growth", "missions", missionId.value, "outreach-summary"],
    })
  },
})

const strategyMutation = useMutation({
  mutationFn: () => startMissionContentStrategy(missionId.value),
  onSuccess: refresh,
})

const publishMutation = useMutation({
  mutationFn: () => publishMission(missionId.value),
  onSuccess: async () => {
    await refreshContentSummary()
  },
})

const outreachApproveMutation = useMutation({
  mutationFn: ({ runId, decision }: { runId: string; decision: "approve" | "reject" }) => (
    approveAgentRun(runId, decision)
  ),
  onSuccess: async () => {
    await queryClient.invalidateQueries({
      queryKey: ["growth", "missions", missionId.value, "outreach-summary"],
    })
    await queryClient.invalidateQueries({ queryKey: ["growth", "agent-runs"] })
  },
})

function approveOutreach(runId: string, decision: "approve" | "reject"): void {
  outreachApproveMutation.mutate({ runId, decision })
}

const platformsQuery = useQuery({
  queryKey: ["content", "platforms"],
  queryFn: listPlatforms,
  staleTime: 60_000,
  retry: false,
})

const reviewingContent = ref<PlatformContent | null>(null)
const reviewBusy = ref(false)

async function openReview(contentId: string): Promise<void> {
  reviewBusy.value = true
  try {
    reviewingContent.value = await getPlatformContent(contentId)
  } finally {
    reviewBusy.value = false
  }
}

function closeReview(): void {
  reviewingContent.value = null
}

async function refreshContentSummary(): Promise<void> {
  await queryClient.invalidateQueries({
    queryKey: ["growth", "missions", missionId.value, "content-summary"],
  })
}

async function reviewConflict(): Promise<void> {
  reviewingContent.value = null
  await refreshContentSummary()
}
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
        <div v-if="contentSummary" class="content-summary">
          <h3>社媒内容</h3>
          <ul v-if="contentSummary.platform_contents.length" class="content-list">
            <li v-for="content in contentSummary.platform_contents" :key="content.id">
              <span>{{ content.platform_code }} · {{ content.title }}</span>
              <span class="chip">{{ content.status }}</span>
              <button
                v-if="content.status === 'IN_REVIEW'"
                class="review-link"
                type="button"
                :disabled="reviewBusy"
                @click="openReview(content.id)"
              >
                去审核
              </button>
            </li>
          </ul>
          <p v-else>暂无平台版本。</p>
          <p>发布包 {{ contentSummary.channel_packages.length }} 个</p>
        </div>
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

      <section v-if="view === 'customer'" class="panel">
        <h2>开发信队列</h2>
        <p v-if="outreachSummaryQuery.isPending.value">正在读取开发信…</p>
        <p v-else-if="!outreachSummaryQuery.data.value?.length">暂无已开始的获客任务。</p>
        <ol v-else class="outreach-list">
          <li v-for="item in outreachSummaryQuery.data.value" :key="item.candidate_id">
            <div class="outreach-head">
              <strong>{{ item.company_name }}</strong>
              <span class="chip">{{ item.agent_run?.status ?? "未开始" }}</span>
            </div>
            <template v-if="item.draft">
              <p class="draft-en">{{ item.draft.english_draft }}</p>
              <p class="draft-zh">{{ item.draft.chinese_explanation }}</p>
            </template>
            <p v-else class="muted">尚未生成开发信。</p>
            <div
              v-if="canApprove && item.agent_run?.status === 'WAITING_APPROVAL'"
              class="outreach-actions"
            >
              <button
                class="button button-primary"
                type="button"
                :disabled="outreachApproveMutation.isPending.value"
                @click="approveOutreach(item.agent_run.id, 'approve')"
              >
                批准发送
              </button>
              <button
                class="button button-quiet"
                type="button"
                :disabled="outreachApproveMutation.isPending.value"
                @click="approveOutreach(item.agent_run.id, 'reject')"
              >
                拒绝
              </button>
            </div>
            <p v-if="item.latest_message" class="muted">
              最新结果：{{ item.latest_message.status }} · {{ item.latest_message.provider }}
            </p>
          </li>
        </ol>
      </section>

      <section v-if="view === 'social'" class="panel">
        <h2>发布准备</h2>
        <p v-if="!contentSummary?.channel_packages.length">还没有渠道内容包。先在“总览”里审核平台内容。</p>
        <ul v-else class="content-list">
          <li v-for="packageItem in contentSummary.channel_packages" :key="packageItem.id">
            <span>{{ packageItem.channel }}</span>
            <span class="chip">{{ packageItem.status }}</span>
          </li>
        </ul>
        <div v-if="canManage && mission.status === 'RUNNING' && contentSummary?.channel_packages.length" class="actions">
          <button
            class="button button-primary"
            type="button"
            :disabled="publishMutation.isPending.value"
            @click="publishMutation.mutate()"
          >
            批准并发布
          </button>
        </div>
        <div v-if="contentSummary?.publish_batches.length" class="publish-batches">
          <h3>发布结果</h3>
          <article v-for="batch in contentSummary.publish_batches" :key="batch.id">
            <p><span class="chip">{{ batch.status }}</span> · {{ batch.data_label }}</p>
            <ul>
              <li v-for="item in batch.items" :key="item.id">
                {{ item.channel }} · {{ item.status }}<template v-if="item.error_code"> · {{ item.error_code }}</template>
              </li>
            </ul>
          </article>
        </div>
      </section>

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

    <ContentReviewDialog
      v-if="reviewingContent"
      :item="reviewingContent"
      kind="platform"
      :permissions="permissions"
      :current-head="reviewingContent.is_current_head"
      :platforms="platformsQuery.data.value ?? []"
      @close="closeReview"
      @updated="refreshContentSummary"
      @platform-generated="refreshContentSummary"
      @conflict="reviewConflict"
    />
  </main>
</template>

<style scoped>
.mission-detail-page { display: grid; gap: 16px; }
.detail-hero { display: flex; align-items: center; justify-content: space-between; gap: 20px; border-radius: 20px; background: linear-gradient(120deg, var(--sg-brand-deep) 0%, var(--sg-brand-strong) 60%, var(--sg-brand-light) 100%); padding: 24px 28px; color: #fff; }
.detail-hero h1 { margin: 4px 0 7px; font-size: clamp(1.45rem, 2vw, 1.85rem); }
.detail-hero p { margin: 0; color: #eaf5ff; font-size: .82rem; line-height: 1.55; }
.eyebrow { margin: 0; color: #bfe0ff; font-size: .65rem; font-weight: 900; letter-spacing: .1em; }
.status-chip { border-radius: 999px; border: 1px solid rgb(255 255 255 / 40%); padding: 5px 11px; font-size: .72rem; }
.section-nav { display: flex; flex-wrap: wrap; gap: 6px; }
.section-nav a { border-radius: 999px; padding: 7px 12px; color: var(--sg-muted); text-decoration: none; font-size: .76rem; }
.section-nav a.active { background: var(--sg-brand); color: #fff; }
.panel { display: grid; gap: 12px; border: 1px solid var(--sg-line); border-radius: 16px; background: #fff; padding: 18px; }
.panel h2 { margin: 0; font-size: 1rem; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 0; }
.facts dt { color: var(--sg-muted); font-size: .68rem; }
.facts dd { margin: 2px 0 0; font-size: .8rem; }
.content-summary { border-top: 1px solid var(--sg-line); padding-top: 10px; }
.content-summary h3 { margin: 0 0 4px; font-size: .8rem; }
.content-summary p { margin: 0; color: var(--sg-muted); font-size: .74rem; }
.content-list { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }
.content-list li { display: flex; align-items: center; gap: 8px; font-size: .74rem; }
.content-list .chip { border-radius: 999px; background: #eef2f6; padding: 2px 7px; color: #4f5d6c; font-size: .66rem; }
.review-link { border: 0; background: transparent; padding: 0; color: var(--sg-brand); cursor: pointer; font-size: .74rem; }
.review-link:disabled { color: var(--sg-muted); cursor: default; }
.outreach-list { display: grid; gap: 12px; margin: 0; padding: 0; list-style: none; }
.outreach-list li { display: grid; gap: 8px; border: 1px solid var(--sg-line); border-radius: 12px; padding: 14px; }
.outreach-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.outreach-head strong { font-size: .86rem; }
.outreach-head .chip { border-radius: 999px; background: #eef2f6; padding: 2px 7px; color: #4f5d6c; font-size: .66rem; }
.draft-en { margin: 0; color: var(--sg-ink); font-size: .82rem; white-space: pre-wrap; }
.draft-zh { margin: 0; color: var(--sg-muted); font-size: .76rem; }
.outreach-actions { display: flex; gap: 8px; }
.publish-batches { display: grid; gap: 10px; border-top: 1px solid var(--sg-line); padding-top: 10px; }
.publish-batches h3 { margin: 0; font-size: .8rem; }
.publish-batches article { display: grid; gap: 6px; }
.publish-batches p { margin: 0; font-size: .76rem; }
.publish-batches ul { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; font-size: .74rem; color: var(--sg-muted); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.timeline { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.timeline li { display: grid; gap: 3px; border-left: 2px solid var(--sg-line); padding-left: 12px; }
.timeline time { color: var(--sg-muted); font-size: .68rem; }
.timeline p { margin: 0; color: var(--sg-muted); font-size: .76rem; }
.empty-card { margin: 0; border: 1px dashed var(--sg-line); border-radius: 12px; padding: 18px; color: var(--sg-muted); }
.error { color: var(--sg-danger); }
.button-danger { border: 1px solid #f3c2c2; background: #fff; color: var(--sg-danger); }
</style>
