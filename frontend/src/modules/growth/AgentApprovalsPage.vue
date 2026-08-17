<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import { agentRunsQueryOptions, approveAgentRun, type AgentRun } from "./agentApi"

const queryClient = useQueryClient()
const runsQuery = useQuery(agentRunsQueryOptions())
const actionError = ref("")
const expandedRunId = ref<string | null>(null)

const statusLabels: Record<AgentRun["status"], string> = {
  RUNNING: "运行中",
  WAITING_APPROVAL: "等待审批",
  COMPLETED: "已完成",
  BUDGET_EXCEEDED: "超出步数",
  FAILED: "已失败",
}

const pendingRuns = computed(() =>
  (runsQuery.data.value ?? []).filter((run) => run.status === "WAITING_APPROVAL"),
)

const approveMutation = useMutation({
  mutationFn: ({ runId, decision }: { runId: string; decision: "approve" | "reject" }) =>
    approveAgentRun(runId, decision),
  onSuccess: () => {
    actionError.value = ""
    void queryClient.invalidateQueries({ queryKey: ["growth", "agent-runs"] })
  },
  onError: (error) => {
    actionError.value = error instanceof Error ? error.message : "审批失败"
  },
})

function draftText(run: AgentRun): string {
  const draft = run.steps.find((step) => step.tool_name === "draft_outreach")
  const output = draft?.output
  return typeof output?.english_draft === "string" ? output.english_draft : ""
}

function toggle(runId: string): void {
  expandedRunId.value = expandedRunId.value === runId ? null : runId
}
</script>

<template>
  <section class="agent-approvals">
    <header class="agent-approvals__header">
      <h1>Agent 审批</h1>
      <p>待审批 {{ pendingRuns.length }} 个发送</p>
    </header>

    <p v-if="actionError" class="agent-approvals__error">{{ actionError }}</p>
    <p v-if="runsQuery.isError.value" class="agent-approvals__error">
      加载失败：{{ runsQuery.error.value?.message }}
    </p>
    <p v-if="runsQuery.isLoading.value" class="agent-approvals__empty">加载中…</p>

    <div v-else class="agent-approvals__list">
      <article
        v-for="run in runsQuery.data.value ?? []"
        :key="run.id"
        class="agent-approvals__run"
      >
        <button class="agent-approvals__toggle" type="button" @click="toggle(run.id)">
          <span>{{ statusLabels[run.status] }}</span>
          <strong>{{ run.goal }}</strong>
          <small>{{ new Date(run.created_at).toLocaleString() }}</small>
        </button>

        <div v-if="expandedRunId === run.id" class="agent-approvals__detail">
          <div v-if="draftText(run)" class="agent-approvals__draft">
            <h3>开发信草稿</h3>
            <p>{{ draftText(run) }}</p>
          </div>

          <ol class="agent-approvals__steps">
            <li v-for="step in run.steps" :key="step.index" class="agent-approvals__step">
              <span class="agent-approvals__step-name">{{ step.tool_name }}</span>
              <span class="agent-approvals__step-outcome">{{ step.outcome }}</span>
              <p v-if="step.reasoning">{{ step.reasoning }}</p>
              <p v-if="step.error" class="agent-approvals__error">{{ step.error }}</p>
            </li>
          </ol>

          <div v-if="run.status === 'WAITING_APPROVAL'" class="agent-approvals__actions">
            <button
              type="button"
              class="agent-approvals__approve"
              :disabled="approveMutation.isPending.value"
              @click="approveMutation.mutate({ runId: run.id, decision: 'approve' })"
            >
              批准发送
            </button>
            <button
              type="button"
              class="agent-approvals__reject"
              :disabled="approveMutation.isPending.value"
              @click="approveMutation.mutate({ runId: run.id, decision: 'reject' })"
            >
              拒绝
            </button>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.agent-approvals {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px;
}
.agent-approvals__header h1 {
  margin: 0 0 4px;
}
.agent-approvals__header p {
  margin: 0;
  color: #64748b;
}
.agent-approvals__error {
  color: #b91c1c;
}
.agent-approvals__empty {
  color: #64748b;
}
.agent-approvals__list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}
.agent-approvals__run {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}
.agent-approvals__toggle {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 14px 16px;
  border: 0;
  background: #fff;
  text-align: left;
  cursor: pointer;
}
.agent-approvals__toggle span {
  padding: 2px 8px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
}
.agent-approvals__toggle small {
  margin-left: auto;
  color: #94a3b8;
}
.agent-approvals__detail {
  padding: 0 16px 16px;
}
.agent-approvals__draft {
  padding: 12px;
  border-radius: 8px;
  background: #f8fafc;
}
.agent-approvals__draft h3 {
  margin: 0 0 8px;
  font-size: 14px;
}
.agent-approvals__steps {
  margin: 12px 0;
  padding-left: 20px;
}
.agent-approvals__step {
  margin-bottom: 10px;
}
.agent-approvals__step-name {
  font-weight: 600;
}
.agent-approvals__step-outcome {
  margin-left: 8px;
  color: #64748b;
  font-size: 12px;
}
.agent-approvals__actions {
  display: flex;
  gap: 8px;
}
.agent-approvals__approve,
.agent-approvals__reject {
  padding: 8px 14px;
  border: 0;
  border-radius: 8px;
  cursor: pointer;
}
.agent-approvals__approve {
  background: #005ba8;
  color: #fff;
}
.agent-approvals__reject {
  background: #fee2e2;
  color: #b91c1c;
}
</style>
