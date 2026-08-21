<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import { ApiError } from "../../api/client"
import AppIcon from "../../shared/components/AppIcon.vue"
import OperationModal from "../../shared/components/OperationModal.vue"
import {
  getPublishMonitor,
  publishingMonitorKeys,
  reconcilePublishTask,
  resolvePublishTask,
  retryPublishTask,
  type PublishMonitorGroup,
  type PublishMonitorTask,
  type PublishTask,
} from "./api"
import {
  canShowConfirmNotPublished,
  isNativeBufferPostId,
  monitoringGroup,
  monitoringStatusLabel,
} from "./publishMonitoring"

const props = defineProps<{ organizationId: string }>()

type Filter = "ALL" | Exclude<PublishMonitorGroup, "WAITING">
type Dialog = "RETRY" | "CONFIRM_PUBLISHED" | "CONFIRM_NOT_PUBLISHED" | null

const queryClient = useQueryClient()
const activeFilter = ref<Filter>("ALL")
const activeTask = ref<PublishTask | null>(null)
const dialog = ref<Dialog>(null)
const busyTaskId = ref<string | null>(null)
const operationMessage = ref("")
const operationError = ref("")
const providerPostId = ref("")
const noPostConfirmed = ref(false)
const expandedTasks = ref(new Set<string>())

const tasksQuery = useQuery({
  queryKey: computed(() => [
    ...publishingMonitorKeys.tasks,
    props.organizationId,
    activeFilter.value,
  ]),
  queryFn: () => getPublishMonitor(
    activeFilter.value === "ALL" ? undefined : activeFilter.value,
  ),
  retry: false,
  refetchInterval: query => (
    document.visibilityState === "visible"
    && (((query.state.data as { summary?: { waiting_count: number; provider_pending_count: number } } | undefined)?.summary?.waiting_count ?? 0) > 0
      || ((query.state.data as { summary?: { waiting_count: number; provider_pending_count: number } } | undefined)?.summary?.provider_pending_count ?? 0) > 0)
      ? 30_000
      : false
  ),
  refetchIntervalInBackground: false,
})
const tasks = computed(() => tasksQuery.data.value?.results ?? [])
const readFailed = computed(() => tasksQuery.isError.value)
const isLoading = computed(() => tasksQuery.isPending.value)
const summaryCounts = computed(() => ({
  ATTENTION: tasksQuery.data.value?.summary?.attention_count ?? 0,
  PROVIDER: tasksQuery.data.value?.summary?.provider_pending_count ?? 0,
  FAILED: tasksQuery.data.value?.summary?.failed_count ?? 0,
  COMPLETED: tasksQuery.data.value?.summary?.today_succeeded_count ?? 0,
}))
const visibleTasks = computed(() => tasks.value)
const nativePostIdValid = computed(() => isNativeBufferPostId(providerPostId.value))

const summaryCards: Array<{ id: Exclude<Filter, "ALL">; label: string; icon: "inbox" | "calendar-clock" | "send" | "circle-check" }> = [
  { id: "ATTENTION", label: "需要人工处理", icon: "inbox" },
  { id: "PROVIDER", label: "等待 Provider 确认", icon: "calendar-clock" },
  { id: "FAILED", label: "明确失败", icon: "send" },
  { id: "COMPLETED", label: "今日发布成功", icon: "circle-check" },
]

const reasonLabels: Record<string, string> = {
  STATUS_NOT_RETRYABLE: "当前状态不能普通重试。",
  STATUS_NOT_RECONCILABLE: "当前状态不需要查询 Buffer。",
  STATUS_NOT_RESOLVABLE: "当前证据不足，不能人工结束任务。",
  RECONCILIATION_WINDOW_ACTIVE: "Buffer 查询窗口尚未结束。",
  RECONCILIATION_EVIDENCE_REQUIRED: "还没有满足人工处理要求的对账证据。",
  PROVIDER_POST_KNOWN: "系统已记录 Provider Post ID，需先完成远端核验。",
}

function formatDate(value: string | null): string {
  if (!value) return "尚未发生"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "时间不可用"
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date)
}

function titleFor(task: PublishMonitorTask): string {
  return task.content_title || "未命名发布内容"
}

function bodyFor(task: PublishMonitorTask): string {
  return task.content_excerpt || "当前内容摘要不可用。"
}

function nextAction(task: PublishTask): string {
  switch (task.status) {
    case "SCHEDULED": return "等待排期时间，系统不会提前提交。"
    case "QUEUED": return "等待队列执行，无需重复操作。"
    case "RUNNING": return "等待 Provider 返回结果，请勿重复发布。"
    case "SUBMITTED": return "等待系统确认 Buffer 最终发布状态。"
    case "SUBMISSION_UNKNOWN": return "系统将安全对账；可用时可手动查询 Buffer 状态。"
    case "NEEDS_ATTENTION": return "请按服务端提供的可用操作核验结果。"
    case "FAILED": return task.allowed_actions.retry.allowed
      ? "检查安全错误信息后，可人工确认是否重试。"
      : "当前不可重试，请按不可用原因补充条件。"
    case "SUCCEEDED": return "发布已确认，无需继续处理。"
    case "CANCELED": return "任务已取消，不会自动重新发布。"
  }
}

function safeError(task: PublishTask): string {
  const code = task.reconciliation_error_code || safeErrorCode(task.last_error)
  if (!code) return "无"
  const labels: Record<string, string> = {
    RATE_LIMITED: "Provider 请求过于频繁，系统将按安全时间重试。",
    BUFFER_PROVIDER_UNAVAILABLE: "Buffer 暂时不可用，请稍后再查询。",
    BUFFER_RECONCILIATION_AMBIGUOUS: "发现多个可能的帖子，无法自动确认。",
    BUFFER_POST_MISMATCH: "查询到的帖子与当前渠道或平台不一致。",
    BUFFER_POST_NOT_FOUND: "当前查询没有找到对应帖子。",
    MANUALLY_CLOSED_NO_POST: "已由人工确认没有发布。",
  }
  return labels[code] ?? "发布服务返回了安全错误，请按可用操作处理。"
}

function safeErrorCode(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return ""
  const code = (value as Record<string, unknown>).code
  return typeof code === "string" && /^[A-Z0-9_]{1,80}$/.test(code) ? code : ""
}

function reasonFor(task: PublishTask): string[] {
  return Object.values(task.allowed_actions)
    .filter(action => !action.allowed && action.reason_code)
    .map(action => reasonLabels[action.reason_code!] ?? "服务端判定当前操作不可用。")
    .filter((reason, index, all) => all.indexOf(reason) === index)
}

function toggleExpanded(taskId: string): void {
  const next = new Set(expandedTasks.value)
  if (next.has(taskId)) next.delete(taskId)
  else next.add(taskId)
  expandedTasks.value = next
}

function openDialog(task: PublishTask, nextDialog: Exclude<Dialog, null>): void {
  activeTask.value = task
  dialog.value = nextDialog
  operationError.value = ""
  providerPostId.value = ""
  noPostConfirmed.value = false
}

function closeDialog(): void {
  dialog.value = null
  activeTask.value = null
  providerPostId.value = ""
  noPostConfirmed.value = false
}

async function refreshAll(): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: publishingMonitorKeys.tasks })
}

function safeOperationError(error: unknown): string {
  if (error instanceof ApiError) {
    return [error.userMessage, error.recoveryAction].filter(Boolean).join(" ")
  }
  return "操作未能完成，请刷新后重试。"
}

async function runReconcile(task: PublishTask): Promise<void> {
  busyTaskId.value = task.id
  operationError.value = ""
  operationMessage.value = ""
  try {
    const updated = await reconcilePublishTask(task.id)
    operationMessage.value = ["SUCCEEDED", "FAILED"].includes(updated.status)
      ? "Buffer 状态已更新。"
      : "等待下一次确认"
    await refreshAll()
  } catch (error) {
    operationError.value = safeOperationError(error)
  } finally {
    busyTaskId.value = null
  }
}

async function submitDialog(): Promise<void> {
  const task = activeTask.value
  if (!task || !dialog.value) return
  busyTaskId.value = task.id
  operationError.value = ""
  operationMessage.value = ""
  try {
    if (dialog.value === "RETRY") await retryPublishTask(task.id)
    if (dialog.value === "CONFIRM_PUBLISHED") {
      if (!nativePostIdValid.value) return
      await resolvePublishTask(task.id, {
        resolution: "CONFIRM_PUBLISHED",
        provider_post_id: providerPostId.value.trim(),
      })
    }
    if (dialog.value === "CONFIRM_NOT_PUBLISHED") {
      if (!noPostConfirmed.value || !canShowConfirmNotPublished(task)) return
      await resolvePublishTask(task.id, { resolution: "CONFIRM_NOT_PUBLISHED" })
    }
    operationMessage.value = dialog.value === "RETRY"
      ? "发布任务已重新进入执行流程。"
      : "人工处理结果已由服务端验证并记录。"
    closeDialog()
    await refreshAll()
  } catch (error) {
    operationError.value = safeOperationError(error)
  } finally {
    busyTaskId.value = null
  }
}
</script>

<template>
  <section class="publish-monitor" aria-labelledby="publish-monitor-title">
    <header class="monitor-header">
      <div class="monitor-heading">
        <span class="monitor-icon"><AppIcon name="share-2" :size="22" /></span>
        <div>
          <h2 id="publish-monitor-title">发布监控</h2>
          <p>只突出需要处理和等待确认的任务，不会自动对账或重新发布。</p>
        </div>
      </div>
      <button class="button button-secondary refresh-button" type="button" :disabled="tasksQuery.isFetching.value" @click="refreshAll">
        刷新状态
      </button>
    </header>

    <div class="summary-grid" aria-label="发布状态摘要">
      <button
        v-for="card in summaryCards"
        :key="card.id"
        type="button"
        class="summary-card"
        :class="[`summary-${card.id.toLowerCase()}`, { active: activeFilter === card.id }]"
        :aria-pressed="activeFilter === card.id"
        :aria-label="`${card.label} ${summaryCounts[card.id]}`"
        @click="activeFilter = activeFilter === card.id ? 'ALL' : card.id"
      >
        <AppIcon :name="card.icon" :size="20" />
        <span>{{ card.label }}</span>
        <strong>{{ summaryCounts[card.id] }}</strong>
      </button>
    </div>

    <p v-if="operationMessage" class="operation-message" role="status">{{ operationMessage }}</p>
    <p v-if="operationError" class="form-error" role="alert">{{ operationError }}</p>

    <section v-if="readFailed" class="monitor-empty" role="alert">
      <h3>暂时无法读取发布任务</h3>
      <p>页面不会把旧缓存或空白结果当作当前状态，请稍后刷新。</p>
      <button class="button button-secondary" type="button" @click="refreshAll">重新读取</button>
    </section>
    <section v-else-if="isLoading" class="monitor-empty" aria-live="polite">
      <h3>正在读取发布状态</h3>
      <p>系统正在汇总任务、渠道和内容信息。</p>
    </section>
    <section v-else-if="!visibleTasks.length" class="monitor-empty">
      <h3>{{ activeFilter === "ALL" ? "目前没有发布任务" : "此分类目前没有任务" }}</h3>
      <p>有真实发布任务后，这里会显示服务端确认的状态和可用操作。</p>
    </section>
    <div v-else class="task-list">
      <article v-for="task in visibleTasks" :key="task.id" class="task-card" :class="`task-${monitoringGroup(task.status).toLowerCase()}`">
        <div class="task-main">
          <div class="task-platform-row">
            <span class="platform-mark" aria-hidden="true">{{ task.platform_name?.slice(0, 1) ?? "渠" }}</span>
            <div>
              <strong>{{ task.platform_name || "未知平台" }}</strong>
              <span>{{ task.social_account_display_name || "渠道名称不可用" }}</span>
            </div>
            <span class="task-status">{{ monitoringStatusLabel(task.status) }}</span>
          </div>

          <h3>{{ titleFor(task) }}</h3>
          <p class="task-copy" :class="{ expanded: expandedTasks.has(task.id) }">{{ bodyFor(task) }}</p>
          <button class="expand-button" type="button" @click="toggleExpanded(task.id)">
            {{ expandedTasks.has(task.id) ? "收起正文" : "展开正文" }}
          </button>

          <dl class="task-timeline">
            <div><dt>排期时间</dt><dd>{{ formatDate(task.scheduled_at) }}</dd></div>
            <div><dt>提交时间</dt><dd>{{ formatDate(task.provider_call_started_at) }}</dd></div>
            <div><dt>最近对账</dt><dd>{{ formatDate(task.last_reconciled_at) }}</dd></div>
          </dl>

          <div class="task-guidance">
            <p><strong>下一步建议</strong>{{ nextAction(task) }}</p>
            <p v-if="safeError(task) !== '无'"><strong>安全错误信息</strong>{{ safeError(task) }}</p>
            <p v-if="task.provider_submission_id"><strong>Buffer Post ID</strong>{{ task.provider_submission_id }}</p>
          </div>
        </div>

        <div class="task-actions" aria-label="可用操作">
          <button
            v-if="task.allowed_actions.retry.allowed"
            class="button button-secondary"
            type="button"
            :disabled="busyTaskId === task.id"
            @click="openDialog(task, 'RETRY')"
          >
            重试发布
          </button>
          <button
            v-if="task.allowed_actions.reconcile.allowed"
            class="button button-primary"
            type="button"
            :disabled="busyTaskId === task.id"
            @click="runReconcile(task)"
          >
            查询 Buffer 状态
          </button>
          <button
            v-if="task.allowed_actions.confirm_published.allowed"
            class="button button-primary"
            type="button"
            :disabled="busyTaskId === task.id"
            @click="openDialog(task, 'CONFIRM_PUBLISHED')"
          >
            确认已经发布
          </button>
          <button
            v-if="canShowConfirmNotPublished(task)"
            class="button button-danger"
            type="button"
            :disabled="busyTaskId === task.id"
            @click="openDialog(task, 'CONFIRM_NOT_PUBLISHED')"
          >
            确认没有发布
          </button>
        </div>

        <details v-if="reasonFor(task).length" class="unavailable-reasons">
          <summary>查看当前不可用操作的原因</summary>
          <ul><li v-for="reason in reasonFor(task)" :key="reason">{{ reason }}</li></ul>
        </details>
      </article>
    </div>

    <OperationModal v-if="dialog === 'RETRY'" title="确认重试发布" title-id="retry-publish-title" @close="closeDialog">
      <p>这会重新执行当前发布任务。请先确认 Provider 尚未接收该内容。</p>
      <p v-if="operationError" class="form-error" role="alert">{{ operationError }}</p>
      <div class="modal-actions">
        <button class="button button-secondary" type="button" :disabled="Boolean(busyTaskId)" @click="closeDialog">取消</button>
        <button class="button button-primary" type="button" :disabled="Boolean(busyTaskId)" @click="submitDialog">确认重试</button>
      </div>
    </OperationModal>

    <OperationModal v-if="dialog === 'CONFIRM_PUBLISHED'" title="验证 Buffer 发布结果" title-id="confirm-published-title" @close="closeDialog">
      <p>请输入原生 Buffer Post ID。系统会先向 Buffer 查询并验证，不会由前端直接改成成功。</p>
      <label for="buffer-post-id">Buffer Post ID</label>
      <input id="buffer-post-id" v-model="providerPostId" autocomplete="off" maxlength="255">
      <p v-if="providerPostId && !nativePostIdValid" class="input-hint input-error">请输入原生 Buffer Post ID，不要粘贴链接。</p>
      <p v-if="operationError" class="form-error" role="alert">{{ operationError }}</p>
      <div class="modal-actions">
        <button class="button button-secondary" type="button" :disabled="Boolean(busyTaskId)" @click="closeDialog">取消</button>
        <button class="button button-primary" type="button" :disabled="Boolean(busyTaskId) || !nativePostIdValid" @click="submitDialog">查询并确认发布</button>
      </div>
    </OperationModal>

    <OperationModal v-if="dialog === 'CONFIRM_NOT_PUBLISHED' && activeTask" title="确认 Buffer 没有发布" title-id="confirm-not-published-title" @close="closeDialog">
      <p>只有服务端确认查询窗口已结束且严格零匹配时，才能关闭任务并释放发布锁。</p>
      <dl class="evidence-grid">
        <div><dt>候选帖子数量</dt><dd>{{ activeTask.resolution_evidence.candidate_count }}</dd></div>
        <div><dt>查询窗口已结束</dt><dd>{{ activeTask.resolution_evidence.query_window_ended ? "是" : "否" }}</dd></div>
        <div><dt>查询被截断</dt><dd>{{ activeTask.resolution_evidence.truncated === false ? "否" : activeTask.resolution_evidence.truncated === true ? "是" : "未知" }}</dd></div>
        <div><dt>证据快照有效</dt><dd>{{ activeTask.resolution_evidence.snapshot_valid ? "是" : "否" }}</dd></div>
        <div><dt>观察时间</dt><dd>{{ formatDate(activeTask.resolution_evidence.observed_at) }}</dd></div>
        <div><dt>查询窗口结束</dt><dd>{{ formatDate(activeTask.resolution_evidence.query_window_end) }}</dd></div>
      </dl>
      <label class="confirm-check">
        <input v-model="noPostConfirmed" type="checkbox">
        <span>我确认 Buffer 查询窗口已结束且没有找到对应帖子。</span>
      </label>
      <p v-if="operationError" class="form-error" role="alert">{{ operationError }}</p>
      <div class="modal-actions">
        <button class="button button-secondary" type="button" :disabled="Boolean(busyTaskId)" @click="closeDialog">取消</button>
        <button class="button button-danger" type="button" :disabled="Boolean(busyTaskId) || !noPostConfirmed" @click="submitDialog">确认关闭任务</button>
      </div>
    </OperationModal>
  </section>
</template>

<style scoped>
.publish-monitor { display: grid; gap: 18px; }
.monitor-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.monitor-heading { display: flex; align-items: center; gap: 12px; }
.monitor-heading h2, .monitor-heading p { margin: 0; }
.monitor-heading h2 { color: var(--sg-ink); font-size: 1.16rem; }
.monitor-heading p { margin-top: 4px; color: var(--sg-muted); font-size: .88rem; }
.monitor-icon { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 12px; background: var(--sg-brand-soft); color: var(--sg-brand-strong); }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.summary-card { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 9px; min-height: 70px; border: 1px solid var(--sg-line); border-radius: var(--sg-radius-md); background: var(--sg-surface); padding: 12px 14px; color: var(--sg-muted); text-align: left; cursor: pointer; }
.summary-card strong { color: var(--sg-ink); font-size: 1.25rem; font-variant-numeric: tabular-nums; }
.summary-card.active { border-color: #79b9f5; background: var(--sg-brand-soft); color: var(--sg-brand-strong); }
.summary-attention svg { color: #c76b15; }
.summary-provider svg { color: var(--sg-brand); }
.summary-failed svg { color: #c44343; }
.summary-completed svg { color: #15805d; }
.operation-message { margin: 0; border: 1px solid #a8d9c6; border-radius: 10px; background: #effaf5; padding: 10px 12px; color: #126649; }
.monitor-empty { display: grid; justify-items: start; gap: 7px; border: 1px dashed #b9d7f2; border-radius: var(--sg-radius-md); background: #f7fbff; padding: 28px; }
.monitor-empty h3, .monitor-empty p { margin: 0; }
.monitor-empty p { color: var(--sg-muted); }
.task-list { display: grid; gap: 12px; }
.task-card { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px 20px; border: 1px solid var(--sg-line); border-left: 4px solid #9dc7ed; border-radius: var(--sg-radius-md); background: var(--sg-surface); padding: 18px; box-shadow: 0 4px 16px rgb(25 71 112 / 5%); }
.task-attention { border-left-color: #e28a31; }
.task-provider, .task-waiting { border-left-color: #4d9de3; }
.task-failed { border-left-color: #d65757; }
.task-completed { border-left-color: #35a67c; }
.task-main { min-width: 0; }
.task-platform-row { display: flex; align-items: center; gap: 10px; }
.task-platform-row > div { display: grid; min-width: 0; }
.task-platform-row > div span { color: var(--sg-muted); font-size: .77rem; }
.platform-mark { display: grid; flex: 0 0 auto; width: 34px; height: 34px; place-items: center; border-radius: 10px; background: var(--sg-brand-soft); color: var(--sg-brand-strong); font-weight: 800; }
.task-status { margin-left: auto; border-radius: 999px; background: #eff6fd; padding: 5px 9px; color: #246da9; font-size: .74rem; font-weight: 750; }
.task-main h3 { margin: 13px 0 0; font-size: 1rem; }
.task-copy { display: -webkit-box; overflow: hidden; margin: 6px 0 0; color: var(--sg-muted); line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.task-copy.expanded { display: block; overflow: visible; }
.expand-button { border: 0; background: transparent; padding: 5px 0; color: var(--sg-brand-strong); font-size: .78rem; font-weight: 700; cursor: pointer; }
.task-timeline { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 10px 0 0; }
.task-timeline div { border-radius: 9px; background: #f7fafd; padding: 8px 10px; }
.task-timeline dt { color: var(--sg-muted); font-size: .7rem; }
.task-timeline dd { margin: 3px 0 0; color: var(--sg-ink); font-size: .78rem; }
.task-guidance { display: grid; gap: 5px; margin-top: 10px; }
.task-guidance p { display: flex; gap: 8px; margin: 0; color: var(--sg-muted); font-size: .8rem; line-height: 1.45; }
.task-guidance strong { flex: 0 0 92px; color: var(--sg-ink); }
.task-actions { display: flex; width: 190px; align-content: start; flex-direction: column; gap: 8px; }
.task-actions:empty { display: none; }
.button-danger { border: 1px solid #dca0a0; background: #fff7f7; color: #a93636; }
.unavailable-reasons { grid-column: 1 / -1; border-top: 1px solid var(--sg-line); padding-top: 10px; color: var(--sg-muted); font-size: .78rem; }
.unavailable-reasons summary { width: fit-content; color: var(--sg-brand-strong); cursor: pointer; }
.unavailable-reasons ul { margin: 8px 0 0; padding-left: 20px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
label { display: block; margin-top: 14px; color: var(--sg-ink); font-weight: 700; }
input:not([type="checkbox"]) { width: 100%; margin-top: 6px; border: 1px solid var(--sg-line); border-radius: 9px; padding: 10px; }
.input-hint { margin: 6px 0 0; font-size: .8rem; }
.input-error { color: #a93636; }
.evidence-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.evidence-grid div { border-radius: 9px; background: #f5f9fd; padding: 9px 10px; }
.evidence-grid dt { color: var(--sg-muted); font-size: .72rem; }
.evidence-grid dd { margin: 3px 0 0; font-weight: 700; }
.confirm-check { display: flex; align-items: flex-start; gap: 8px; font-weight: 600; line-height: 1.45; }
.confirm-check input { margin-top: 3px; }

@media (max-width: 760px) {
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .task-card { grid-template-columns: 1fr; }
  .task-actions { width: 100%; }
}

@media (max-width: 480px) {
  .monitor-header { align-items: stretch; flex-direction: column; }
  .refresh-button { width: 100%; }
  .summary-grid { grid-template-columns: 1fr; }
  .summary-card { min-height: 58px; }
  .task-card { padding: 15px; }
  .task-platform-row { align-items: flex-start; flex-wrap: wrap; }
  .task-status { width: 100%; margin-left: 44px; }
  .task-timeline, .evidence-grid { grid-template-columns: 1fr; }
  .task-guidance p { flex-direction: column; gap: 2px; }
  .task-guidance strong { flex-basis: auto; }
  .modal-actions { flex-direction: column-reverse; }
  .modal-actions .button { width: 100%; }
}
</style>
