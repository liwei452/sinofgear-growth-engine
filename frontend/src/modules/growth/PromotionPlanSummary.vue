<script setup lang="ts">
import { computed } from "vue"

import type { PromotionPlan } from "./api"

const props = defineProps<{ plan?: PromotionPlan }>()

const marketsLabel = computed(() => (
  props.plan?.target_markets.map(market => market.country_label).join("、") || "待 AI 生成"
))
const audiencesLabel = computed(() => (
  props.plan?.audiences.map(audience => audience.industry).join("、") || "待 AI 生成"
))
const periodLabel = computed(() => (
  props.plan?.period_weeks ? `${props.plan.period_weeks} 周市场验证` : "待 AI 生成"
))
const themesLabel = computed(() => (
  props.plan?.content_themes.join("；") || "待 AI 生成"
))
const channelsLabel = computed(() => (
  props.plan?.channels.map(channelLabel).join(" · ") || "待 AI 生成"
))

function channelLabel(code: string): string {
  return ({
    LINKEDIN: "LinkedIn",
    FACEBOOK: "Facebook",
    INSTAGRAM: "Instagram",
    TIKTOK: "TikTok",
  } as Record<string, string>)[code] ?? code
}
</script>

<template>
  <section class="growth-card plan-summary">
    <div class="plan-summary-heading">
      <p class="eyebrow">推广计划 · 待人工审核</p>
      <p>{{ plan?.summary || "系统正在根据产品事实与市场档案生成推广计划。" }}</p>
    </div>
    <div class="plan-summary-grid">
      <div><span>目标市场</span><strong>{{ marketsLabel }}</strong></div>
      <div><span>目标人群</span><strong>{{ audiencesLabel }}</strong></div>
      <div><span>验证周期</span><strong>{{ periodLabel }}</strong></div>
      <div><span>内容策略</span><strong>{{ themesLabel }}</strong></div>
      <div><span>发布渠道</span><strong>{{ channelsLabel }}</strong></div>
    </div>
  </section>
</template>

<style scoped src="./growth-pages.css"></style>

<style scoped>
.plan-summary-heading {
  margin-bottom: 4px;
}
.plan-summary-heading p:last-child {
  margin: 0;
  color: var(--sg-muted);
  font-size: 0.8rem;
}
.plan-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.plan-summary-grid div {
  display: grid;
  gap: 3px;
}
.plan-summary-grid span {
  color: var(--sg-muted);
  font-size: 0.72rem;
}
</style>
