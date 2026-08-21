<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, ref } from "vue"
import { RouterLink } from "vue-router"

import { apiRequest } from "../../api/client"
import WorkspaceHeader from "../../shared/components/WorkspaceHeader.vue"
import { currentUserQueryOptions } from "../auth/auth"
import ContentReviewDialog from "../content/ContentReviewDialog.vue"
import PublishMonitoringPanel from "./PublishMonitoringPanel.vue"
import {
  getCursorPage,
  listMasterContents,
  listPlatformContents,
  listPlatforms,
  type CursorPage,
  type MasterContent,
  type PlatformContent,
} from "../content/api"
import {
  contentWorkflowGroup,
  contentWorkflowStage,
  type ContentWorkflowGroup,
  type ContentWorkflowStage,
  type PublishStatus,
} from "./contentWorkflow"

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

const statusLabels: Record<ContentWorkflowStage, string> = {
  PREPARE: "准备发布",
  AI_DRAFT: "AI 草稿",
  REVIEW: "待人工审核",
  SCHEDULED: "已排期",
  SUBMITTED: "已提交",
  PUBLISHED: "已发布",
  NEEDS_ATTENTION: "需要处理",
}
const groups: Array<{
  id: ContentWorkflowGroup
  label: string
  stages: ContentWorkflowStage[]
}> = [
  { id: "PENDING", label: "待处理", stages: ["AI_DRAFT", "REVIEW", "NEEDS_ATTENTION"] },
  { id: "PLANNED", label: "计划中", stages: ["PREPARE", "SCHEDULED", "SUBMITTED"] },
  { id: "COMPLETED", label: "已完成", stages: ["PUBLISHED"] },
]

const activeGroup = ref<ContentWorkflowGroup>("PENDING")
const activeWorkspaceView = ref<"WORKFLOW" | "MONITOR">("WORKFLOW")
const activeDetailStage = ref<ContentWorkflowStage | null>(null)
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

const masterQuery = useQuery({
  queryKey: ["publishing-workspace", "masters"],
  queryFn: () => readAllPages(listMasterContents({ page_size: 50 }), "/api/v1/master-contents"),
  retry: false,
})
const platformQuery = useQuery({
  queryKey: ["publishing-workspace", "platforms-content"],
  queryFn: () => readAllPages(listPlatformContents({ page_size: 50 }), "/api/v1/platform-contents"),
  retry: false,
})
const tasksQuery = useQuery({
  queryKey: ["publishing-workspace", "tasks"],
  queryFn: async () => readAllPages(
    apiRequest<CursorPage<PublishTask>>("/api/v1/publish-tasks?page_size=50")
      .then(page => page ?? { next: null, previous: null, results: [] }),
    "/api/v1/publish-tasks",
  ),
  retry: false,
})
const platformDefinitionsQuery = useQuery({
  queryKey: ["content", "platforms"],
  queryFn: listPlatforms,
  retry: false,
})
const currentUserQuery = useQuery(currentUserQueryOptions())

const workflowItems = computed<WorkflowItem[]>(() => {
  const tasksByContentId = new Map<string, PublishTask[]>()
  for (const task of tasksQuery.data.value ?? []) {
    tasksByContentId.set(
      task.platform_content_id,
      [...(tasksByContentId.get(task.platform_content_id) ?? []), task],
    )
  }
  const masterItems = (masterQuery.data.value ?? []).map(item => ({
    id: "master-" + item.id,
    item,
    kind: "master" as const,
    stage: contentWorkflowStage({ contentStatus: item.status, publishStatus: null }),
    task: null,
  }))
  const platformItems = (platformQuery.data.value ?? []).flatMap(item => {
    const tasks = tasksByContentId.get(item.id) ?? []
    if (!tasks.length) {
      return [{
        id: "platform-" + item.id,
        item,
        kind: "platform" as const,
        task: null,
        stage: contentWorkflowStage({ contentStatus: item.status, publishStatus: null }),
      }]
    }
    return tasks.map(task => ({
      id: "platform-" + item.id + "-task-" + task.id,
      item,
      kind: "platform" as const,
      task,
      stage: contentWorkflowStage({ contentStatus: item.status, publishStatus: task.status }),
    }))
  })
  return [...masterItems, ...platformItems]
})

const groupCounts = computed(() => Object.fromEntries(
  groups.map(group => [
    group.id,
    workflowItems.value.filter(item => contentWorkflowGroup(item.stage) === group.id).length,
  ]),
))
const statusCounts = computed(() => Object.fromEntries(
  Object.keys(statusLabels).map(stage => [
    stage,
    workflowItems.value.filter(item => item.stage === stage).length,
  ]),
))
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const permissionSet = computed(() => new Set(permissions.value))
const isAdministrator = computed(() => currentUserQuery.data.value?.membership.role === "ADMINISTRATOR")
const workflowReadFailed = computed(() => (
  masterQuery.isError.value || platformQuery.isError.value || tasksQuery.isError.value
))

function groupDefinition(group: ContentWorkflowGroup) {
  return groups.find(candidate => candidate.id === group) ?? groups[0]
}

function itemsFor(group: ContentWorkflowGroup): WorkflowItem[] {
  return workflowItems.value.filter((item) => (
    contentWorkflowGroup(item.stage) === group
    && (!activeDetailStage.value || item.stage === activeDetailStage.value)
  ))
}

function platformName(item: WorkflowItem): string {
  if (item.kind === "master") return "主内容"
  const code = item.item.payload.platform_code
  return platformDefinitionsQuery.data.value?.find(platform => platform.code === code)?.name ?? code
}

function deliveryFact(item: WorkflowItem): string {
  if (!item.task) {
    return item.kind === "platform" && item.item.publish_package_id
      ? "发布包已准备，尚未提交平台"
      : "尚未准备发布"
  }
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

function activateGroup(group: ContentWorkflowGroup, focus = false): void {
  activeGroup.value = group
  activeDetailStage.value = null
  if (focus) {
    const index = groups.findIndex(candidate => candidate.id === group)
    void nextTick(() => tabRefs.value[index]?.focus())
  }
}

function onTabKeydown(event: KeyboardEvent, index: number): void {
  const target = event.key === "ArrowRight" ? (index + 1) % groups.length
    : event.key === "ArrowLeft" ? (index - 1 + groups.length) % groups.length
      : event.key === "Home" ? 0 : event.key === "End" ? groups.length - 1 : -1
  if (target < 0) return
  event.preventDefault()
  activateGroup(groups[target].id, true)
}

function emptyTitle(group: ContentWorkflowGroup): string {
  if (group === "PENDING") return "目前没有待处理内容"
  if (group === "PLANNED") return "目前没有计划中的内容"
  return "目前没有已完成发布"
}

function emptyMessage(group: ContentWorkflowGroup): string {
  if (group === "PENDING") return "可以从生成内容开始；有审核权限时也可直接查看待审核任务。"
  if (group === "PLANNED") return "先创建社媒计划并配置可用的平台账户，再安排提交。"
  return "已完成只统计平台确认的发布记录；导出或未知提交不会计入。"
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
    <WorkspaceHeader
      title="内容与发布"
      description="按待处理、计划中和已完成管理内容。具体状态仍保留在二级筛选和内容标签中。"
    />

    <nav class="workspace-view-switch" aria-label="内容与发布视图">
      <button
        type="button"
        :aria-pressed="activeWorkspaceView === 'WORKFLOW'"
        :class="{ active: activeWorkspaceView === 'WORKFLOW' }"
        @click="activeWorkspaceView = 'WORKFLOW'"
      >
        内容工作流
      </button>
      <button
        type="button"
        :aria-pressed="activeWorkspaceView === 'MONITOR'"
        :class="{ active: activeWorkspaceView === 'MONITOR' }"
        @click="activeWorkspaceView = 'MONITOR'"
      >
        发布监控
      </button>
    </nav>

    <template v-if="activeWorkspaceView === 'WORKFLOW'">
      <section v-if="workflowReadFailed" class="form-error" role="alert">
        <p>内容或发布状态暂时无法读取；不会将旧缓存或空白当作当前状态。</p>
        <button type="button" class="button button-secondary" @click="refreshWorkspace">重新读取内容和发布状态</button>
      </section>

      <template v-else>
      <section class="workflow-tabs" aria-label="内容发布状态">
        <div role="tablist" aria-label="内容发布主阶段">
          <button
            v-for="(group, index) in groups"
            :id="'publishing-tab-' + group.id"
            :key="group.id"
            :ref="element => { if (element) tabRefs[index] = element as HTMLButtonElement }"
            type="button"
            role="tab"
            :tabindex="activeGroup === group.id ? 0 : -1"
            :aria-selected="activeGroup === group.id"
            :aria-controls="'publishing-panel-' + group.id"
            :class="{ active: activeGroup === group.id }"
            @click="activateGroup(group.id)"
            @keydown="onTabKeydown($event, index)"
          >
            <span class="tab-label">{{ group.label }}</span>
            <span class="tab-count">{{ groupCounts[group.id] }}</span>
          </button>
        </div>
      </section>

      <section
        v-for="group in groups"
        :id="'publishing-panel-' + group.id"
        :key="group.id"
        class="outcome-panel"
        role="tabpanel"
        :aria-labelledby="'publishing-tab-' + group.id"
        :aria-label="group.label"
        :hidden="activeGroup !== group.id"
      >
        <div class="status-filters" aria-label="具体状态筛选">
          <button
            type="button"
            :class="{ active: activeDetailStage === null }"
            @click="activeDetailStage = null"
          >
            全部 {{ groupCounts[group.id] }}
          </button>
          <button
            v-for="stage in groupDefinition(group.id).stages"
            :key="stage"
            type="button"
            :class="{ active: activeDetailStage === stage }"
            @click="activeDetailStage = stage"
          >
            {{ statusLabels[stage] }} {{ statusCounts[stage] }}
          </button>
        </div>

        <div v-if="itemsFor(group.id).length" class="outcome-list">
          <article v-for="entry in itemsFor(group.id)" :key="entry.id" class="outcome-card">
            <div>
              <div class="content-meta">
                <span>{{ platformName(entry) }}</span>
                <span class="status-badge">{{ statusLabels[entry.stage] }}</span>
              </div>
              <h2>{{ entry.item.payload.title }}</h2>
              <p>{{ deliveryFact(entry) }}</p>
              <p v-if="entry.task" class="account-id">账号：{{ entry.task.social_account_id }}</p>
              <p v-if="entry.task?.provider_submission_id" class="submission-id">提交编号：{{ entry.task.provider_submission_id }}</p>
            </div>
            <button
              type="button"
              class="button button-secondary"
              :aria-label="'查看内容：' + entry.item.payload.title"
              @click="reviewing = entry"
            >
              查看内容
            </button>
          </article>
        </div>

        <section v-else class="empty-state publishing-empty">
          <div>
            <h2>{{ emptyTitle(group.id) }}</h2>
            <p>{{ emptyMessage(group.id) }}</p>
          </div>
          <div class="empty-state-actions">
            <template v-if="group.id === 'PENDING'">
              <RouterLink v-if="permissionSet.has('content.manage')" class="button button-primary" to="/promotion">生成内容</RouterLink>
              <RouterLink v-if="permissionSet.has('content.review')" class="button button-secondary" to="/missions">前往审核</RouterLink>
            </template>
            <template v-else>
              <RouterLink class="button button-primary" to="/promotion">创建社媒计划</RouterLink>
              <RouterLink v-if="isAdministrator" class="button button-secondary" to="/platform-accounts">配置平台账户</RouterLink>
            </template>
          </div>
        </section>
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
    </template>

    <PublishMonitoringPanel
      v-else-if="currentUserQuery.data.value?.organization.id"
      :organization-id="currentUserQuery.data.value.organization.id"
    />
    <section v-else class="empty-state publishing-empty">
      <div><h2>正在准备发布监控</h2><p>系统正在确认当前组织和权限边界。</p></div>
    </section>
  </section>
</template>

<style scoped>
.publishing-workspace {
  gap: 20px;
}

.workspace-view-switch {
  display: inline-flex;
  width: fit-content;
  gap: 4px;
  border: 1px solid var(--sg-line);
  border-radius: 12px;
  background: #f5f9fd;
  padding: 4px;
}

.workspace-view-switch button {
  min-height: 38px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  padding: 7px 14px;
  color: var(--sg-muted);
  font-weight: 750;
  cursor: pointer;
}

.workspace-view-switch button.active {
  background: var(--sg-surface);
  box-shadow: 0 2px 9px rgb(34 86 132 / 10%);
  color: var(--sg-brand-strong);
}

.workflow-tabs {
  border-bottom: 1px solid var(--sg-line);
}

[role="tablist"] {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  width: 100%;
  gap: 6px;
}

[role="tab"] {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 0;
  border-bottom: 3px solid transparent;
  background: transparent;
  padding: 11px 8px;
  color: var(--sg-muted);
  font-weight: 750;
  cursor: pointer;
}

[role="tab"].active {
  border-color: var(--sg-brand);
  color: var(--sg-brand-strong);
}

.tab-label {
  min-width: 0;
  white-space: nowrap;
}

.tab-count {
  min-width: 24px;
  border-radius: 999px;
  background: var(--sg-brand-soft);
  padding: 2px 7px;
  font-size: .76rem;
  font-variant-numeric: tabular-nums;
}

.outcome-panel {
  display: grid;
  gap: 14px;
}

.outcome-panel[hidden] {
  display: none;
}

.status-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.status-filters button {
  min-height: 38px;
  border: 1px solid var(--sg-line);
  border-radius: 999px;
  background: var(--sg-surface);
  padding: 7px 11px;
  color: var(--sg-muted);
  font-size: .78rem;
  font-weight: 700;
  cursor: pointer;
}

.status-filters button.active {
  border-color: #9ecfff;
  background: var(--sg-brand-soft);
  color: var(--sg-brand-strong);
}

.outcome-list {
  display: grid;
  gap: 12px;
}

.outcome-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  border: 1px solid var(--sg-line);
  border-radius: var(--sg-radius-md);
  background: var(--sg-surface);
  padding: 20px;
}

.outcome-card h2,
.outcome-card p {
  margin: 0;
}

.outcome-card h2 {
  margin-top: 8px;
  font-size: 1.08rem;
}

.outcome-card p {
  margin-top: 7px;
  color: var(--sg-muted);
  line-height: 1.5;
}

.content-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--sg-muted);
  font-size: .75rem;
  font-weight: 750;
}

.status-badge {
  border-radius: 999px;
  background: var(--sg-brand-soft);
  padding: 4px 8px;
  color: var(--sg-brand-strong);
}

.submission-id {
  font-family: ui-monospace, monospace;
  font-size: .8rem;
}

.publishing-empty {
  grid-template-columns: minmax(0, 1fr) auto;
}

.publishing-empty h2,
.publishing-empty p {
  margin: 0;
}

.publishing-empty h2 {
  font-size: 1rem;
}

.publishing-empty p {
  margin-top: 5px;
}

@media (max-width: 560px) {
  .workspace-view-switch {
    width: 100%;
  }

  .workspace-view-switch button {
    flex: 1;
  }

  [role="tablist"] {
    gap: 2px;
  }

  [role="tab"] {
    gap: 4px;
    padding-inline: 4px;
    font-size: .82rem;
  }

  .tab-count {
    min-width: 21px;
    padding-inline: 5px;
  }

  .outcome-card {
    align-items: stretch;
    flex-direction: column;
    padding: 17px;
  }

  .outcome-card .button {
    width: 100%;
  }

  .publishing-empty {
    grid-template-columns: 1fr;
  }
}
</style>
