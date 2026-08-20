<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import { apiRequest } from "../../api/client"
import { currentUserQueryOptions } from "../auth/auth"
import ContentReviewDialog from "../content/ContentReviewDialog.vue"
import { listMasterContents, listPlatformContents, listPlatforms, type MasterContent, type PlatformContent } from "../content/api"
import { contentWorkflowStage, type ContentWorkflowStage, type PublishStatus } from "./contentWorkflow"

type PublishTask = {
  id: string
  platform_content_id: string
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

const masterQuery = useQuery({ queryKey: ["publishing-workspace", "masters"], queryFn: () => listMasterContents({ page_size: 50 }), retry: false })
const platformQuery = useQuery({ queryKey: ["publishing-workspace", "platforms-content"], queryFn: () => listPlatformContents({ page_size: 50 }), retry: false })
const tasksQuery = useQuery({
  queryKey: ["publishing-workspace", "tasks"],
  queryFn: async () => (await apiRequest<{ results: PublishTask[] }>("/api/v1/publish-tasks?page_size=50"))?.results ?? [],
  retry: false,
})
const platformDefinitionsQuery = useQuery({ queryKey: ["content", "platforms"], queryFn: listPlatforms, retry: false })
const currentUserQuery = useQuery(currentUserQueryOptions())

const workflowItems = computed<WorkflowItem[]>(() => {
  const tasksByContentId = new Map((tasksQuery.data.value ?? []).map(task => [task.platform_content_id, task]))
  const masterItems = (masterQuery.data.value?.results ?? []).map(item => ({
    id: `master-${item.id}`, item, kind: "master" as const,
    stage: contentWorkflowStage({ contentStatus: item.status, publishStatus: null }), task: null,
  }))
  const platformItems = (platformQuery.data.value?.results ?? []).map(item => {
    const task = tasksByContentId.get(item.id) ?? null
    return { id: `platform-${item.id}`, item, kind: "platform" as const, task,
      stage: contentWorkflowStage({ contentStatus: item.status, publishStatus: task?.status ?? null }) }
  })
  return [...masterItems, ...platformItems]
})
const filteredItems = computed(() => workflowItems.value.filter(item => item.stage === activeStage.value))
const counts = computed(() => Object.fromEntries(stages.map(stage => [stage, workflowItems.value.filter(item => item.stage === stage).length])))
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])

function platformName(item: WorkflowItem): string {
  if (item.kind === "master") return "主内容"
  const code = item.item.payload.platform_code
  return platformDefinitionsQuery.data.value?.find(platform => platform.code === code)?.name ?? code
}

function deliveryFact(item: WorkflowItem): string {
  if (!item.task) return item.kind === "platform" && item.item.publish_package_id ? "发布包已准备，尚未提交平台" : "尚未准备发布"
  const connector = item.task.connector_code.toUpperCase()
  if (connector.includes("BUFFER")) return "通过 Buffer 提交；请以平台回执为准"
  if (connector.includes("OFFICIAL")) return "通过官方 API 提交；请以平台回执为准"
  return "手工导出或待人工提交；导出不代表已发布"
}
</script>

<template>
  <main class="content-area page-stack publishing-workspace">
    <header class="workspace-header">
      <div class="workspace-header-copy">
        <p class="eyebrow">内容工作台</p>
        <h1>内容与发布</h1>
        <p class="workspace-description">按下一步结果管理素材、草稿、审核与发布。预览或导出不是发布；只有平台确认的回执才会显示为“已发布”。</p>
      </div>
    </header>

    <section class="workflow-tabs" aria-label="内容发布状态">
      <div role="tablist" aria-label="内容发布阶段">
        <button v-for="stage in stages" :key="stage" type="button" role="tab" :aria-selected="activeStage === stage" :class="{ active: activeStage === stage }" @click="activeStage = stage">
          {{ labels[stage] }} <span>{{ counts[stage] }}</span>
        </button>
      </div>
    </section>

    <p v-if="masterQuery.isError.value || platformQuery.isError.value || tasksQuery.isError.value" class="form-error">部分状态暂时无法读取；未读取到的内容不会被当作已发布。</p>
    <section v-if="filteredItems.length" class="outcome-list" :aria-label="labels[activeStage]">
      <article v-for="entry in filteredItems" :key="entry.id" class="outcome-card">
        <div>
          <p class="eyebrow">{{ platformName(entry) }} · {{ entry.item.status }}</p>
          <h2>{{ entry.item.payload.title }}</h2>
          <p>{{ deliveryFact(entry) }}</p>
          <p v-if="entry.task?.provider_submission_id" class="submission-id">提交编号：{{ entry.task.provider_submission_id }}</p>
        </div>
        <button type="button" class="button button-secondary" :aria-label="`查看内容：${entry.item.payload.title}`" @click="reviewing = entry">查看内容</button>
      </article>
    </section>
    <section v-else class="empty-state"><div class="empty-state-icon">○</div><div><h2>{{ labels[activeStage] }}暂无内容</h2><p>切换状态查看其他内容。系统不会把未知提交或手工导出误报为已发布。</p></div></section>

    <ContentReviewDialog
      v-if="reviewing"
      :item="reviewing.item"
      :kind="reviewing.kind"
      :permissions="permissions"
      :current-head="reviewing.item.is_current_head"
      :platforms="platformDefinitionsQuery.data.value ?? []"
      @close="reviewing = null"
      @updated="reviewing = null"
      @platform-generated="reviewing = null"
      @conflict="reviewing = null"
    />
  </main>
</template>

<style scoped>
.publishing-workspace{gap:20px}.workflow-tabs{overflow:auto;border-bottom:1px solid var(--sg-line)}[role="tablist"]{display:flex;min-width:max-content;gap:4px}[role="tab"]{border:0;border-bottom:3px solid transparent;background:transparent;padding:10px 12px;color:var(--sg-muted);font-weight:750;cursor:pointer}[role="tab"].active{border-color:var(--sg-brand);color:var(--sg-brand-strong)}[role="tab"] span{margin-left:5px;border-radius:999px;background:var(--sg-brand-soft);padding:2px 7px;font-size:.78rem}.outcome-list{display:grid;gap:12px}.outcome-card{display:flex;align-items:center;justify-content:space-between;gap:20px;border:1px solid var(--sg-line);border-radius:var(--sg-radius-md);background:var(--sg-surface);padding:20px;box-shadow:var(--sg-shadow-sm)}.outcome-card h2,.outcome-card p{margin:0}.outcome-card h2{font-size:1.08rem}.outcome-card p:not(.eyebrow){margin-top:7px;color:var(--sg-muted);line-height:1.5}.submission-id{font-family:ui-monospace,monospace;font-size:.8rem}@media(max-width:560px){.outcome-card{align-items:stretch;flex-direction:column}.outcome-card .button{width:100%}}
</style>
