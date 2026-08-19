<script setup lang="ts">
import { ref } from "vue"

import type { GrowthMission } from "./api"

defineProps<{
  mission: GrowthMission
  canRun: boolean
  candidates: Array<{ id: string; company_name: string }>
}>()

const emit = defineEmits<{
  "start-outreach": [candidateId: string]
  "start-content-strategy": []
}>()

const selectedCandidate = ref("")

const customerStages = ["发现", "待核实", "高意向", "待联系", "已联系", "有回复"]
</script>

<template>
  <section class="lane-board" aria-label="执行线">
    <div class="lane">
      <div class="lane-head">
        <h3>客户开发</h3>
        <span>{{ mission.lane_counts.ACQUISITION + mission.lane_counts.OUTREACH }} 项</span>
      </div>
      <ol class="stages">
        <li v-for="stage in customerStages" :key="stage">{{ stage }}</li>
      </ol>
      <div v-if="canRun" class="lane-actions">
        <select v-model="selectedCandidate" aria-label="选择已接受候选">
          <option value="" disabled>选择已接受候选</option>
          <option v-for="candidate in candidates" :key="candidate.id" :value="candidate.id">
            {{ candidate.company_name }}
          </option>
        </select>
        <button
          class="button button-primary"
          type="button"
          :disabled="!selectedCandidate"
          @click="emit('start-outreach', selectedCandidate)"
        >
          开始获客
        </button>
      </div>
    </div>

    <div class="lane">
      <div class="lane-head">
        <h3>社媒增长</h3>
        <span>{{ mission.lane_counts.SOCIAL }} 项</span>
      </div>
      <ol class="stages">
        <li>内容计划</li>
        <li>生成内容</li>
        <li>人工审核</li>
        <li>排期发布</li>
      </ol>
      <div v-if="canRun" class="lane-actions">
        <button
          class="button button-primary"
          type="button"
          @click="emit('start-content-strategy')"
        >
          开始内容策略
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.lane-board { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.lane { display: grid; gap: 10px; border: 1px solid var(--sg-line); border-radius: 16px; background: #fff; padding: 16px; }
.lane-head { display: flex; align-items: center; justify-content: space-between; }
.lane-head h3 { margin: 0; font-size: 1rem; }
.lane-head span { color: var(--sg-muted); font-size: .7rem; }
.stages { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; list-style: none; }
.stages li { border-radius: 999px; background: var(--sg-brand-soft); padding: 4px 9px; color: var(--sg-brand-strong); font-size: .7rem; }
.lane-actions { display: flex; gap: 8px; }
.lane-actions select { flex: 1; border: 1px solid var(--sg-line); border-radius: 9px; padding: 8px 9px; }
@media (max-width: 720px) { .lane-board { grid-template-columns: 1fr; } }
</style>
