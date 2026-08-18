<script setup lang="ts">
import { computed } from "vue"
import { RouterLink } from "vue-router"

import type { MetricReceipt } from "../growth/api"

const props = defineProps<{ receipts: MetricReceipt[] }>()

const days = computed(() => {
  const result: Array<{ key: string; label: string; count: number }> = []
  const formatter = new Intl.DateTimeFormat("zh-CN", { weekday: "short" })
  const now = new Date()
  for (let offset = 6; offset >= 0; offset -= 1) {
    const date = new Date(now)
    date.setHours(0, 0, 0, 0)
    date.setDate(date.getDate() - offset)
    const key = date.toISOString().slice(0, 10)
    result.push({
      key,
      label: formatter.format(date),
      count: props.receipts.filter((receipt) => !receipt.is_demo && receipt.created_at.slice(0, 10) === key).length,
    })
  }
  return result
})

const maximum = computed(() => Math.max(1, ...days.value.map(day => day.count)))
const hasRecordedActivity = computed(() => days.value.some(day => day.count > 0))
</script>

<template>
  <section class="workspace-card trend-card" aria-labelledby="dashboard-trend-title">
    <div class="trend-heading">
      <div>
        <h2 id="dashboard-trend-title">近七天记录</h2>
        <p>仅统计已保存的渠道结果记录，不推算曝光或转化。</p>
      </div>
      <RouterLink to="/analytics">查看经营效果</RouterLink>
    </div>
    <div v-if="hasRecordedActivity" class="trend-bars" role="img" aria-label="近七天已记录业务活动">
      <div v-for="day in days" :key="day.key">
        <span :style="{ height: `${Math.max(8, day.count / maximum * 100)}%` }" />
        <small>{{ day.label }}</small>
        <b>{{ day.count }}</b>
      </div>
    </div>
    <div v-else class="trend-empty">
      <strong>还没有近七天业务记录</strong>
      <p>发布后录入真实点击、回复或询盘，趋势才会出现。</p>
    </div>
  </section>
</template>

<style scoped>
.trend-card { padding: 20px; }
.trend-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.trend-heading h2, .trend-heading p, .trend-empty p { margin: 0; }
.trend-heading h2 { font-size: 1rem; }
.trend-heading p, .trend-empty p { margin-top: 5px; color: var(--sg-muted); font-size: .8rem; line-height: 1.55; }
.trend-heading a { color: var(--sg-brand-strong); font-size: .8rem; font-weight: 750; text-decoration: none; }
.trend-bars { display: grid; height: 150px; grid-template-columns: repeat(7, 1fr); gap: 12px; align-items: end; margin-top: 20px; }
.trend-bars div { display: grid; height: 100%; grid-template-rows: 1fr auto auto; gap: 5px; align-items: end; text-align: center; }
.trend-bars span { width: min(100%, 28px); min-height: 8px; justify-self: center; border-radius: 8px 8px 3px 3px; background: linear-gradient(180deg, #57b2ff, var(--sg-brand)); }
.trend-bars small { color: var(--sg-muted); font-size: .7rem; }
.trend-bars b { font-size: .72rem; }
.trend-empty { margin-top: 18px; border-radius: 12px; background: var(--sg-canvas); padding: 18px; }
@media (max-width: 560px) { .trend-heading { display: grid; }.trend-bars { gap: 5px; } }
</style>
