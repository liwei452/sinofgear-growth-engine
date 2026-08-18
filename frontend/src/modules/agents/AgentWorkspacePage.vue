<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, ref, watch } from "vue"
import { useRoute } from "vue-router"

import AppIcon from "../../shared/components/AppIcon.vue"
import {
  agentRunsQueryOptions,
  approveAgentRun,
  startAgentRun,
} from "../growth/agentApi"
import { getProductAIStatus } from "../settings/api"
import AgentCapabilityCard from "./AgentCapabilityCard.vue"
import AgentRunTimeline from "./AgentRunTimeline.vue"
import ModelStatusCard from "./ModelStatusCard.vue"

const route = useRoute()
const queryClient = useQueryClient()
const runsQuery = useQuery(agentRunsQueryOptions())
const modelQuery = useQuery({
  queryKey: ["settings", "product-ai-status"],
  queryFn: getProductAIStatus,
  staleTime: 30_000,
})
const startDialogOpen = ref(false)
const actionNotice = ref("")
const cancelStartButton = ref<HTMLButtonElement | null>(null)
const startDialog = ref<HTMLElement | null>(null)
let startDialogReturnFocus: HTMLElement | null = null

watch(startDialogOpen, async (open) => {
  if (open) {
    startDialogReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    cancelStartButton.value?.focus()
  } else {
    startDialogReturnFocus?.focus()
    startDialogReturnFocus = null
  }
})

function onStartDialogKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault()
    startDialogOpen.value = false
    return
  }
  if (event.key !== "Tab" || !startDialog.value) return
  const controls = [...startDialog.value.querySelectorAll<HTMLElement>("button:not([disabled])")]
  const first = controls[0]
  const last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

const pendingRuns = computed(() => (
  (runsQuery.data.value ?? []).filter(run => run.status === "WAITING_APPROVAL")
))
const visibleRuns = computed(() => {
  const runs = route.query.view === "approvals" ? pendingRuns.value : (runsQuery.data.value ?? [])
  return runs.slice(0, 6)
})

const approveMutation = useMutation({
  mutationFn: ({ runId, decision }: { runId: string; decision: "approve" | "reject" }) => (
    approveAgentRun(runId, decision)
  ),
  onSuccess: async () => {
    actionNotice.value = "任务状态已更新。"
    await queryClient.invalidateQueries({ queryKey: ["growth", "agent-runs"] })
  },
  onError: (error) => {
    actionNotice.value = error instanceof Error ? error.message : "任务处理失败。"
  },
})

const startMutation = useMutation({
  mutationFn: () => startAgentRun("content_strategy"),
  onSuccess: async () => {
    startDialogOpen.value = false
    actionNotice.value = "内容策略任务已启动。"
    await queryClient.invalidateQueries({ queryKey: ["growth", "agent-runs"] })
  },
  onError: (error) => {
    actionNotice.value = error instanceof Error ? error.message : "任务启动失败。"
  },
})
</script>

<template>
  <main class="agent-workspace-page">
    <header class="workspace-hero">
      <div>
        <p class="eyebrow">AI GROWTH OPERATIONS</p>
        <h1>Agent 工作台</h1>
        <p>让 Agent 参与获客判断、内容策略与社媒运营；写入数据、发布和客户触达仍由你批准。</p>
      </div>
      <div class="hero-mark" aria-hidden="true"><AppIcon name="bot" :size="30" /></div>
    </header>

    <ModelStatusCard
      :status="modelQuery.data.value ?? null"
      :pending-approvals="pendingRuns.length"
    />
    <p v-if="actionNotice" class="workspace-notice" role="status">{{ actionNotice }}</p>

    <section class="capability-section" aria-labelledby="agent-capabilities-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">四类业务角色</p>
          <h2 id="agent-capabilities-title">选择你要推进的工作</h2>
        </div>
        <span>能力边界与执行方式清晰标注</span>
      </div>
      <div class="capability-grid">
        <AgentCapabilityCard
          title="获客 Agent"
          description="根据公开证据筛选客户、补全线索并准备人工跟进。"
          icon="users-round"
          :mode="modelQuery.data.value?.real_requests_enabled ? 'AI 判断 + 自动化' : '自动化流程'"
          :capabilities="['判断客户匹配度', '整理网站公开证据', '准备开发信草稿']"
          action-label="查看客户机会"
          action-to="/opportunities"
        />
        <AgentCapabilityCard
          title="内容 Agent"
          description="结合客户信号提出选题，再进入受控的内容生成流程。"
          icon="sparkles"
          mode="AI 生成任务"
          :capabilities="['分析内容机会', '准备内容 Brief', '交回内容工厂生成']"
          action-label="启动内容策略"
          @action="startDialogOpen = true"
        />
        <AgentCapabilityCard
          title="社媒 Agent"
          description="汇总真实表现、提出排期建议，并在批准后安排发布。"
          icon="send"
          mode="自动化流程"
          :capabilities="['分析渠道表现', '建议发布节奏', '审批后安排发布']"
          action-label="进入社媒运营"
          action-to="/promotion"
        />
        <AgentCapabilityCard
          title="客户激活 Agent"
          description="围绕已有询盘和合法客户关系准备下一步跟进，不自动发送邮件。"
          icon="inbox"
          mode="自动化流程"
          :capabilities="['识别待跟进客户', '准备回复草稿', '记录人工处理结果']"
          action-label="查看待跟进客户"
          action-to="/opportunities"
        />
      </div>
    </section>

    <section class="run-section" aria-labelledby="agent-runs-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">运行记录</p>
          <h2 id="agent-runs-title">{{ route.query.view === "approvals" ? "等待你批准" : "最近任务" }}</h2>
        </div>
        <span>{{ visibleRuns.length }} 条</span>
      </div>
      <p v-if="runsQuery.isLoading.value" class="empty-card">正在读取 Agent 任务…</p>
      <p v-else-if="runsQuery.isError.value" class="empty-card error" role="alert">Agent 任务暂时无法读取。</p>
      <div v-else-if="visibleRuns.length" class="run-grid">
        <AgentRunTimeline
          v-for="run in visibleRuns"
          :key="run.id"
          :run="run"
          :busy="approveMutation.isPending.value"
          @approve="approveMutation.mutate({ runId: run.id, decision: 'approve' })"
          @reject="approveMutation.mutate({ runId: run.id, decision: 'reject' })"
        />
      </div>
      <div v-else class="empty-card">
        <strong>{{ route.query.view === "approvals" ? "当前没有等待批准的任务" : "还没有 Agent 运行记录" }}</strong>
        <p>可以从上方内容 Agent 开始一次受控的内容策略任务。</p>
        <button class="button button-primary" type="button" @click="startDialogOpen = true">启动内容策略</button>
      </div>
    </section>

    <div v-if="startDialogOpen" class="dialog-backdrop" role="presentation" @click.self="startDialogOpen = false">
      <section ref="startDialog" class="start-dialog" role="dialog" aria-modal="true" aria-labelledby="start-agent-title" @keydown="onStartDialogKeydown">
        <div class="dialog-icon"><AppIcon name="sparkles" :size="24" /></div>
        <h2 id="start-agent-title">启动内容策略 Agent</h2>
        <p>Agent 会分析已记录的客户和询盘信号。若要创建 Brief，会暂停并等待你的批准。</p>
        <div>
          <button ref="cancelStartButton" class="button button-quiet" type="button" :disabled="startMutation.isPending.value" @click="startDialogOpen = false">取消</button>
          <button class="button button-primary" type="button" :disabled="startMutation.isPending.value" @click="startMutation.mutate()">
            {{ startMutation.isPending.value ? "正在启动…" : "确认启动" }}
          </button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.agent-workspace-page { display: grid; gap: 20px; }
.workspace-hero { display: flex; align-items: center; justify-content: space-between; gap: 20px; border-radius: 20px; background: linear-gradient(120deg, #0875eb 0%, #1687ff 55%, #3eb6ff 100%); padding: 25px 28px; color: #fff; box-shadow: 0 16px 34px rgb(22 135 255 / 20%); }
.workspace-hero .eyebrow { color: #dcefff; }
.workspace-hero h1 { margin: 4px 0 7px; font-size: clamp(1.55rem, 2vw, 2rem); }
.workspace-hero p:last-child { max-width: 760px; margin: 0; color: #eaf5ff; font-size: .82rem; line-height: 1.6; }
.hero-mark { display: grid; width: 62px; height: 62px; flex: 0 0 auto; place-items: center; border: 1px solid rgb(255 255 255 / 38%); border-radius: 18px; background: rgb(255 255 255 / 16%); }
.eyebrow { margin: 0; color: var(--sg-brand); font-size: .65rem; font-weight: 900; letter-spacing: .1em; }
.capability-section, .run-section { display: grid; gap: 14px; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 14px; }
.section-heading h2 { margin: 4px 0 0; color: var(--sg-ink); font-size: 1.08rem; }
.section-heading > span { color: var(--sg-muted); font-size: .7rem; }
.capability-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.run-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; align-items: start; }
.workspace-notice { margin: 0; border-radius: 10px; background: #e9fbf4; padding: 10px 13px; color: #19795b; font-size: .76rem; }
.empty-card { display: grid; justify-items: start; gap: 10px; margin: 0; border: 1px dashed #bfd9f4; border-radius: 16px; background: #fff; padding: 22px; color: var(--sg-muted); }
.empty-card p { margin: 0; font-size: .75rem; }
.error { color: var(--sg-danger); }
.dialog-backdrop { position: fixed; z-index: 50; inset: 0; display: grid; place-items: center; background: rgb(16 42 86 / 34%); padding: 18px; }
.start-dialog { display: grid; width: min(460px, 100%); gap: 13px; border-radius: 20px; background: #fff; padding: 25px; box-shadow: 0 24px 70px rgb(16 42 86 / 24%); }
.dialog-icon { display: grid; width: 48px; height: 48px; place-items: center; border-radius: 14px; background: var(--sg-brand-soft); color: var(--sg-brand); }
.start-dialog h2, .start-dialog p { margin: 0; }
.start-dialog p { color: var(--sg-muted); font-size: .8rem; line-height: 1.55; }
.start-dialog > div:last-child { display: flex; justify-content: flex-end; gap: 8px; margin-top: 7px; }
@media (max-width: 1180px) { .capability-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 850px) { .run-grid { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .workspace-hero { align-items: flex-start; padding: 20px; }.hero-mark { width: 48px; height: 48px; }.capability-grid { grid-template-columns: 1fr; }.section-heading { align-items: flex-start; flex-direction: column; } }
</style>
