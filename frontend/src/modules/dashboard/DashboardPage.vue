<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"
import { useRouter } from "vue-router"

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
</script>

<template>
  <main class="today-page">
    <WorkspaceHeader
      title="今日"
      description="基于当前任务和增长记录，先确认机会、阻塞、证据与下一步。"
      :status="latestEvidence?.health_status"
    />

    <div class="confidence-grid">
      <section class="confidence-region" aria-labelledby="today-opportunity-title">
        <h2 id="today-opportunity-title">今日最重要机会</h2>
        <template v-if="primaryDecision">
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
        <template v-if="primaryBlocker">
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
        <template v-if="latestEvidence">
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

      <TodayWorkInbox id="today-todo" />
    </div>
  </main>
</template>

<style scoped>
.today-page { display: grid; gap: 18px; }
.confidence-grid { display: grid; gap: 16px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.confidence-region { display: grid; align-content: start; gap: 10px; border: 1px solid var(--sg-line); border-radius: 14px; background: #fff; padding: 18px; }
.confidence-region h2 { margin: 0; font-size: 1rem; }
.confidence-region p { margin: 0; color: var(--sg-muted); font-size: .82rem; line-height: 1.5; }
.confidence-region .region-title { color: var(--sg-ink); font-weight: 800; }
.confidence-region time { color: var(--sg-muted); font-size: .72rem; }
.confidence-region :deep(.business-state) { padding: 0; }
.confidence-region :deep(.business-state-copy h2) { font-size: .85rem; }
@media (max-width: 900px) { .confidence-grid { grid-template-columns: 1fr; } }
</style>
