<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, ref } from "vue"

import { currentUserQueryOptions } from "../auth/auth"
import { decideProposal, directorKeys, getCockpit, type DirectorAction, type DirectorDecision } from "../director/api"
import { ordinaryDirectorError, ordinaryStatus } from "../../shared/presentation/ordinary"
import OperationModal from "../../shared/components/OperationModal.vue"
import ActivityRow from "./components/ActivityRow.vue"
import DecisionCard from "./components/DecisionCard.vue"

const queryClient = useQueryClient()
const currentUserQuery = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUserQuery.data.value?.organization.id ?? "")
const cockpitQuery = useQuery({
  queryKey: computed(() => directorKeys.cockpit(organizationId.value)),
  queryFn: ({ signal }) => getCockpit({ signal }),
  enabled: computed(() => Boolean(organizationId.value)),
  retry: false,
})

const decisions = computed(() => (cockpitQuery.data.value?.decisions ?? []).slice(0, 3))
const heading = computed(() => decisions.value.length
  ? `今天有 ${decisions.value.length} 件事需要你决定`
  : "今天没有需要你决定的事")
const busyId = ref<string | null>(null)
const notice = ref("")
const dialog = ref<{ decision: DirectorDecision; action: Exclude<DirectorAction, "APPROVE"> } | null>(null)
const reason = ref("")
const reasonError = ref("")
const reasonInput = ref<HTMLTextAreaElement | null>(null)

const mutation = useMutation({
  mutationFn: ({ decision, action, comment }: { decision: DirectorDecision; action: DirectorAction; comment: string }) => {
    busyId.value = decision.id
    return decideProposal(decision.id, { action, expected_version: decision.version, comment })
  },
  onSuccess: async () => {
    closeDialog()
    notice.value = "已提交你的决定。"
    await queryClient.invalidateQueries({ queryKey: directorKeys.cockpit(organizationId.value) })
  },
  onError: async (error) => {
    const safe = ordinaryDirectorError(error)
    notice.value = safe.message
    if (safe.refresh) await queryClient.invalidateQueries({ queryKey: directorKeys.cockpit(organizationId.value) })
  },
  onSettled: () => { busyId.value = null },
})

function decide(decision: DirectorDecision, action: DirectorAction): void {
  notice.value = ""
  if (action === "APPROVE") {
    if (window.confirm(`确认批准“${decision.title}”吗？`)) {
      mutation.mutate({ decision, action, comment: "" })
    }
    return
  }
  dialog.value = { decision, action }
  reason.value = ""
  reasonError.value = ""
}

function closeDialog(): void {
  dialog.value = null
  reason.value = ""
  reasonError.value = ""
}

function submitReason(): void {
  if (!dialog.value) return
  if (!reason.value.trim() || !/[\u3400-\u9fff]/u.test(reason.value)) {
    reasonError.value = "请用中文填写原因。"
    void nextTick(() => reasonInput.value?.focus())
    return
  }
  mutation.mutate({ ...dialog.value, comment: reason.value.trim() })
}

function statusTone(status: string): "brand" | "warning" | "neutral" {
  if (status === "RUNNING") return "brand"
  if (status === "QUEUED" || status === "RETRY_QUEUED") return "warning"
  return "neutral"
}
</script>

<template>
  <div class="page-stack dashboard-page">
    <header class="cockpit-hero">
      <div>
        <p class="eyebrow">今天</p>
        <h1 v-if="cockpitQuery.isPending.value">正在整理今天的工作</h1>
        <h1 v-else-if="cockpitQuery.isError.value">今天的工作暂时无法显示</h1>
        <h1 v-else>{{ heading }}</h1>
        <p>AI 汇总真实工作和结果，你只需要处理最重要的决定。</p>
      </div>
    </header>

    <p v-if="notice" class="dashboard-notice" role="alert">{{ notice }}</p>
    <section v-if="cockpitQuery.isPending.value" class="cockpit-card" role="status">
      正在整理需要你决定的事项、AI 工作和最近结果……
    </section>
    <section v-else-if="cockpitQuery.isError.value" class="cockpit-card cockpit-local-error" role="alert">
      <h2>今天的工作暂时没有加载成功</h2>
      <p>页面其他功能仍可使用，请稍后重新加载。</p>
      <button type="button" @click="cockpitQuery.refetch()">重新加载</button>
    </section>

    <div v-else class="cockpit-grid dashboard-cockpit-grid">
      <section class="cockpit-card cockpit-card-priority" aria-labelledby="decision-title">
        <div class="cockpit-card-heading"><div><p class="eyebrow">优先处理</p><h2 id="decision-title">需要你决定</h2></div></div>
        <p v-if="!decisions.length" class="cockpit-empty">当前没有等待你决定的事项。AI 会在需要你确认时放到这里。</p>
        <div v-else class="decision-card-list">
          <DecisionCard
            v-for="(decision, index) in decisions"
            :key="decision.id"
            :index="index + 1"
            :title="decision.title"
            :explanation="decision.explanation"
            :actions="decision.actions"
            :busy="busyId === decision.id"
            @decide="decide(decision, $event)"
          />
        </div>
      </section>

      <section class="cockpit-card" aria-labelledby="activity-title">
        <div class="cockpit-card-heading"><div><p class="eyebrow">进行中</p><h2 id="activity-title">AI 正在帮你工作</h2></div></div>
        <p v-if="!cockpitQuery.data.value?.active_work.length" class="cockpit-empty">AI 当前没有正在执行的工作。完成产品资料后，新的工作会出现在这里。</p>
        <div v-else class="activity-row-list">
          <ActivityRow
            v-for="work in cockpitQuery.data.value.active_work"
            :key="work.job_id"
            :title="work.label"
            detail="进度来自系统真实任务记录。"
            :status-label="ordinaryStatus(work.status)"
            :status-tone="statusTone(work.status)"
            :progress="work.progress_is_determinate ? work.progress : null"
          />
        </div>
      </section>

      <section class="cockpit-card cockpit-card-results" aria-labelledby="results-title">
        <div class="cockpit-card-heading"><div><p class="eyebrow">近期效果</p><h2 id="results-title">最近结果</h2></div></div>
        <p v-if="!cockpitQuery.data.value?.recent_outcomes.length" class="cockpit-empty">还没有可汇报的真实结果。开始推广后，系统会在这里汇总已记录的数据。</p>
        <ul v-else class="outcome-list">
          <li v-for="outcome in cockpitQuery.data.value.recent_outcomes" :key="`${outcome.kind}:${outcome.label}`">
            <div><span>{{ outcome.label }}</span><strong>{{ outcome.value }}</strong></div><p>{{ outcome.detail }}</p>
          </li>
        </ul>
      </section>
    </div>

    <OperationModal
      v-if="dialog"
      :title="dialog.action === 'REQUEST_ADJUSTMENT' ? '请说明需要怎样调整' : '请说明拒绝原因'"
      title-id="director-reason-title"
      @close="closeDialog"
    >
      <form class="reason-form" @submit.prevent="submitReason">
        <label for="director-reason">原因</label>
        <textarea
          id="director-reason"
          ref="reasonInput"
          v-model="reason"
          rows="5"
          maxlength="500"
          :aria-invalid="Boolean(reasonError)"
          :aria-describedby="reasonError ? 'director-reason-error' : undefined"
          @input="reasonError = ''"
        />
        <p v-if="reasonError" id="director-reason-error" class="field-error" role="alert">{{ reasonError }}</p>
        <div class="reason-actions">
          <button type="button" class="button button-quiet" :disabled="mutation.isPending.value" @click="closeDialog">取消</button>
          <button type="submit" class="button button-primary" :disabled="mutation.isPending.value">{{ mutation.isPending.value ? '正在提交' : '提交' }}</button>
        </div>
      </form>
    </OperationModal>
  </div>
</template>

<style scoped>
.dashboard-cockpit-grid { align-items: start; }
.cockpit-card-priority { grid-row: span 2; }
.decision-card-list, .activity-row-list { margin-top: 18px; }
.dashboard-notice { margin: 0; padding: 12px 16px; border-radius: 12px; background: var(--sg-brand-tint); color: var(--sg-brand-strong); }
.outcome-list { display: grid; gap: 12px; margin: 18px 0 0; padding: 0; list-style: none; }
.outcome-list li { padding: 15px; border: 1px solid var(--sg-line); border-radius: 14px; }
.outcome-list div { display: flex; justify-content: space-between; gap: 12px; }
.outcome-list strong { color: var(--sg-brand); font-size: 1.4rem; }
.outcome-list p { margin: 6px 0 0; color: var(--sg-muted); }
.reason-form { display: grid; gap: 12px; margin-top: 16px; }
.reason-form label { font-weight: 700; }
.reason-form textarea { width: 100%; resize: vertical; box-sizing: border-box; border: 1px solid var(--sg-line); border-radius: 12px; padding: 12px; font: inherit; }
.reason-form textarea:focus { outline: 3px solid var(--sg-brand-tint); border-color: var(--sg-brand); }
.field-error { margin: 0; color: var(--sg-danger, #b42318); }
.reason-actions { display: flex; justify-content: flex-end; gap: 10px; }
@media (max-width: 760px) { .cockpit-card-priority { grid-row: auto; } }
</style>
