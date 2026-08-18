<script setup lang="ts">
import { computed } from "vue"

import type { AgentRun } from "./agentApi"

const props = defineProps<{
  run: AgentRun
  statusLabel: string
  busy?: boolean
}>()

defineEmits<{
  approve: []
  reject: []
}>()

const draft = computed(() => {
  const step = props.run.steps.find((item) => item.tool_name === "draft_outreach")
  return typeof step?.output?.english_draft === "string" ? step.output.english_draft : ""
})

const pendingAction = computed(() => {
  const labels: Record<string, string> = {
    send_outreach: "发送这封开发信",
    publish_social: "发布这条社媒内容",
    schedule_social: "安排这条社媒内容",
  }
  const tool = props.run.pending_approval?.tool_name ?? ""
  return labels[tool] ?? "执行下一步操作"
})
</script>

<template>
  <article class="approval-card" role="region" :aria-label="run.goal">
    <header class="approval-card__header">
      <div>
        <span class="approval-card__status">{{ statusLabel }}</span>
        <h2>{{ run.goal }}</h2>
      </div>
      <time :datetime="run.created_at">{{ new Date(run.created_at).toLocaleString() }}</time>
    </header>

    <section v-if="run.status === 'WAITING_APPROVAL'" class="approval-card__decision">
      <p class="approval-card__prompt">是否允许 Agent {{ pendingAction }}？</p>
      <p v-if="run.pending_approval?.reasoning" class="approval-card__reason">
        {{ run.pending_approval.reasoning }}
      </p>
    </section>

    <section v-if="draft" class="approval-card__draft" aria-label="待审核内容">
      <h3>待审核草稿</h3>
      <p>{{ draft }}</p>
    </section>

    <div v-if="run.status === 'WAITING_APPROVAL'" class="approval-card__actions">
      <button type="button" class="primary" :disabled="busy" @click="$emit('approve')">批准执行</button>
      <button type="button" class="reject" :disabled="busy" @click="$emit('reject')">拒绝</button>
    </div>

    <details class="approval-card__technical">
      <summary>技术执行记录</summary>
      <dl v-if="run.pending_approval">
        <div><dt>待执行工具</dt><dd><code>{{ run.pending_approval.tool_name || "未记录" }}</code></dd></div>
        <div><dt>工具参数</dt><dd><code>{{ JSON.stringify(run.pending_approval.tool_args ?? {}) }}</code></dd></div>
      </dl>
      <ol>
        <li v-for="step in run.steps" :key="step.index">
          <strong>{{ step.tool_name || "未命名步骤" }}</strong>
          <span>{{ step.outcome }}</span>
          <p v-if="step.reasoning">{{ step.reasoning }}</p>
          <p v-if="step.error" class="error">{{ step.error }}</p>
          <code v-if="Object.keys(step.args).length">{{ JSON.stringify(step.args) }}</code>
        </li>
      </ol>
    </details>
  </article>
</template>

<style scoped>
.approval-card { display: grid; gap: 16px; border: 1px solid var(--sg-line); border-radius: 16px; background: #fff; padding: 20px; box-shadow: 0 4px 18px rgb(23 34 49 / 5%); }
.approval-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.approval-card__header h2 { margin: 8px 0 0; font-size: 1.08rem; }
.approval-card__header time { flex: 0 0 auto; color: var(--sg-muted); font-size: .74rem; }
.approval-card__status { display: inline-flex; border-radius: 999px; background: #fff3df; padding: 4px 8px; color: #8a5900; font-size: .72rem; font-weight: 850; }
.approval-card__decision { border-left: 3px solid var(--sg-accent); border-radius: 8px; background: #fff9f2; padding: 12px 14px; }
.approval-card__prompt { margin: 0; color: var(--sg-ink); font-weight: 850; }
.approval-card__reason { margin: 6px 0 0; color: var(--sg-muted); font-size: .875rem; line-height: 1.55; }
.approval-card__draft { border: 1px solid #dce8f4; border-radius: 12px; background: #f8fbff; padding: 16px; }
.approval-card__draft h3 { margin: 0 0 8px; font-size: .86rem; }
.approval-card__draft p { margin: 0; white-space: pre-wrap; line-height: 1.65; }
.approval-card__actions { display: flex; flex-wrap: wrap; gap: 9px; }
.approval-card__actions button { min-height: 42px; border: 0; border-radius: 9px; padding: 9px 16px; font: inherit; font-weight: 800; cursor: pointer; }
.approval-card__actions .primary { background: var(--sg-brand); color: #fff; }
.approval-card__actions .reject { background: #feeceb; color: #a42e25; }
.approval-card__actions button:disabled { opacity: .55; cursor: not-allowed; }
.approval-card__technical { border-top: 1px solid var(--sg-line); padding-top: 12px; color: var(--sg-muted); font-size: .78rem; }
.approval-card__technical summary { cursor: pointer; font-weight: 800; }
.approval-card__technical dl { display: grid; gap: 8px; }
.approval-card__technical dl div { display: grid; gap: 3px; }
.approval-card__technical dd { overflow-wrap: anywhere; margin: 0; }
.approval-card__technical ol { display: grid; gap: 10px; padding-left: 20px; }
.approval-card__technical li { padding-left: 4px; }
.approval-card__technical li span { margin-left: 8px; }
.approval-card__technical li p { margin: 5px 0; }
.approval-card__technical code { overflow-wrap: anywhere; white-space: pre-wrap; }
.error { color: var(--sg-danger); }
@media (max-width: 640px) { .approval-card__header { flex-direction: column; }.approval-card__actions button { flex: 1; } }
</style>
