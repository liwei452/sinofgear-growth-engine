<script setup lang="ts">
defineProps<{
  activeMarketLabel: string
  activeMarketIndustries: string
  validationPeriodLabel: string
  contentSummary: string
  channelSummary: string
}>()
</script>

<template>
  <section class="growth-card plan-summary">
    <div class="plan-summary-heading">
      <p class="eyebrow">推广计划 · 待人工审核</p>
      <p>系统根据市场档案与产品事实给出建议；所有内容仍需人工批准。</p>
    </div>
    <div class="plan-summary-grid">
      <div><span>目标市场</span><strong>{{ activeMarketLabel }}</strong></div>
      <div><span>目标人群</span><strong>{{ activeMarketIndustries }}</strong></div>
      <div><span>验证周期</span><strong>{{ validationPeriodLabel }}</strong></div>
      <div><span>内容策略</span><strong>{{ contentSummary }}</strong></div>
      <div><span>发布渠道</span><strong>{{ channelSummary }}</strong></div>
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
