<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed, ref, watch } from "vue"
import { RouterLink } from "vue-router"

import { apiRequest } from "../../api/client"
import WorkspaceHeader from "../../shared/components/WorkspaceHeader.vue"
import type { MissionAttribution } from "../attribution/api"
import AttributionEvidenceDrawer from "../attribution/AttributionEvidenceDrawer.vue"
import { missionsQueryOptions } from "../missions/api"

type OutcomeMetric = {
  key: string
  label: string
  value: string
  detail: string
}

const missionsQuery = useQuery(missionsQueryOptions())
const selectedMissionId = ref("")
const showEvidence = ref(false)
const missions = computed(() => missionsQuery.data.value ?? [])
const selectedMission = computed(() => missions.value.find(mission => mission.id === selectedMissionId.value) ?? null)

watch(missions, (list) => {
  if (!selectedMissionId.value && list.length) selectedMissionId.value = list[0].id
})

const attributionQuery = useQuery({
  queryKey: computed(() => ["growth", "attribution", selectedMissionId.value]),
  queryFn: async () => {
    const result = await apiRequest<MissionAttribution>(
      "/api/v1/growth/attribution?mission=" + selectedMissionId.value,
    )
    if (!result) throw new Error("归因响应为空。")
    return result
  },
  enabled: computed(() => Boolean(selectedMissionId.value)),
  staleTime: 15_000,
})

const attribution = computed(() => attributionQuery.data.value)
const confirmedTraceCount = computed(() => (
  attribution.value?.traces.filter(trace => trace.confidence === "CONFIRMED").length ?? 0
))

function formatAmount(value: string): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return value
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount)
}

const outcomeMetrics = computed<OutcomeMetric[]>(() => {
  const outcomes = attribution.value?.outcomes
  if (!outcomes) return []
  const metrics: OutcomeMetric[] = []
  if (typeof outcomes.emails_sent === "number") {
    metrics.push({
      key: "sent",
      label: "已发送或已提交",
      value: String(outcomes.emails_sent),
      detail: "邮件渠道已确认发送",
    })
  }
  if (typeof outcomes.confirmed_replies === "number") {
    metrics.push({
      key: "replies",
      label: "有效回复",
      value: String(outcomes.confirmed_replies),
      detail: "已确认回复记录",
    })
  }
  if (typeof outcomes.confirmed_rfqs === "number") {
    metrics.push({
      key: "rfqs",
      label: "RFQ",
      value: String(outcomes.confirmed_rfqs),
      detail: "已关联当前任务的询盘",
    })
  }
  const revenue = outcomes.won_revenue?.amount
  if (revenue !== null && revenue !== undefined && revenue !== "") {
    metrics.push({
      key: "revenue",
      label: "成交金额",
      value: formatAmount(revenue),
      detail: "币种以成交记录为准",
    })
  }
  return metrics
})
</script>

<template>
  <section class="results-page">
    <WorkspaceHeader
      class="results-header"
      title="效果"
      description="只展示系统中已保存且可核验的成果，并明确每项数据的任务范围。"
    >
      <template #actions>
        <RouterLink class="button button-secondary" to="/attribution">查看完整归因</RouterLink>
      </template>
    </WorkspaceHeader>

    <label class="mission-picker">
      <span>增长任务</span>
      <select v-model="selectedMissionId">
        <option value="" disabled>选择任务</option>
        <option v-for="mission in missions" :key="mission.id" :value="mission.id">{{ mission.title }}</option>
      </select>
    </label>

    <p v-if="!selectedMissionId" class="empty">请选择一个增长任务查看效果。</p>
    <p v-else-if="attributionQuery.isLoading.value" class="empty">正在读取已保存的结果…</p>
    <section v-else-if="attributionQuery.isError.value" class="empty" role="alert">
      <div>
        <h2>效果数据暂时无法读取</h2>
        <p>当前不会显示旧缓存或未经证实的结果。</p>
      </div>
      <button class="button button-secondary" type="button" @click="attributionQuery.refetch()">重新读取效果</button>
    </section>

    <template v-else-if="attribution">
      <section class="results-summary" aria-labelledby="confirmed-outcomes-title">
        <div class="section-heading">
          <div>
            <h2 id="confirmed-outcomes-title">已确认成果</h2>
            <p>当前任务：{{ selectedMission?.title }}</p>
          </div>
          <span class="scope-chip">累计已保存记录</span>
        </div>
        <ul class="outcome-metrics" aria-label="已确认成果指标">
          <li v-for="metric in outcomeMetrics" :key="metric.key" :aria-label="metric.label">
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
            <small>{{ metric.detail }}</small>
          </li>
        </ul>
        <p v-if="attribution.availability.email !== 'CONNECTED'" class="scope-note">
          邮件渠道未接通，已发送或已提交数量未纳入本页。
        </p>
      </section>

      <section class="attribution-scope" aria-labelledby="attribution-scope-title">
        <div>
          <h2 id="attribution-scope-title">任务归因范围</h2>
          <p>仅统计与当前增长任务关联、并保留系统来源记录的回复、询盘和成交。</p>
          <strong>{{ confirmedTraceCount }} 条已确认归因证据</strong>
        </div>
        <button class="button button-secondary" type="button" @click="showEvidence = true">查看证据清单</button>
      </section>

      <AttributionEvidenceDrawer
        v-if="showEvidence"
        :traces="attribution.traces"
        @close="showEvidence = false"
      />
    </template>
  </section>
</template>

<style scoped>
.results-page {
  display: grid;
  gap: 20px;
}

.results-header {
  align-items: center;
  border: 1px solid #c9e3ff;
  border-radius: 18px;
  background: linear-gradient(135deg, #f8fcff 0%, #eaf5ff 100%);
  padding: 24px 26px;
}

.mission-picker {
  display: grid;
  max-width: 420px;
  gap: 7px;
  color: var(--sg-muted);
  font-size: .82rem;
  font-weight: 750;
}

.mission-picker select {
  min-height: 44px;
  border: 1px solid var(--sg-line);
  border-radius: var(--sg-radius-sm);
  background: var(--sg-surface);
  padding: 9px 12px;
  color: var(--sg-ink);
}

.empty,
.results-summary,
.attribution-scope {
  border: 1px solid var(--sg-line);
  border-radius: var(--sg-radius-md);
  background: var(--sg-surface);
  padding: 20px;
}

.empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  color: var(--sg-muted);
}

.empty h2,
.empty p,
.section-heading h2,
.section-heading p,
.attribution-scope h2,
.attribution-scope p {
  margin: 0;
}

.empty h2,
.section-heading h2,
.attribution-scope h2 {
  color: var(--sg-ink);
  font-size: 1.05rem;
}

.empty p,
.section-heading p,
.attribution-scope p {
  margin-top: 5px;
  color: var(--sg-muted);
  font-size: .84rem;
  line-height: 1.55;
}

.section-heading,
.attribution-scope {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.scope-chip {
  border-radius: 999px;
  background: var(--sg-brand-soft);
  padding: 6px 10px;
  color: var(--sg-brand-strong);
  font-size: .74rem;
  font-weight: 800;
}

.outcome-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 18px 0 0;
  padding: 0;
  overflow: hidden;
  border: 1px solid #d8e7f5;
  border-radius: 14px;
  background: #d8e7f5;
  list-style: none;
}

.outcome-metrics li {
  display: grid;
  min-width: 0;
  gap: 6px;
  background: #f7fbff;
  padding: 18px;
}

.outcome-metrics span {
  color: var(--sg-muted);
  font-size: .78rem;
  font-weight: 750;
}

.outcome-metrics strong {
  color: var(--sg-ink);
  font-size: clamp(1.45rem, 2.8vw, 2rem);
  letter-spacing: -.025em;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.outcome-metrics small {
  color: var(--sg-muted);
  font-size: .72rem;
  line-height: 1.45;
}

.scope-note {
  margin: 14px 0 0;
  border-radius: 10px;
  background: #f1f7fc;
  padding: 10px 12px;
  color: #3d6078;
  font-size: .8rem;
}

.attribution-scope strong {
  display: block;
  margin-top: 8px;
  color: var(--sg-brand-strong);
  font-size: .84rem;
}

@media (max-width: 760px) {
  .results-header,
  .section-heading,
  .attribution-scope,
  .empty {
    align-items: stretch;
    flex-direction: column;
  }

  .outcome-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 420px) {
  .results-header,
  .results-summary,
  .attribution-scope,
  .empty {
    padding: 17px;
  }

  .outcome-metrics li {
    padding: 14px;
  }
}
</style>
