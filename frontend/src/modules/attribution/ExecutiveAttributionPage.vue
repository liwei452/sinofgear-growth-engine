<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed, ref, watch } from "vue"

import { apiRequest } from "../../api/client"
import { missionsQueryOptions } from "../missions/api"
import type { MissionAttribution } from "./api"
import AttributionEvidenceDrawer from "./AttributionEvidenceDrawer.vue"

const missionsQuery = useQuery(missionsQueryOptions())
const selectedMissionId = ref("")
const showEvidence = ref(false)

const missions = computed(() => missionsQuery.data.value ?? [])
watch(missions, (list) => {
  if (!selectedMissionId.value && list.length) selectedMissionId.value = list[0].id
})
const attributionQuery = useQuery({
  queryKey: ["growth", "attribution", selectedMissionId],
  queryFn: async () => {
    const result = await apiRequest<MissionAttribution>(
      `/api/v1/growth/attribution?mission=${selectedMissionId.value}`,
    )
    if (!result) throw new Error("归因响应为空。")
    return result
  },
  enabled: computed(() => !!selectedMissionId.value),
  staleTime: 15_000,
})

const attribution = computed(() => attributionQuery.data.value)
</script>

<template>
  <main class="attribution-page">
    <header class="attribution-hero">
      <div>
        <p class="eyebrow">EXECUTIVE ATTRIBUTION</p>
        <h1>数据归因</h1>
        <p>从触达追踪到回复、RFQ、报价、订单与收入，并明确可信等级。</p>
      </div>
    </header>

    <label class="mission-picker">
      增长任务
      <select v-model="selectedMissionId">
        <option value="" disabled>选择任务</option>
        <option v-for="mission in missions" :key="mission.id" :value="mission.id">
          {{ mission.title }}
        </option>
      </select>
    </label>

    <div v-if="!selectedMissionId" class="empty">请选择一个增长任务查看归因。</div>
    <div v-else-if="attributionQuery.isLoading.value" class="empty">正在读取归因…</div>
    <template v-else-if="attribution">
      <section class="outcome-grid">
        <div class="metric"><span class="chip">确定</span><strong>{{ attribution.outcomes.confirmed_replies }}</strong><em>有效回复</em></div>
        <div class="metric"><span class="chip">确定</span><strong>{{ attribution.outcomes.confirmed_rfqs }}</strong><em>RFQ</em></div>
        <div class="metric"><span class="chip">确定</span><strong>{{ attribution.outcomes.won_revenue.amount }}</strong><em>收入</em></div>
        <div class="metric"><span class="chip">{{ attribution.availability.email === "CONNECTED" ? "确定" : "未接通" }}</span><strong>{{ attribution.outcomes.emails_sent ?? "—" }}</strong><em>邮件发送</em></div>
        <div class="metric"><span class="chip">成本</span><strong>{{ attribution.outcomes.cost_per_result ?? "—" }}</strong><em>单位成果成本</em></div>
      </section>

      <section class="diagnostics">
        <h2>辅助诊断</h2>
        <div class="metric"><strong>{{ attribution.diagnostics.impressions }}</strong><em>曝光</em></div>
      </section>

      <button class="button button-quiet" type="button" @click="showEvidence = true">查看依据</button>

      <AttributionEvidenceDrawer
        v-if="showEvidence"
        :traces="attribution.traces"
        @close="showEvidence = false"
      />
    </template>
  </main>
</template>

<style scoped>
.attribution-page { display: grid; gap: 16px; }
.attribution-hero { border-radius: 20px; background: linear-gradient(120deg, var(--sg-brand-deep) 0%, var(--sg-brand-strong) 60%, var(--sg-brand-light) 100%); padding: 24px 28px; color: #fff; }
.attribution-hero h1 { margin: 4px 0 7px; }
.attribution-hero p { margin: 0; color: #eaf5ff; font-size: .82rem; }
.eyebrow { margin: 0; color: #bfe0ff; font-size: .65rem; font-weight: 900; letter-spacing: .1em; }
.mission-picker { display: grid; gap: 6px; max-width: 360px; color: var(--sg-muted); font-size: .74rem; }
.mission-picker select { border: 1px solid #d7e2f0; border-radius: 9px; padding: 8px 9px; }
.outcome-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.metric { display: grid; gap: 5px; border: 1px solid #e5ecf6; border-radius: 14px; background: #fff; padding: 15px; }
.chip { justify-self: start; border-radius: 999px; background: #e7f8ed; padding: 3px 7px; color: #14733c; font-size: .64rem; font-weight: 800; }
.metric strong { font-size: 1.35rem; }
.metric em { color: var(--sg-muted); font-size: .7rem; font-style: normal; }
.diagnostics { display: grid; gap: 10px; border: 1px solid #e5ecf6; border-radius: 14px; background: #fff; padding: 15px; }
.diagnostics h2 { margin: 0; font-size: .9rem; }
.empty { border: 1px dashed var(--sg-line); border-radius: 12px; padding: 20px; color: var(--sg-muted); }
</style>
