<script setup lang="ts">
import { computed } from "vue"
import { RouterLink } from "vue-router"

import type { AgentRun } from "../growth/agentApi"
import type { ProductAIStatus } from "../settings/api"

export type DashboardChannelIssue = {
  code: string
  name: string
  status: string
  recovery: string
}

const props = defineProps<{
  modelStatus: ProductAIStatus | null
  pendingRuns: AgentRun[]
  channelIssues: DashboardChannelIssue[]
  completedRuns: AgentRun[]
}>()

const modelSummary = computed(() => {
  if (!props.modelStatus) return "状态暂不可用"
  if (props.modelStatus.mode === "CONFIGURED_AI") {
    return `${props.modelStatus.provider_label} · ${props.modelStatus.model}`
  }
  if (props.modelStatus.mode === "FAKE_OFFLINE") return "离线演示 · 不会调用外部模型"
  return "尚未配置真实模型"
})
</script>

<template>
  <aside class="dashboard-rail" aria-label="工作台状态">
    <section class="rail-card model-card">
      <div class="rail-title">
        <div>
          <p>MODEL STATUS</p>
          <h2>Agent 与模型</h2>
        </div>
        <span class="model-pulse" aria-hidden="true" />
      </div>
      <strong>{{ modelSummary }}</strong>
      <RouterLink to="/settings">检查模型设置</RouterLink>
    </section>

    <section class="rail-card">
      <div class="rail-title">
        <h2>等待你处理</h2>
        <span>{{ pendingRuns.length }}</span>
      </div>
      <ul v-if="pendingRuns.length" class="rail-list">
        <li v-for="run in pendingRuns.slice(0, 3)" :key="run.id">
          <strong>{{ run.goal }}</strong>
          <small>等待人工批准</small>
        </li>
      </ul>
      <p v-else class="rail-empty">当前没有等待审批的 Agent 任务。</p>
      <RouterLink to="/agent-workspace?view=approvals">查看审批任务</RouterLink>
    </section>

    <section class="rail-card">
      <div class="rail-title">
        <h2>社媒渠道</h2>
        <span>{{ channelIssues.length }}</span>
      </div>
      <ul v-if="channelIssues.length" class="rail-list channel-issues">
        <li v-for="issue in channelIssues.slice(0, 5)" :key="issue.code">
          <strong>{{ issue.name }}</strong>
          <small>{{ issue.status }} · {{ issue.recovery }}</small>
        </li>
      </ul>
      <p v-else class="rail-empty">渠道状态暂无异常记录。</p>
      <RouterLink to="/platform-accounts">管理平台账户</RouterLink>
    </section>

    <section class="rail-card">
      <div class="rail-title">
        <h2>最近完成</h2>
        <span>{{ completedRuns.length }}</span>
      </div>
      <ul v-if="completedRuns.length" class="rail-list">
        <li v-for="run in completedRuns.slice(0, 3)" :key="run.id">
          <strong>{{ run.goal }}</strong>
          <small>{{ new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(run.updated_at)) }}</small>
        </li>
      </ul>
      <p v-else class="rail-empty">还没有已完成的 Agent 任务。</p>
      <RouterLink to="/agent-workspace">打开 Agent 工作台</RouterLink>
    </section>
  </aside>
</template>

<style scoped>
.dashboard-rail { display: grid; gap: 14px; align-content: start; }
.rail-card { display: grid; gap: 13px; border: 1px solid var(--sg-line); border-radius: 16px; background: white; padding: 18px; box-shadow: var(--sg-shadow-sm); }
.model-card { border-color: #cfe7ff; background: linear-gradient(145deg, #fff 0%, #eef7ff 100%); }
.rail-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.rail-title h2, .rail-title p { margin: 0; }
.rail-title h2 { font-size: 1rem; }
.rail-title p { margin-bottom: 4px; color: var(--sg-brand); font-size: .65rem; font-weight: 850; letter-spacing: .1em; }
.rail-title > span:not(.model-pulse) { display: grid; min-width: 26px; height: 26px; place-items: center; border-radius: 999px; background: var(--sg-brand-soft); color: var(--sg-brand-strong); font-size: .75rem; font-weight: 800; }
.model-pulse { width: 10px; height: 10px; border-radius: 50%; background: var(--sg-success); box-shadow: 0 0 0 5px rgb(40 184 135 / 12%); }
.rail-card > strong { color: var(--sg-ink); font-size: .9rem; line-height: 1.5; }
.rail-card > a { width: max-content; color: var(--sg-brand-strong); font-size: .82rem; font-weight: 750; text-decoration: none; }
.rail-list { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.rail-list li { display: grid; gap: 3px; border-left: 3px solid var(--sg-brand); padding-left: 10px; }
.channel-issues li { border-left-color: var(--sg-warning); }
.rail-list strong { font-size: .83rem; }
.rail-list small, .rail-empty { color: var(--sg-muted); font-size: .76rem; line-height: 1.5; }
.rail-empty { margin: 0; }
</style>
