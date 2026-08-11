<script setup lang="ts">
import { computed, ref } from "vue"
import { useQuery, useQueryClient } from "@tanstack/vue-query"

import { ApiError } from "../../api/client"
import { currentUserQueryOptions } from "../auth/auth"
import StatusBadge from "../../shared/components/StatusBadge.vue"
import { ordinaryStatus } from "../../shared/presentation/ordinary"
import ContentReviewDialog from "./ContentReviewDialog.vue"
import {
  contentQueryKeys, listCampaigns, listMasterContents, listPlatformContents,
  listPlatformPage, type ContentFilters, type MasterContent, type PlatformContent,
} from "./api"
import { useCursorCollection } from "./useCursorCollection"

type ReviewItem = MasterContent | PlatformContent
const queryClient = useQueryClient()
const currentUserQuery = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUserQuery.data.value?.organization.id ?? "")
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const enabled = computed(() => Boolean(organizationId.value) && permissions.value.includes("content.read"))
const tab = ref<"master" | "platform">("master")
const status = ref("IN_REVIEW")
const campaign = ref("")
const platform = ref("")
const selected = ref<ReviewItem | null>(null)
const notice = ref("")
const error = ref("")

const filters = computed<ContentFilters>(() => ({
  ...(status.value ? { status: status.value as ContentFilters["status"] } : {}),
  ...(campaign.value ? { campaign: campaign.value } : {}),
  ...(tab.value === "platform" && platform.value ? { platform: platform.value } : {}),
}))
const masterQuery = useQuery({
  queryKey: computed(() => contentQueryKeys.masterContents(organizationId.value, filters.value)),
  queryFn: () => listMasterContents(filters.value), enabled: computed(() => enabled.value && tab.value === "master"),
})
const platformQuery = useQuery({
  queryKey: computed(() => contentQueryKeys.platformContents(organizationId.value, filters.value)),
  queryFn: () => listPlatformContents(filters.value), enabled: computed(() => enabled.value && tab.value === "platform"),
})
const campaignsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.campaigns(organizationId.value)), queryFn: listCampaigns, enabled })
const platformsQuery = useQuery({ queryKey: computed(() => contentQueryKeys.platforms(organizationId.value)), queryFn: listPlatformPage, enabled })
const campaignPages = useCursorCollection(campaignsQuery.data, "/api/v1/campaigns", organizationId, (item) => item.id)
const platformOptions = useCursorCollection(platformsQuery.data, "/api/v1/platforms", organizationId, (item) => item.id)
const masterPages = useCursorCollection(
  masterQuery.data, "/api/v1/master-contents",
  computed(() => `${organizationId.value}:${JSON.stringify(filters.value)}`), (item) => item.id,
)
const platformPages = useCursorCollection(
  platformQuery.data, "/api/v1/platform-contents",
  computed(() => `${organizationId.value}:${JSON.stringify(filters.value)}`), (item) => item.id,
)
const items = computed<ReviewItem[]>(() => tab.value === "master"
  ? masterPages.items.value : platformPages.items.value)
const activePages = computed(() => tab.value === "master" ? masterPages : platformPages)
const pending = computed(() => tab.value === "master" ? masterQuery.isPending.value : platformQuery.isPending.value)
const failed = computed(() => tab.value === "master" ? masterQuery.error.value : platformQuery.error.value)
const statusTone = (value: string): "brand" | "success" | "warning" | "danger" | "neutral" => (
  value === "APPROVED" || value === "PUBLISHED" ? "success"
    : value === "REJECTED" ? "danger" : value === "IN_REVIEW" ? "warning" : "neutral"
)

function switchTab(next: "master" | "platform"): void {
  tab.value = next
  platform.value = ""
  selected.value = null
}
async function updated(item: ReviewItem): Promise<void> {
  selected.value = item
  notice.value = "内容已更新。"
  await queryClient.invalidateQueries({ queryKey: tab.value === "master"
    ? contentQueryKeys.masterContents(organizationId.value, filters.value)
    : contentQueryKeys.platformContents(organizationId.value, filters.value) })
}
async function platformGenerated(): Promise<void> {
  notice.value = "平台版本已刷新。"
  await queryClient.invalidateQueries({ queryKey: contentQueryKeys.platformContents(organizationId.value, {}) })
}
async function refreshConflict(): Promise<void> {
  notice.value = "内容状态已变化，列表已刷新。"
  if (tab.value === "master") await masterQuery.refetch()
  else await platformQuery.refetch()
}
async function retry(): Promise<void> {
  error.value = ""
  if (tab.value === "master") await masterQuery.refetch()
  else await platformQuery.refetch()
}
function safeError(): string {
  return failed.value instanceof ApiError ? failed.value.userMessage : "审核队列暂时无法加载，请重试。"
}
function filterError(reason: unknown, label: string): string {
  return reason instanceof ApiError ? reason.userMessage : `${label}没有加载成功，请重试。`
}
</script>

<template>
  <main class="page-stack review-center" aria-labelledby="reviews-title">
    <header><p class="eyebrow">集中比较与推进内容</p><h1 id="reviews-title">审核中心</h1><p>查看普通字段，修改内容，并清楚地批准、驳回或归档当前版本。</p></header>
    <p v-if="notice" role="status" class="notice">{{ notice }}</p><p v-if="error" role="alert">{{ error }}</p>
    <div role="tablist" aria-label="内容类型" class="tabs"><button role="tab" type="button" :aria-selected="tab === 'master'" @click="switchTab('master')">通用文案</button><button role="tab" type="button" :aria-selected="tab === 'platform'" @click="switchTab('platform')">渠道文案</button></div>
    <section class="filters" aria-label="审核筛选"><label>内容状态<select v-model="status" aria-label="内容状态"><option value="IN_REVIEW">等待确认</option><option value="DRAFT">草稿</option><option value="APPROVED">已批准</option><option value="REJECTED">已退回</option><option value="ARCHIVED">已归档</option><option value="">全部状态</option></select></label><label>推广计划<select v-model="campaign"><option value="">全部推广计划</option><option v-for="item in campaignPages.items.value" :key="item.id" :value="item.id">{{ item.name }}</option></select><button v-if="campaignPages.next.value" type="button" :disabled="campaignPages.loading.value" @click="campaignPages.loadMore">加载更多推广计划</button><span v-if="campaignPages.error.value" role="alert">{{ campaignPages.error.value }} <button type="button" @click="campaignPages.loadMore">重试加载更多推广计划</button></span></label><label v-if="tab === 'platform'">推广渠道<select v-model="platform"><option value="">全部推广渠道</option><option v-for="item in platformOptions.items.value" :key="item.id" :value="item.id">{{ item.name }}</option></select><button v-if="platformOptions.next.value" type="button" :disabled="platformOptions.loading.value" @click="platformOptions.loadMore">加载更多推广渠道</button><span v-if="platformOptions.error.value" role="alert">{{ platformOptions.error.value }} <button type="button" @click="platformOptions.loadMore">重试加载更多推广渠道</button></span></label></section>
    <p v-if="enabled && campaignsQuery.isError.value" role="alert">{{ filterError(campaignsQuery.error.value, '活动') }} <button type="button" @click="campaignsQuery.refetch()">重新加载活动</button></p>
    <p v-if="enabled && platformsQuery.isError.value" role="alert">{{ filterError(platformsQuery.error.value, '平台') }} <button type="button" @click="platformsQuery.refetch()">重新加载平台</button></p>
    <p v-if="pending" role="status">正在加载待确认内容…</p><section v-else-if="failed" class="state-panel"><h2>待确认内容没有加载成功</h2><p>{{ safeError() }}</p><button type="button" @click="retry">重新加载</button></section><section v-else-if="!items.length && !activePages.next.value" class="state-panel"><h2>当前没有符合条件的内容</h2><p>可以切换状态或内容类型查看其他项目。</p></section><section v-else-if="items.length" class="review-grid"><article v-for="item in items" :key="item.id" class="review-card"><div class="card-heading"><div><p class="eyebrow">第 {{ item.version }} 版</p><h2>{{ item.payload.title }}</h2></div><StatusBadge :tone="statusTone(item.status)" :label="ordinaryStatus(item.status)" /></div><p>{{ item.payload.body.slice(0, 140) }}{{ item.payload.body.length > 140 ? '…' : '' }}</p><p class="muted">来源和版本信息已保留，可在详情中查看。</p><details><summary>高级记录</summary><p>{{ tab === 'master' ? `方案 ${ (item as MasterContent).brief_id } · 生成记录 ${ (item as MasterContent).generation_job_id }` : `通用文案 ${ (item as PlatformContent).master_content_id }` }}</p></details><button type="button" @click="selected = item">查看并确认</button></article></section>
    <p v-if="activePages.error.value" role="alert">{{ activePages.error.value }} <button type="button" @click="activePages.loadMore">重试</button></p><button v-else-if="activePages.next.value" type="button" :disabled="activePages.loading.value" @click="activePages.loadMore">{{ activePages.loading.value ? '正在加载…' : '加载更多待审内容' }}</button>
    <ContentReviewDialog v-if="selected" :item="selected" :kind="tab" :permissions="permissions" :current-head="selected.is_current_head" :platforms="platformOptions.items.value" @close="selected = null" @updated="updated" @platform-generated="platformGenerated" @conflict="refreshConflict" />
  </main>
</template>

<style scoped>
.review-center{display:grid;gap:1.4rem}.tabs{display:flex;gap:.5rem;border-bottom:1px solid #d8dee8}.tabs button{padding:.75rem 1rem;border:0;border-bottom:3px solid transparent;background:transparent}.tabs button[aria-selected=true]{border-color:#1b6b55;font-weight:800}.filters,.card-heading{display:flex;gap:1rem;justify-content:space-between;align-items:flex-start}.filters{flex-wrap:wrap;padding:1rem;border-radius:1rem;background:#f7f9fb}.filters label{display:grid;gap:.35rem}.review-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}.review-card{padding:1rem;border:1px solid #d8dee8;border-radius:1rem;background:#fff}.status-chip{padding:.25rem .55rem;border-radius:999px;background:#edf4f1;font-weight:700}.muted{color:#667085}.notice{padding:.75rem 1rem;border-radius:.75rem;background:#edf8f2}@media(max-width:600px){.filters,.card-heading{display:grid}.filters label{width:100%}}
</style>
