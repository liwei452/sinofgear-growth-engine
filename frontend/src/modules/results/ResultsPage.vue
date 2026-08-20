<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed, ref, watch } from "vue"
import { RouterLink } from "vue-router"

import { apiRequest } from "../../api/client"
import type { MissionAttribution } from "../attribution/api"
import AttributionEvidenceDrawer from "../attribution/AttributionEvidenceDrawer.vue"
import { missionsQueryOptions } from "../missions/api"

type FunnelStep = { label: string; value: number | string | null | undefined; detail: string }
const missionsQuery = useQuery(missionsQueryOptions())
const selectedMissionId = ref("")
const showEvidence = ref(false)
const missions = computed(() => missionsQuery.data.value ?? [])
watch(missions, list => { if (!selectedMissionId.value && list.length) selectedMissionId.value = list[0].id })
const attributionQuery = useQuery({
  queryKey: computed(() => ["growth", "attribution", selectedMissionId.value]),
  queryFn: async () => {
    const result = await apiRequest<MissionAttribution>(`/api/v1/growth/attribution?mission=${selectedMissionId.value}`)
    if (!result) throw new Error("归因响应为空。")
    return result
  },
  enabled: computed(() => Boolean(selectedMissionId.value)),
  staleTime: 15_000,
})
const attribution = computed(() => attributionQuery.data.value)
function observed(value: number | string | null | undefined): string { return value === null || value === undefined || value === "" ? "尚未记录" : String(value) }
const funnelSteps = computed<FunnelStep[]>(() => {
  const outcomes = attribution.value?.outcomes
  return [
    { label: "发现公司", value: null, detail: "尚无可核验的发现记录" },
    { label: "人工确认", value: null, detail: "尚无可核验的确认记录" },
    { label: "找到联系路径", value: null, detail: "尚无可核验的联系路径记录" },
    { label: "创建跟进", value: null, detail: "当前归因未提供可核验的跟进创建记录" },
    { label: "获得回复", value: outcomes?.confirmed_replies, detail: "已确认的有效回复" },
    { label: "形成询盘", value: outcomes?.confirmed_rfqs, detail: "已确认的 RFQ" },
    { label: "成交", value: outcomes?.won_revenue?.amount, detail: "已确认的成交收入" },
  ]
})
</script>

<template>
  <section class="results-page">
    <header class="results-hero"><div><p class="eyebrow">BUSINESS OUTCOMES</p><h1>效果</h1><p>只显示系统中已经保存、可核验的结果；没有记录时明确标注。</p></div><RouterLink class="button button-quiet" to="/attribution">查看归因依据</RouterLink></header>
    <label class="mission-picker">增长任务<select v-model="selectedMissionId"><option value="" disabled>选择任务</option><option v-for="mission in missions" :key="mission.id" :value="mission.id">{{ mission.title }}</option></select></label>
    <p v-if="!selectedMissionId" class="empty">请选择一个增长任务查看效果。</p><p v-else-if="attributionQuery.isLoading.value" class="empty">正在读取已保存的结果…</p>
    <section v-else-if="attributionQuery.isError.value" class="empty" role="alert"><p>效果数据暂时无法读取，因此不会显示未经证实的结果。</p><button class="button button-quiet" type="button" @click="attributionQuery.refetch()">重新读取效果</button></section>
    <template v-else-if="attribution">
      <section aria-labelledby="funnel-title" class="funnel-card"><div><h2 id="funnel-title">从机会到成交</h2><p>当前任务累计（全部已保存记录）</p><p>转化漏斗只使用当前任务的归因数据，不推测未记录的步骤。</p></div><ol class="funnel" aria-label="转化漏斗"><li v-for="step in funnelSteps" :key="step.label"><span class="step-label">{{ step.label }}</span><strong :class="{ unknown: observed(step.value) === '尚未记录' }">{{ observed(step.value) }}</strong><small>{{ step.detail }}</small></li></ol></section>
      <section aria-labelledby="funnel-table-title" class="table-card"><h2 id="funnel-table-title">漏斗数据表</h2><table><thead><tr><th>阶段</th><th>已记录结果</th><th>说明</th></tr></thead><tbody><tr v-for="(step, index) in funnelSteps" :key="step.label"><th scope="row" :aria-label="step.label">阶段 {{ index + 1 }}</th><td>{{ observed(step.value) }}</td><td>{{ step.detail }}</td></tr></tbody></table></section>
      <button class="button button-quiet" type="button" @click="showEvidence = true">查看归因依据</button><AttributionEvidenceDrawer v-if="showEvidence" :traces="attribution.traces" @close="showEvidence = false" />
    </template>
  </section>
</template>

<style scoped>
.results-page { display: grid; gap: 18px; }.results-hero { display: flex; justify-content: space-between; gap: 18px; border-radius: 20px; background: linear-gradient(120deg, var(--sg-brand-deep), var(--sg-brand-strong)); padding: 24px 28px; color: #fff; }.results-hero h1 { margin: 4px 0 7px; }.results-hero p { margin: 0; color: #eaf5ff; }.eyebrow { font-size: .65rem; font-weight: 900; letter-spacing: .1em; }.mission-picker { display: grid; gap: 6px; max-width: 360px; color: var(--sg-muted); font-size: .8rem; }.mission-picker select { border: 1px solid var(--sg-line); border-radius: 9px; padding: 8px; }.empty, .funnel-card, .table-card { border: 1px solid var(--sg-line); border-radius: 14px; background: #fff; padding: 18px; }.empty { color: var(--sg-muted); }.funnel-card, .table-card { display: grid; gap: 14px; }.funnel-card h2, .table-card h2 { margin: 0; font-size: 1rem; }.funnel-card p { margin: 5px 0 0; color: var(--sg-muted); font-size: .82rem; }.funnel { display: grid; grid-template-columns: repeat(7, minmax(120px, 1fr)); gap: 10px; margin: 0; padding: 0; list-style: none; overflow-x: auto; }.funnel li { display: grid; gap: 6px; min-width: 120px; border-radius: 10px; background: #f3f7fb; padding: 12px; }.step-label { font-size: .8rem; font-weight: 800; }.funnel strong { font-size: 1.2rem; color: var(--sg-brand-deep); }.funnel .unknown { color: var(--sg-muted); font-size: .9rem; }.funnel small { color: var(--sg-muted); font-size: .7rem; line-height: 1.4; } table { width: 100%; border-collapse: collapse; font-size: .82rem; } th, td { border-top: 1px solid var(--sg-line); padding: 9px; text-align: left; } thead th { border-top: 0; color: var(--sg-muted); } @media (max-width: 760px) { .results-hero { display: grid; } }
</style>
