<script setup lang="ts">
defineProps<{
  activeMarketLabel: string
  activeMarketIndustries: string
  validationPeriodLabel: string
}>()
</script>

<template>
  <section class="growth-card plan-summary">
    <div><span>目标市场</span><strong>{{ activeMarketLabel }}</strong></div>
    <div><span>理想客户</span><strong>{{ activeMarketIndustries }}</strong></div>
    <div><span>验证周期</span><strong>{{ validationPeriodLabel }}</strong></div>
    <div><span>审核边界</span><strong>所有内容人工批准后导出</strong></div>
  </section>
</template>
