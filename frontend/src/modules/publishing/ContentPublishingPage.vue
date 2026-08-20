<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, ref } from "vue"

import { apiRequest } from "../../api/client"
import { currentUserQueryOptions } from "../auth/auth"
import ContentReviewDialog from "../content/ContentReviewDialog.vue"
import { getCursorPage, listMasterContents, listPlatformContents, listPlatforms, type CursorPage, type MasterContent, type PlatformContent } from "../content/api"
import { contentWorkflowStage, type ContentWorkflowStage, type PublishStatus } from "./contentWorkflow"

type PublishTask = {
  id: string
  platform_content_id: string
  social_account_id: string
  connector_code: string
  status: Exclude<PublishStatus, null>
  provider_submission_id: string | null
}
type ReviewItem = MasterContent | PlatformContent
type WorkflowItem = {
  id: string
  item: ReviewItem
  kind: "master" | "platform"
  stage: ContentWorkflowStage
  task: PublishTask | null
}

const labels: Record<ContentWorkflowStage, string> = {
  PREPARE: "准备发布", AI_DRAFT: "AI 草稿", REVIEW: "待人工审核", SCHEDULED: "已排期",
  SUBMITTED: "已提交", PUBLISHED: "已发布", NEEDS_ATTENTION: "需要处理",
}
const stages = Object.keys(labels) as ContentWorkflowStage[]
const activeStage = ref<ContentWorkflowStage>("REVIEW")
const reviewing = ref<WorkflowItem | null>(null)
const tabRefs = ref<HTMLButtonElement[]>([])
const queryClient = useQueryClient()

async function readAllPages<T>(first: Promise<CursorPage<T>>, exactPath: string): Promise<T[]> {
  const results: T[] = []
  const visited = new Set<string>()
  let page = await first
  while (true) {
    results.push(...page.results)
    if (!page.next || visited.has(page.next)) return results
    visited.add(page.next)
    page = await getCursorPage<T>(page.next, exactPath)
  }
}

const masterQuery = useQuery({ queryKey: ["publishing-workspace", "masters"], queryFn: () => readAllPages(listMasterContents({ page_size: 50 }), "/api/v1/master-contents"), retry: false })
const platformQuery = useQuery({ queryKey: ["publishing-workspace", "platforms-content"], queryFn: () => readAllPages(listPlatformContents({ page_size: 50 }), "/api/v1/platform-contents"), retry: false })
const tasksQuery = useQuery({
  queryKey: ["publishing-workspace", "tasks"],
  queryFn: async () => readAllPages(
    apiRequest<CursorPage<PublishTask>>("/api/v1/publish-tasks?page_size=50").then(page => page ?? { next: null, previous: null, results: [] }),
    "/api/v1/publish-tasks",
  ),
  retry: false,
})
const platformDefinitionsQuery = useQuery({ queryKey: ["content", "platforms"], queryFn: listPlatforms, retry: false })
const currentUserQuery = useQuery(currentUserQueryOptions())

const workflowItems = computed<WorkflowItem[]>(() => {
  const tasksByContentId = new Map<string, PublishTask[]>()
  for (const task of tasksQuery.data.value ?? []) {
    tasksByContentId.set(task.platform_content_id, [...(tasksByContentId.get(task.platform_content_id) ?? []), task])
  }
  const masterItems = (masterQuery.data.value ?? []).map(item => ({
    id: `master-${item.id}`, item, kind: "master" as const,
    stage: contentWorkflowStage({ contentStatus: item.status, publishStatus: null }), task: null,
  }))
  const platformItems = (platformQuery.data.value ?? []).flatMap(item => {
    const tasks = tasksByContentId.get(item.id) ?? []
    if (!tasks.length) return [{ id: `platform-${item.id}`, item, kind: "platform" as const, task: null,
      stage: contentWorkflowStage({ contentStatus: item.status, publishStatus: null }) }]
    return tasks.map(task => ({ id: `platform-${item.id}-task-${task.id}`, item, kind: "platform" as const, task,
      stage: contentWorkflowStage({ contentStatus: item.status, publishStatus: task.status }) }))
  })
  return [...masterItems, ...platformItems]
})
const counts = computed(() => Object.fromEntries(stages.map(stage => [stage, workflowItems.value.filter(item => item.stage === stage).length])))
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const workflowReadFailed = computed(() => masterQuery.isError.value || platformQuery.isError.value || tasksQuery.isError.value)

function itemsFor(stage: ContentWorkflowStage): WorkflowItem[] {
  return workflowItems.value.filter(item => item.stage === stage)
}

function platformName(item: WorkflowItem): string {
  if (item.kind === "master") return "主内容"
  const code = item.item.payload.platform_code
  return platformDefinitionsQuery.data.value?.find(platform => platform.code === code)?.name ?? code
}

function deliveryFact(item: WorkflowItem): string {
  if (!item.task) return item.kind === "platform" && item.item.publish_package_id ? "发布包已准备，尚未提交平台" : "尚未准备发布"
  switch (item.task.status) {
    case "SUBMISSION_UNKNOWN": return "平台提交状态待确认；请勿重复发布"
    case "FAILED": return "平台发布失败；请人工检查后处理"
    case "CANCELED": return "发布任务已取消；尚未发布"
    case "SUCCEEDED": return "平台已确认发布"
    case "SCHEDULED": return "已排期，尚未提交平台"
    case "QUEUED":
    case "RUNNING": return "正在等待平台处理；尚未确认发布"
    case "SUBMITTED": break
    default: return "发布状态未知；请人工核对"
  }
  const connector = item.task.connector_code.toUpperCase()
  if (connector.includes("BUFFER")) return "通过 Buffer 提交；请以平台回执为准"
  if (connector.includes("OFFICIAL")) return "通过官方 API 提交；请以平台回执为准"
  return "手工导出或待人工提交；导出不代表已发布"
}

function activateStage(stage: ContentWorkflowStage, focus = false): void {
  activeStage.value = stage
  if (focus) void nextTick(() => tabRefs.value[stages.indexOf(stage)]?.focus())
}

function onTabKeydown(event: KeyboardEvent, index: number): void {
  const target = event.key === "ArrowRight" ? (index + 1) % stages.length
    : event.key === "ArrowLeft" ? (index - 1 + stages.length) % stages.length
      : event.key === "Home" ? 0 : event.key === "End" ? stages.length - 1 : -1
  if (target < 0) return
  event.preventDefault()
  activateStage(stages[target], true)
}

async function refreshWorkspace(): Promise<void> {
  reviewing.value = null
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["publishing-workspace", "masters"] }),
    queryClient.invalidateQueries({ queryKey: ["publishing-workspace", "platforms-content"] }),
    queryClient.invalidateQueries({ queryKey: ["publishing-workspace", "tasks"] }),
  ])
}
</script>

<template>
  <section class="content-area page-stack publishing-workspace">
    <header class="workspace-header">
      <div class="workspace-header-copy">
        <p class="eyebrow">内容工作台</p>
        <h1>内容与发布</h1>
        <p class="workspace-description">按下一步结果管理素材、草稿、审核与发布。预览或导出不是发布；只有平台确认的回执才会显示为“已发布”。</p>
      </div>
    </header>

    <section v-if="workflowReadFailed" class="form-error" role="alert">
      <p>内容或发布状态暂时无法读取；不会将旧缓存或空白当作当前状态。</p>
      <button type="button" class="button button-secondary" @click="refreshWorkspace">重新读取内容和发布状态</button>
    </section>

    <template v-else>
      <section class="workflow-tabs" aria-label="内容发布状态">
        <div role="tablist" aria-label="内容发布阶段">
          <button v-for="(stage, index) in stages" :id="`publishing-tab-${stage}`" :key="stage" :ref="element => { if (element) tabRefs[index] = element as HTMLButtonElement }" type="button" role="tab" :tabindex="activeStage === stage ? 0 : -1" :aria-selected="activeStage === stage" :aria-controls="`publishing-panel-${stage}`" :class="{ active: activeStage === stage }" @click="activateStage(stage)" @keydown="onTabKeydown($event, index)">
            {{ labels[stage] }} <span>{{ counts[stage] }}</span>
          </button>
        </div>
      </section>

      <section v-for="stage in stages" :id="`publishing-panel-${stage}`" :key="stage" class="outcome-list" role="tabpanel" :aria-labelledby="`publishing-tab-${stage}`" :aria-label="labels[stage]" :hidden="activeStage !== stage">
        <template v-if="itemsFor(stage).length">
          <article v-for="entry in itemsFor(stage)" :key="entry.id" class="outcome-card">
            <div>
              <p class="eyebrow">{{ platformName(entry) }} · {{ entry.item.status }}</p>
              <h2>{{ entry.item.payload.title }}</h2>
              <p>{{ deliveryFact(entry) }}</p>
              <p v-if="entry.task" class="account-id">账号：{{ entry.task.social_account_id }}</p>
              <p v-if="entry.task?.provider_submission_id" class="submission-id">提交编号：{{ entry.task.provider_submission_id }}</p>
            </div>
            <button type="button" class="button button-secondary" :aria-label="`查看内容：${entry.item.payload.title}`" @click="reviewing = entry">查看内容</button>
          </article>
        </template>
        <section v-else class="empty-state"><div class="empty-state-icon">○</div><div><h2>{{ labels[stage] }}暂无内容</h2><p>切换状态查看其他内容。系统不会把未知提交或手工导出误报为已发布。</p></div></section>
      </section>

      <ContentReviewDialog
        v-if="reviewing"
        :item="reviewing.item"
        :kind="reviewing.kind"
        :permissions="permissions"
        :current-head="reviewing.item.is_current_head"
        :platforms="platformDefinitionsQuery.data.value ?? []"
        @close="reviewing = null"
        @updated="refreshWorkspace"
        @platform-generated="refreshWorkspace"
        @conflict="reviewing = null"
      />
    </template>
  </section>
</template>

<style scoped>
.publishing-workspace{gap:20px}.workflow-tabs{overflow:auto;border-bottom:1px solid var(--sg-line)}[role="tablist"]{display:flex;min-width:max-content;gap:4px}[role="tab"]{border:0;border-bottom:3px solid transparent;background:transparent;padding:10px 12px;color:var(--sg-muted);font-weight:750;cursor:pointer}[role="tab"].active{border-color:var(--sg-brand);color:var(--sg-brand-strong)}[role="tab"] span{margin-left:5px;border-radius:999px;background:var(--sg-brand-soft);padding:2px 7px;font-size:.78rem}.outcome-list{display:grid;gap:12px}.outcome-list[hidden]{display:none}.outcome-card{display:flex;align-items:center;justify-content:space-between;gap:20px;border:1px solid var(--sg-line);border-radius:var(--sg-radius-md);background:var(--sg-surface);padding:20px;box-shadow:var(--sg-shadow-sm)}.outcome-card h2,.outcome-card p{margin:0}.outcome-card h2{font-size:1.08rem}.outcome-card p:not(.eyebrow){margin-top:7px;color:var(--sg-muted);line-height:1.5}.submission-id{font-family:ui-monospace,monospace;font-size:.8rem}@media(max-width:560px){.outcome-card{align-items:stretch;flex-direction:column}.outcome-card .button{width:100%}}
</style>
