<script setup lang="ts">
import { computed } from "vue"

import type { MarketPilotSummary } from "./api"

const props = defineProps<{ summary: MarketPilotSummary }>()
const emit = defineEmits<{ selectMarket: [payload: { countryCode: string; countryName: string }] }>()
const activeMarkets = computed(() => props.summary.markets.filter((market) => market.status === "ACTIVE_MARKET"))
const candidateMarkets = computed(() => props.summary.markets.filter((market) => market.status !== "ACTIVE_MARKET"))

function rateLabel(value: number | null): string {
  return value === null ? "待采样" : `${value.toFixed(1)}%`
}

function costLabel(value: number): string {
  return `¥${(value / 1_000_000).toFixed(2)}`
}
</script>

<template>
  <section class="growth-card market-pilot" aria-labelledby="market-pilot-title">
    <div class="growth-heading">
      <div><h2 id="market-pilot-title">双市场获客验证</h2><p>同时验证两种找客路线，只用可核验样本计算结果。</p></div>
      <span>8 周对照</span>
    </div>
    <div class="market-pilot-grid">
      <article v-for="market in activeMarkets" :key="market.country_code" :aria-label="`${market.country_label} ${market.route_label}`">
        <div><strong>{{ market.country_label }}</strong><span>{{ market.route_label }}</span></div>
        <dl>
          <div><dt>有效客户率</dt><dd>{{ rateLabel(market.metrics.effective_customer_rate) }}</dd></div>
          <div><dt>积极回复率</dt><dd>{{ rateLabel(market.metrics.positive_reply_rate) }}</dd></div>
          <div><dt>来源成本</dt><dd>{{ costLabel(market.metrics.source_cost_micros) }}</dd></div>
        </dl>
        <small>{{ market.metrics.raw_sample_count }}/{{ summary.quality_gate.minimum_raw_samples }} 条准入样本</small>
        <button class="market-candidate-link" type="button" @click="emit('selectMarket', { countryCode: market.country_code, countryName: market.country_label })">查看该市场候选公司</button>
      </article>
    </div>
    <div class="market-radar-head">
      <h3>市场雷达</h3>
      <p>数据可获得性 25% · 需求强度 25% · 采购意图 20% · 企业可触达性 15% · 商业可执行性 15%</p>
    </div>
    <div class="market-radar-list">
      <details v-for="market in candidateMarkets" :key="market.country_code">
        <summary><strong>{{ market.country_label }} · {{ market.recommended_wave }}</strong><span>{{ market.route_label }}</span></summary>
        <div class="market-radar-detail">
          <p><b>数据来源类型</b> {{ market.source_types.join("、") }}</p>
          <p><b>最近更新</b> {{ market.last_updated_at }}</p>
          <p><b>200 条样本质量</b> {{ market.sample_quality.raw_sample_count }}/200 · 具名买家率 {{ market.sample_quality.named_buyer_rate ?? "待评分" }} · 企业匹配率 {{ market.sample_quality.active_entity_match_rate ?? "待评分" }} · 重复率 {{ market.sample_quality.duplicate_rate ?? "待评分" }}</p>
          <p><b>证据客户门槛</b> {{ market.sample_quality.evidence_company_count }}/{{ market.sample_quality.evidence_company_threshold }} 家</p>
          <p><b>为什么推荐这个市场</b> {{ market.recommendation_reasons.join("；") }}</p>
          <p><b>为什么暂缓</b> {{ market.hold_reasons.join("；") }}</p>
          <button class="market-candidate-link" type="button" @click="emit('selectMarket', { countryCode: market.country_code, countryName: market.country_label })">查看该市场候选公司</button>
        </div>
      </details>
    </div>
  </section>
</template>
<style scoped>.market-candidate-link { margin-top: 10px; border: 0; background: transparent; padding: 0; color: #17699d; font: inherit; font-size: .76rem; font-weight: 850; cursor: pointer; }</style>
