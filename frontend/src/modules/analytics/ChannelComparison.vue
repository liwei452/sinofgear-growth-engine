<script setup lang="ts">
import { computed } from "vue"

import type { MetricReceipt } from "../growth/api"

const props = defineProps<{ receipts: MetricReceipt[] }>()

function metric(item: MetricReceipt, name: string): number | null {
  const value = item.payload[name]
  return typeof value === "number" && value >= 0 ? value : null
}

const rows = computed(() => {
  const byChannel = new Map<string, {
    channel: string
    reach: number
    clicks: number
    inquiries: number
  }>()
  for (const item of props.receipts) {
    if (item.is_demo) continue
    const channel = item.channel
    const current = byChannel.get(channel) ?? { channel, reach: 0, clicks: 0, inquiries: 0 }
    current.reach += metric(item, "views") ?? metric(item, "impressions") ?? 0
    current.clicks += metric(item, "clicks") ?? 0
    current.inquiries += metric(item, "inquiries") ?? 0
    byChannel.set(channel, current)
  }
  return [...byChannel.values()]
})
</script>

<template>
  <section class="channel-comparison" aria-labelledby="channel-comparison-title">
    <header><div><p>CHANNELS</p><h2 id="channel-comparison-title">渠道比较</h2></div><span>仅已记录数据</span></header>
    <div v-if="rows.length" class="comparison-table">
      <table>
        <thead><tr><th scope="col">渠道</th><th scope="col">触达</th><th scope="col">点击</th><th scope="col">询盘</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.channel"><th scope="row">{{ row.channel }}</th><td>{{ row.reach }}</td><td>{{ row.clicks }}</td><td>{{ row.inquiries }}</td></tr></tbody>
      </table>
    </div>
    <p v-else>尚未记录渠道结果，暂不生成比较。</p>
  </section>
</template>

<style scoped>
.channel-comparison { display: grid; gap: 14px; border: 1px solid var(--sg-line); border-radius: 17px; background: #fff; padding: 18px; box-shadow: var(--sg-shadow-sm); }
.channel-comparison header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.channel-comparison header p, .channel-comparison h2 { margin: 0; }.channel-comparison header p { color: var(--sg-brand); font-size: .62rem; font-weight: 900; letter-spacing: .1em; }.channel-comparison h2 { margin-top: 3px; font-size: .96rem; }.channel-comparison header > span, .channel-comparison > p { color: var(--sg-muted); font-size: .68rem; }.channel-comparison > p { margin: 0; }
.comparison-table { overflow-x: auto; }.comparison-table table { width: 100%; min-width: 330px; border-collapse: collapse; }.comparison-table th, .comparison-table td { border-top: 1px solid var(--sg-line); padding: 10px 8px; color: var(--sg-muted); font-size: .69rem; text-align: left; }.comparison-table thead th { color: #8aa0b6; font-weight: 800; }.comparison-table tbody th { color: var(--sg-ink); }
</style>
