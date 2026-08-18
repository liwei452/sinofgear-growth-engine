<script setup lang="ts">
import { computed } from "vue"

import type { GrowthWorkspace } from "../growth/api"

const props = defineProps<{ workspace: GrowthWorkspace }>()

const formalAccountIds = computed(() => new Set(
  props.workspace.target_accounts.filter(item => !item.is_demo).map(item => item.id),
))
const effectiveCustomers = computed(() => {
  const count = new Set(props.workspace.intent_signals
    .filter(item => item.collection_method !== "DEMO_FIXTURE" && formalAccountIds.value.has(item.account_id))
    .map(item => item.account_id)).size
  return count || null
})
const approvedContent = computed(() => {
  const count = (props.workspace.channel_packages ?? []).filter(item => !item.is_demo && item.status === "APPROVED").length
  return count || null
})
const publishedContent = computed(() => {
  const count = (props.workspace.publish_batches ?? [])
    .filter(item => !item.is_demo)
    .flatMap(item => item.items)
    .filter(item => item.status === "SUCCEEDED").length
  return count || null
})
const validInquiries = computed(() => {
  const count = (props.workspace.inbound_leads ?? []).filter(item => item.is_demo !== true).length
  return count || null
})
const kpis = computed(() => [
  { label: "有效客户", value: effectiveCustomers.value, note: "有真实意向证据的账户" },
  { label: "已批准内容", value: approvedContent.value, note: "已通过人工审核" },
  { label: "已发布内容", value: publishedContent.value, note: "平台任务已成功记录" },
  { label: "有效询盘", value: validInquiries.value, note: "已记录的入站需求" },
])
</script>

<template>
  <section class="effect-kpis" aria-label="经营效果核心指标">
    <article v-for="item in kpis" :key="item.label">
      <span>{{ item.label }}</span>
      <strong>{{ item.value ?? "无数据" }}</strong>
      <small>{{ item.note }}</small>
    </article>
  </section>
</template>

<style scoped>
.effect-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.effect-kpis article { position: relative; display: grid; gap: 7px; overflow: hidden; border: 1px solid var(--sg-line); border-radius: 17px; background: #fff; padding: 18px; box-shadow: var(--sg-shadow-sm); }
.effect-kpis article::after { content: ""; position: absolute; width: 48px; height: 48px; right: -15px; top: -15px; border-radius: 50%; background: var(--sg-brand-soft); }
.effect-kpis span { color: var(--sg-muted); font-size: .72rem; font-weight: 750; }
.effect-kpis strong { color: var(--sg-ink); font-size: 1.45rem; }
.effect-kpis small { color: #8096ad; font-size: .65rem; }
@media (max-width: 900px) { .effect-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 520px) { .effect-kpis { grid-template-columns: 1fr; } }
</style>
