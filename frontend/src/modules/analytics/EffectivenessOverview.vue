<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed, ref } from "vue"
import { RouterLink } from "vue-router"

import AppIcon from "../../shared/components/AppIcon.vue"
import WorkspaceHeader from "../../shared/components/WorkspaceHeader.vue"
import { growthWorkspaceQueryOptions, type MetricReceipt } from "../growth/api"

import ChannelComparison from "./ChannelComparison.vue"
import EffectivenessKpis from "./EffectivenessKpis.vue"
import MetricEntryDrawer from "./MetricEntryDrawer.vue"

const workspaceQuery = useQuery(growthWorkspaceQueryOptions())
const drawerOpen = ref(false)

function receiptTotal(receipt: MetricReceipt): number {
  return ["views", "impressions", "clicks", "replies", "inquiries"].reduce((sum, field) => {
    const value = receipt.payload[field]
    return sum + (typeof value === "number" && value >= 0 ? value : 0)
  }, 0)
}

const recordedReceipts = computed(() => (workspaceQuery.data.value?.metric_receipts ?? [])
  .filter(item => !item.is_demo))
const trendRows = computed(() => recordedReceipts.value.slice(0, 6).map(item => ({
  id: item.id,
  label: item.channel,
  value: receiptTotal(item),
  width: 0,
})).map((item, _index, rows) => ({
  ...item,
  width: Math.max(6, Math.round(item.value / Math.max(...rows.map(row => row.value), 1) * 100)),
})))

const suggestion = computed(() => {
  const workspace = workspaceQuery.data.value
  if (!workspace) return { text: "正在读取已保存的经营记录。", to: "/content-factory", action: "查看内容" }
  const approved = workspace.channel_packages.some(item => !item.is_demo && item.status === "APPROVED")
  if (!approved) return { text: "先完成一份有证据的内容并提交人工审核。", to: "/content-factory", action: "创建内容" }
  if (!recordedReceipts.value.length) return { text: "已有内容通过审核，可以录入平台后台核实的渠道结果。", to: "", action: "录入数据" }
  return { text: "渠道结果已有记录，下一步检查询盘质量与客户证据是否对应。", to: "/opportunities", action: "查看机会" }
})

function followSuggestion(): void {
  if (!suggestion.value.to) drawerOpen.value = true
}
</script>

<template>
  <div class="effectiveness-page">
    <WorkspaceHeader
      eyebrow="经营总览"
      title="经营效果"
      description="只展示已保存、可追溯的客户、内容、发布与询盘结果。"
    >
      <template #actions>
        <button class="button button-primary" type="button" @click="drawerOpen = true">
          <AppIcon name="chart-column" :size="17" />
          录入数据
        </button>
      </template>
    </WorkspaceHeader>

    <p v-if="workspaceQuery.isPending.value" class="overview-state">正在读取经营记录…</p>
    <p v-else-if="workspaceQuery.isError.value" class="overview-state is-error">经营记录暂时无法读取，请稍后重试。</p>

    <template v-if="workspaceQuery.data.value">
      <EffectivenessKpis :workspace="workspaceQuery.data.value" />

      <div class="effectiveness-grid">
        <section class="trend-card" aria-labelledby="effectiveness-trend-title">
          <header>
            <div><p>TREND</p><h2 id="effectiveness-trend-title">近期记录趋势</h2></div>
            <span>最多 6 条</span>
          </header>
          <div v-if="trendRows.length" class="trend-list">
            <div v-for="row in trendRows" :key="row.id" class="trend-row">
              <span>{{ row.label }}</span>
              <i><b :style="{ width: `${row.width}%` }" /></i>
              <strong>{{ row.value }}</strong>
            </div>
          </div>
          <p v-else class="empty-copy">尚无已记录趋势，录入平台核实结果后显示。</p>
        </section>

        <ChannelComparison :receipts="workspaceQuery.data.value.metric_receipts" />
      </div>

      <section class="system-suggestion" aria-labelledby="system-suggestion-title">
        <span class="suggestion-icon"><AppIcon name="sparkles" :size="20" /></span>
        <div><p>SYSTEM GUIDANCE</p><h2 id="system-suggestion-title">系统建议</h2><span>{{ suggestion.text }}</span></div>
        <RouterLink v-if="suggestion.to" class="button button-secondary" :to="suggestion.to">{{ suggestion.action }}</RouterLink>
        <button v-else class="button button-secondary" type="button" @click="followSuggestion">{{ suggestion.action }}</button>
      </section>
    </template>

    <MetricEntryDrawer :open="drawerOpen" @close="drawerOpen = false" />
  </div>
</template>

<style scoped>
.effectiveness-page { display: grid; gap: 18px; }
.effectiveness-grid { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(320px, .92fr); gap: 14px; }
.trend-card, .system-suggestion { border: 1px solid var(--sg-line); border-radius: 17px; background: #fff; padding: 18px; box-shadow: var(--sg-shadow-sm); }
.trend-card header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.trend-card header p, .trend-card h2 { margin: 0; }
.trend-card header p, .system-suggestion > div > p { color: var(--sg-brand); font-size: .62rem; font-weight: 900; letter-spacing: .1em; }
.trend-card h2 { margin-top: 3px; font-size: .96rem; }
.trend-card header > span, .empty-copy { color: var(--sg-muted); font-size: .68rem; }
.empty-copy { margin: 22px 0 4px; }
.trend-list { display: grid; gap: 13px; margin-top: 18px; }
.trend-row { display: grid; grid-template-columns: 82px minmax(0, 1fr) 52px; align-items: center; gap: 10px; font-size: .7rem; }
.trend-row > span { overflow: hidden; color: var(--sg-muted); text-overflow: ellipsis; }
.trend-row i { height: 8px; overflow: hidden; border-radius: 999px; background: var(--sg-brand-soft); }
.trend-row b { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #1687ff, #53b8ff); }
.trend-row strong { text-align: right; }
.system-suggestion { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 14px; }
.suggestion-icon { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 13px; background: var(--sg-brand-soft); color: var(--sg-brand); }
.system-suggestion p, .system-suggestion h2 { margin: 0; }
.system-suggestion h2 { margin: 3px 0 5px; font-size: .95rem; }
.system-suggestion div > span { color: var(--sg-muted); font-size: .73rem; }
.overview-state { margin: 0; border-radius: 12px; background: var(--sg-brand-soft); padding: 14px; color: var(--sg-muted); }
.overview-state.is-error { background: var(--sg-danger-soft); color: var(--sg-danger); }
@media (max-width: 920px) { .effectiveness-grid { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .system-suggestion { grid-template-columns: auto 1fr; }.system-suggestion .button { grid-column: 1 / -1; width: 100%; } }
</style>
