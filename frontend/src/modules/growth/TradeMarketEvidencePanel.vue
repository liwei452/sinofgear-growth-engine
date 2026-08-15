<script setup lang="ts">
import { computed, ref, watch } from "vue"

import { loadTradeIndicators, syncPublicTradeData, type TradeIndicatorResponse } from "./api"

const props = defineProps<{
  markets: Array<{ country_code: string; country_label: string }>
}>()

const supportedCountries = new Set([
  "USA", "GBR", "CAN", "DEU", "VNM", "IDN", "PHL", "ZAF", "EGY", "KEN", "NGA",
  "MAR", "CHL", "PER", "COL", "MEX", "BRA", "IND", "TUR", "PAK", "SAU", "GHA",
])
const availableMarkets = computed(() => props.markets.filter(
  market => supportedCountries.has(market.country_code),
))
const selectedCountry = ref(availableMarkets.value[0]?.country_code ?? "")
const hsInput = ref("848340, 848390")
const currentYear = new Date().getUTCFullYear()
const periods = [`${currentYear - 3}`, `${currentYear - 2}`]
const result = ref<TradeIndicatorResponse | null>(null)
const loading = ref(false)
const syncing = ref(false)
const error = ref("")
const loaded = ref(false)

watch(availableMarkets, (markets) => {
  if (markets.some(market => market.country_code === selectedCountry.value)) return
  selectedCountry.value = markets[0]?.country_code ?? ""
  loaded.value = false
  result.value = null
})

const hsCodes = computed(() => hsInput.value.split(",").map(value => value.trim()).filter(Boolean))
const hsValid = computed(() => (
  hsCodes.value.length > 0
  && hsCodes.value.length <= 10
  && hsCodes.value.every(value => /^(?:\d{4}|\d{6})$/.test(value))
))

async function loadEvidence(): Promise<void> {
  if (!selectedCountry.value || !hsValid.value) return
  loading.value = true
  error.value = ""
  try {
    result.value = await loadTradeIndicators({
      countryCode: selectedCountry.value,
      hsCodes: hsCodes.value,
      periods,
    })
    loaded.value = true
  } catch {
    error.value = "贸易证据读取失败，请稍后重试。"
  } finally {
    loading.value = false
  }
}

async function syncEvidence(): Promise<void> {
  if (!selectedCountry.value || !hsValid.value) return
  syncing.value = true
  error.value = ""
  try {
    await syncPublicTradeData({
      countryCode: selectedCountry.value,
      hsCodes: hsCodes.value,
      periods,
    })
    await loadEvidence()
  } catch {
    error.value = "公开贸易连接器未配置；当前不会自动加载演示数据。"
  } finally {
    syncing.value = false
  }
}

function indicator(key: string) {
  return result.value?.indicators[key]
}

function percent(key: string): string {
  const value = indicator(key)?.value_percent
  return value == null ? "无数据" : `${value}%`
}
</script>

<template>
  <section class="trade-evidence-panel" aria-labelledby="trade-evidence-title">
    <div class="trade-evidence-head">
      <div>
        <h3 id="trade-evidence-title">官方公开贸易证据</h3>
        <p>用于判断市场规模和变化，不会生成买家公司、联系人或采购意向。</p>
      </div>
      <span v-if="result?.is_demo" class="demo-label">Demo / Fake 数据</span>
    </div>
    <div v-if="availableMarkets.length" class="trade-controls">
      <label>市场
        <select v-model="selectedCountry" aria-label="贸易证据市场" @change="loaded = false; result = null">
          <option v-for="market in availableMarkets" :key="market.country_code" :value="market.country_code">
            {{ market.country_label }}
          </option>
        </select>
      </label>
      <label>HS 编码
        <input v-model="hsInput" aria-label="贸易证据 HS 编码" @input="loaded = false; result = null">
      </label>
      <button type="button" :disabled="loading || !hsValid" @click="loadEvidence">
        {{ loading ? "正在读取…" : "查看市场贸易证据" }}
      </button>
      <button type="button" class="primary-action" :disabled="syncing || !hsValid" @click="syncEvidence">
        {{ syncing ? "正在同步…" : "同步公开贸易数据" }}
      </button>
    </div>
    <p v-if="!hsValid" class="validation-message" role="alert">请输入 1–10 个四位或六位 HS 编码，用英文逗号分隔。</p>
    <p v-if="!availableMarkets.length" class="empty-message">请先选择一个支持官方公共贸易统计的观察市场。</p>
    <p v-else-if="!loaded && !error" class="empty-message">尚未读取快照。点击“查看市场贸易证据”读取本组织已保存的数据。</p>
    <p v-if="error" class="validation-message" role="alert">{{ error }}</p>
    <template v-if="loaded && result">
      <p class="scope-warning">{{ result.scope_warning }}</p>
      <div v-if="result.status === 'NO_DATA'" class="empty-message">
        <strong>当前没有官方贸易快照</strong>
        <span>可由有权限的用户同步已配置的官方来源；未配置时不会自动出现 Demo 数据。</span>
      </div>
      <div v-else class="trade-results">
        <dl class="indicator-grid">
          <div><dt>最新进口规模</dt><dd>${{ indicator("import_scale")?.value_usd ?? "无数据" }}</dd><small>公式：最新期间各 HS 世界进口值求和</small></div>
          <div><dt>同比变化</dt><dd>{{ percent("year_over_year") }}</dd><small>(本期 - 上年同期) / 上年同期 × 100%</small></div>
          <div><dt>数据连续性</dt><dd>{{ percent("continuity") }}</dd><small>已观察期间 / 请求期间 × 100%</small></div>
          <div><dt>来自中国的份额</dt><dd>{{ percent("china_share") }}</dd><small>中国进口值 / 世界进口值 × 100%</small></div>
          <div><dt>新鲜度</dt><dd>{{ indicator("freshness")?.value_days ?? "无数据" }} 天</dd><small>查看日 - 最近观察期末</small></div>
        </dl>
        <details open>
          <summary>公式输入与原始证据</summary>
          <pre>{{ JSON.stringify(result.indicators, null, 2) }}</pre>
          <div class="evidence-list" role="region" aria-label="公开贸易证据">
            <article v-for="item in result.evidence" :key="item.id">
              <strong>HS {{ item.hs_code }} · {{ item.period }} · {{ item.partner_code === "156" ? "中国" : "世界" }}</strong>
              <span>${{ item.trade_value_usd }} · {{ item.source_dataset }} · {{ item.dataset_version || "版本未提供" }}</span>
              <a :href="item.source_url" target="_blank" rel="noopener noreferrer">查看 UN Comtrade 原始来源</a>
            </article>
          </div>
        </details>
      </div>
    </template>
  </section>
</template>

<style scoped>
.trade-evidence-panel { margin: 18px 0; border: 1px solid #cfe0ee; border-radius: 12px; background: #fbfdff; padding: 14px; }
.trade-evidence-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.trade-evidence-head h3,.trade-evidence-head p { margin: 0; }.trade-evidence-head p { margin-top: 5px; color: var(--sg-muted); font-size: .76rem; }
.demo-label { color: #8a5900; font-size: .72rem; font-weight: 850; }.trade-controls { display: grid; grid-template-columns: 1fr 1.4fr auto auto; gap: 9px; align-items: end; margin-top: 12px; }
.trade-controls label { display: grid; gap: 5px; color: var(--sg-muted); font-size: .72rem; }.trade-controls input,.trade-controls select,.trade-controls button { min-height: 40px; border: 1px solid var(--sg-line); border-radius: 8px; background: #fff; padding: 7px 10px; }.trade-controls button { cursor: pointer; color: #17699d; font-weight: 800; }.trade-controls .primary-action { color: #fff; background: #17699d; border-color: #17699d; }.trade-controls button:disabled { opacity: .55; cursor: not-allowed; }
.empty-message { display: grid; gap: 5px; color: var(--sg-muted); font-size: .78rem; }.scope-warning { color: #6b4d00; background: #fff8dd; border-radius: 8px; padding: 9px 11px; font-size: .76rem; }.validation-message { color: #9b2c2c; font-size: .76rem; }
.indicator-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }.indicator-grid div { border: 1px solid #dce8f1; border-radius: 9px; padding: 10px; background: #fff; }.indicator-grid dt,.indicator-grid small { color: var(--sg-muted); font-size: .68rem; }.indicator-grid dd { margin: 5px 0; color: var(--sg-ink); font-weight: 850; }.indicator-grid small { line-height: 1.4; }
details { margin-top: 10px; } summary { cursor: pointer; color: #17699d; font-weight: 800; font-size: .78rem; } pre { overflow: auto; max-height: 220px; background: #f4f8fb; padding: 10px; font-size: .68rem; }.evidence-list { display: grid; gap: 7px; }.evidence-list article { display: grid; grid-template-columns: 1fr 1.5fr auto; gap: 10px; padding: 9px; border-bottom: 1px solid #e2ebf2; font-size: .72rem; }.evidence-list span { color: var(--sg-muted); }.evidence-list a { color: #17699d; }
@media (max-width: 900px) { .trade-controls { grid-template-columns: 1fr 1fr; }.indicator-grid { grid-template-columns: repeat(2, 1fr); }.evidence-list article { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .trade-controls,.indicator-grid { grid-template-columns: 1fr; } }
</style>
