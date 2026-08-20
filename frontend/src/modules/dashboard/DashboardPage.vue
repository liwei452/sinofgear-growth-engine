<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"
import { useRouter } from "vue-router"

import { ApiError } from "../../api/client"
import BusinessState from "../../shared/components/BusinessState.vue"
import WorkspaceHeader from "../../shared/components/WorkspaceHeader.vue"
import { businessStatus } from "../../shared/presentation/businessStatus"
import { missionsQueryOptions } from "../missions/api"
import TodayWorkInbox from "../workItems/TodayWorkInbox.vue"
import { workItemsQueryOptions } from "../workItems/api"

const router = useRouter()
const missionsQuery = useQuery(missionsQueryOptions())
const workItemsQuery = useQuery(workItemsQueryOptions())

const workItems = computed(() => workItemsQuery.data.value ?? [])
const missions = computed(() => missionsQuery.data.value ?? [])
const primaryDecision = computed(() => workItems.value.find((item) => item.priority === "URGENT")
  ?? workItems.value.find((item) => item.priority === "HIGH")
  ?? null)
const primaryBlocker = computed(() => workItems.value.find((item) => item.action_type === "OPEN_SETTINGS") ?? null)
const latestEvidence = computed(() => [...missions.value]
  .sort((left, right) => right.created_at.localeCompare(left.created_at))[0] ?? null)
const evidenceStatus = computed(() => latestEvidence.value ? businessStatus(latestEvidence.value.health_status) : null)

function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403
}
</script>

<template>
  <section class="today-page">
    <WorkspaceHeader
      title="今日"
      description="基于当前任务和增长记录，先确认机会、阻塞、证据与下一步。"
      :status="latestEvidence?.health_status"
    />

    <div class="confidence-grid">
      <section class="confidence-region" aria-labelledby="today-opportunity-title">
        <h2 id="today-opportunity-title">今日最重要机会</h2>
        <BusinessState
          v-if="workItemsQuery.isLoading.value"
          kind="loading"
          title="正在读取待办"
          message="待办记录加载完成后，才能确认今日最重要机会。"
        />
        <BusinessState
          v-else-if="workItemsQuery.isError.value && isForbidden(workItemsQuery.error.value)"
          kind="blocked"
          title="无权查看待办"
          message="当前账号无权读取待办记录，无法确认今日机会。"
          action-label="前往设置"
          @action="router.push('/settings')"
        />
        <BusinessState
          v-else-if="workItemsQuery.isError.value"
          kind="error"
          title="待办暂时无法读取"
          message="待办记录不可用，暂时无法确认今日机会。"
          action-label="重新加载待办"
          @action="workItemsQuery.refetch()"
        />
        <template v-else-if="primaryDecision">
          <p class="region-title">{{ primaryDecision.title }}</p>
          <p>{{ primaryDecision.summary }}</p>
          <RouterLink class="button button-primary" to="#today-todo">前往待办处理</RouterLink>
        </template>
        <BusinessState
          v-else
          kind="empty"
          title="暂无可确认的机会"
          message="当前记录中没有紧急或高优先级事项。"
          action-label="查看增长任务"
          @action="router.push('/missions')"
        />
      </section>

      <section class="confidence-region" aria-labelledby="today-blocker-title">
        <h2 id="today-blocker-title">当前阻塞</h2>
        <BusinessState
          v-if="workItemsQuery.isLoading.value"
          kind="loading"
          title="正在读取待办"
          message="待办记录加载完成后，才能确认当前是否存在阻塞。"
        />
        <BusinessState
          v-else-if="workItemsQuery.isError.value && isForbidden(workItemsQuery.error.value)"
          kind="blocked"
          title="无权查看待办"
          message="当前账号无权读取待办记录，无法确认当前阻塞。"
          action-label="前往设置"
          @action="router.push('/settings')"
        />
        <BusinessState
          v-else-if="workItemsQuery.isError.value"
          kind="error"
          title="待办暂时无法读取"
          message="待办记录不可用，暂时无法确认当前阻塞。"
          action-label="重新加载待办"
          @action="workItemsQuery.refetch()"
        />
        <template v-else-if="primaryBlocker">
          <p class="region-title">{{ primaryBlocker.title }}</p>
          <p>{{ primaryBlocker.summary }}</p>
          <RouterLink class="button button-secondary" to="/settings">{{ primaryBlocker.action_label }}</RouterLink>
        </template>
        <BusinessState
          v-else
          kind="success"
          title="暂无已记录阻塞"
          message="当前待办中没有需要前往设置处理的阻塞项。"
          action-label="查看设置"
          @action="router.push('/settings')"
        />
      </section>

      <section class="confidence-region" aria-labelledby="today-evidence-title">
        <h2 id="today-evidence-title">最新证据</h2>
        <BusinessState
          v-if="missionsQuery.isLoading.value"
          kind="loading"
          title="正在读取增长记录"
          message="增长记录加载完成后，才能确认最新证据。"
        />
        <BusinessState
          v-else-if="missionsQuery.isError.value && isForbidden(missionsQuery.error.value)"
          kind="blocked"
          title="无权查看增长记录"
          message="当前账号无权读取增长记录，无法确认最新证据。"
          action-label="前往设置"
          @action="router.push('/settings')"
        />
        <BusinessState
          v-else-if="missionsQuery.isError.value"
          kind="error"
          title="增长记录暂时无法读取"
          message="增长记录不可用，暂时无法确认最新证据。"
          action-label="重新加载记录"
          @action="missionsQuery.refetch()"
        />
        <template v-else-if="latestEvidence">
          <p class="region-title">{{ latestEvidence.title }}</p>
          <p>{{ evidenceStatus?.label }}：{{ evidenceStatus?.consequence }}</p>
          <time :datetime="latestEvidence.created_at">记录于 {{ latestEvidence.created_at }}</time>
        </template>
        <BusinessState
          v-else
          kind="unknown"
          title="暂无增长记录"
          message="尚无任务记录可作为今日判断的证据。"
          action-label="创建增长任务"
          @action="router.push('/missions')"
        />
      </section>

      <TodayWorkInbox id="today-todo" class="today-inbox" />
    </div>
  </section>
</template>

<style scoped>
.today-page { display: grid; gap: 18px; }
.confidence-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); overflow: hidden; border: 1px solid var(--sg-line); border-radius: 14px; background: #fff; }
.confidence-region { display: grid; align-content: start; gap: 10px; min-width: 0; padding: 18px; }
.confidence-region + .confidence-region { border-left: 1px solid var(--sg-line); }
.confidence-region h2 { margin: 0; font-size: 1rem; }
.confidence-region p { margin: 0; color: var(--sg-muted); font-size: .82rem; line-height: 1.5; }
.confidence-region .region-title { color: var(--sg-ink); font-weight: 800; }
.confidence-region time { color: var(--sg-muted); font-size: .72rem; }
.confidence-region :deep(.business-state) { border: 0; background: transparent; padding: 0; box-shadow: none; }
.confidence-region :deep(.business-state-copy h2) { font-size: .85rem; }
.today-inbox { grid-column: 1 / -1; border: 0; border-top: 1px solid var(--sg-line); border-radius: 0; box-shadow: none; }
@media (max-width: 900px) {
  .confidence-grid { grid-template-columns: 1fr; }
  .confidence-region + .confidence-region { border-top: 1px solid var(--sg-line); border-left: 0; }
}
</style>
