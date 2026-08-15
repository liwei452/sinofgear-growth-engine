<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import { createWatchMarket, growthQueryKeys, watchMarket, type MarketPilotSummary } from "./api"

const props = defineProps<{ summary: MarketPilotSummary }>()
const emit = defineEmits<{ selectMarket: [payload: { countryCode: string; countryName: string }] }>()
const queryClient = useQueryClient()
const search = ref("")
const region = ref("ALL")
const pathFamily = ref("ALL")
const availability = ref("ALL")
const sortBy = ref("RECOMMENDED")
const watchedCodes = ref(new Set<string>())
const watchingCode = ref("")
const countryLabel = ref("")
const countryCode = ref("")
const selectedPath = ref<"CUSTOMS_STRONG" | "MIXED_ACQUISITION">("MIXED_ACQUISITION")
const createStatus = ref("")
const createError = ref("")

const formalMarkets = computed(() => props.summary.markets.filter(market => !market.is_demo))
const activeMarkets = computed(() => formalMarkets.value.filter(market => market.status === "ACTIVE_MARKET"))
const candidateMarkets = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  const filtered = formalMarkets.value.filter(market => (
    market.status !== "ACTIVE_MARKET"
    && (!query || `${market.country_label} ${market.country_code}`.toLocaleLowerCase().includes(query))
    && (region.value === "ALL" || market.region === region.value)
    && (pathFamily.value === "ALL" || market.path_family === pathFamily.value)
    && (availability.value === "ALL" || market.data_availability_label?.startsWith(availability.value))
  ))
  return [...filtered].sort((left, right) => {
    if (sortBy.value === "NAME") return left.country_label.localeCompare(right.country_label, "zh-CN")
    if (sortBy.value === "WATCHED") return Number(isWatched(right)) - Number(isWatched(left))
    return formalMarkets.value.indexOf(left) - formalMarkets.value.indexOf(right)
  })
})

const regions = computed(() => [...new Set(formalMarkets.value.map(market => market.region).filter(Boolean))])
const hasScoredMarkets = computed(() => formalMarkets.value.some(market => (
  Object.values(market.scores ?? {}).some(value => typeof value === "number")
)))

const mutation = useMutation({
  mutationFn: watchMarket,
  onSuccess: async (result) => {
    watchedCodes.value = new Set([...watchedCodes.value, result.country_code])
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
})

const createMutation = useMutation({
  mutationFn: createWatchMarket,
  onSuccess: async (result) => {
    createStatus.value = "已加入观察市场，下一步导入真实候选公司。"
    createError.value = ""
    watchedCodes.value = new Set([...watchedCodes.value, result.market.country_code])
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
    emit("selectMarket", {
      countryCode: result.market.country_code,
      countryName: result.market.country_label,
    })
  },
  onError: () => {
    createStatus.value = ""
    createError.value = "观察市场没有保存成功，请检查国家代码后重试。"
  },
})

function isWatched(market: MarketPilotSummary["markets"][number]): boolean {
  return Boolean(market.is_watched || watchedCodes.value.has(market.country_code))
}

function addWatch(countryCode: string): void {
  watchingCode.value = countryCode
  mutation.mutate(countryCode)
}

function createUserMarket(): void {
  createStatus.value = ""
  createError.value = ""
  createMutation.mutate({
    countryCode: countryCode.value,
    countryLabel: countryLabel.value,
    pathFamily: selectedPath.value,
  })
}

function rateLabel(value: number | null): string { return value === null ? "待采样" : `${value.toFixed(1)}%` }
function costLabel(value: number): string { return `¥${(value / 1_000_000).toFixed(2)}` }
function routeFamilyLabel(value?: string): string { return value === "CUSTOMS_STRONG" ? "海关强数据" : "混合获客" }
function regionLabel(value?: string): string {
  return { NORTH_AMERICA: "北美", EUROPE: "欧洲", SOUTHEAST_ASIA: "东南亚", AFRICA: "非洲", LATIN_AMERICA: "拉美", OTHER: "其他" }[value ?? "OTHER"] ?? "其他"
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
        <p v-if="market.evidence_note" class="active-market-note">{{ market.evidence_note }}</p>
        <dl class="active-market-meta">
          <div><dt>适合行业</dt><dd>{{ market.suitable_industries?.join("、") || "待真实样本验证" }}</dd></div>
          <div><dt>数据可得性</dt><dd>{{ market.data_availability_label || "待验证" }}</dd></div>
          <div><dt>推荐下一动作</dt><dd>{{ market.recommended_action || "进入候选导入" }}</dd></div>
          <div><dt>风险</dt><dd>{{ market.hold_reasons.join("；") }}</dd></div>
        </dl>
        <div class="market-card-actions">
          <button v-if="!isWatched(market)" class="market-watch-button" type="button" :disabled="mutation.isPending.value && watchingCode === market.country_code" @click="addWatch(market.country_code)">加入观察市场</button>
          <span v-else class="watched-label">已观察</span>
          <button class="market-candidate-link" type="button" @click="emit('selectMarket', { countryCode: market.country_code, countryName: market.country_label })">查看该市场候选公司</button>
        </div>
      </article>
    </div>
    <p v-if="!activeMarkets.length" class="market-empty">当前没有已验证的活跃市场。请先导入有许可的市场名单或公开线索，再用真实样本评估。</p>

    <div class="market-radar-head">
      <h3>市场雷达</h3>
      <p><strong>发现更多适合的海外市场。</strong> 海关强数据走许可交易数据/名单；混合获客使用贸易背景、企业目录/官网和公开招投标。</p>
      <p v-if="hasScoredMarkets">数据可获得性 25% · 需求强度 25% · 采购意图 20% · 企业可触达性 15% · 商业可执行性 15%</p>
    </div>
    <form v-if="!formalMarkets.length" class="market-create-form" @submit.prevent="createUserMarket">
      <div>
        <h4>加入真实观察市场</h4>
        <p>这里只记录你的选择，不生成市场评分、需求结论或虚拟客户。</p>
      </div>
      <label>国家或地区<input v-model.trim="countryLabel" aria-label="国家或地区" required maxlength="96" placeholder="例如：德国"></label>
      <label>ISO 国家代码<input v-model.trim="countryCode" aria-label="ISO 国家代码" required minlength="2" maxlength="3" pattern="[A-Za-z]{2,3}" placeholder="例如：DEU"></label>
      <label>获客路径<select v-model="selectedPath" aria-label="获客路径"><option value="MIXED_ACQUISITION">混合公开信号</option><option value="CUSTOMS_STRONG">许可交易数据</option></select></label>
      <button class="button button-primary" type="submit" :disabled="createMutation.isPending.value">{{ createMutation.isPending.value ? "正在保存…" : "加入观察市场" }}</button>
      <p v-if="createStatus" class="approval-status" role="status">{{ createStatus }}</p>
      <p v-if="createError" class="manual-import-error" role="alert">{{ createError }}</p>
    </form>
    <div class="market-filters">
      <label>搜索国家<input v-model="search" type="search" aria-label="搜索国家" placeholder="输入国家名称"></label>
      <label>区域<select v-model="region" aria-label="按区域筛选"><option value="ALL">全部区域</option><option v-for="item in regions" :key="item" :value="item">{{ regionLabel(item) }}</option></select></label>
      <label>获客路径<select v-model="pathFamily" aria-label="按获客路径筛选"><option value="ALL">全部路径</option><option value="CUSTOMS_STRONG">海关强数据</option><option value="MIXED_ACQUISITION">混合获客</option></select></label>
      <label>数据可得性<select v-model="availability" aria-label="按数据可得性筛选"><option value="ALL">全部</option><option value="高">高</option><option value="中高">中高</option><option value="中">中</option><option value="中低">中低</option><option value="待验证">待验证</option></select></label>
      <label>排序<select v-model="sortBy" aria-label="市场排序"><option value="RECOMMENDED">推荐顺序</option><option value="WATCHED">已观察优先</option><option value="NAME">国家名称</option></select></label>
    </div>

    <div class="market-workbench-grid">
      <article v-for="market in candidateMarkets" :key="market.country_code" class="market-workbench-card" :aria-label="`${market.country_label} ${market.route_label}`">
        <header><div><h4>{{ market.country_label }} · {{ market.recommended_wave }}</h4></div><b>{{ routeFamilyLabel(market.path_family) }}</b></header>
        <p class="market-worth"><strong>为什么值得看</strong> {{ market.recommendation_reasons.join("；") || "尚未形成推荐结论；由你主动加入观察。" }}</p>
        <dl>
          <div><dt>适合行业</dt><dd>{{ market.suitable_industries?.join("、") || "待真实样本验证" }}</dd></div>
          <div><dt>数据可得性</dt><dd>{{ market.data_availability_label || "待验证" }}</dd></div>
          <div><dt>证据来源 / 时间</dt><dd>{{ market.evidence_note || "研究配置；尚无实时数据" }} · {{ market.last_updated_at }}</dd></div>
          <div><dt>推荐下一动作</dt><dd>{{ market.recommended_action || "进入候选导入" }}</dd></div>
          <div><dt>风险</dt><dd>{{ market.hold_reasons.join("；") }}</dd></div>
        </dl>
        <div class="market-card-actions">
          <button v-if="!isWatched(market)" class="market-watch-button" type="button" @click="addWatch(market.country_code)">加入观察市场</button>
          <span v-else class="watched-label">已观察</span>
          <button class="market-candidate-link" type="button" @click="emit('selectMarket', { countryCode: market.country_code, countryName: market.country_label })">查看该市场候选公司</button>
        </div>
      </article>
    </div>
    <p v-if="!candidateMarkets.length" class="market-empty">当前没有已保存的候选市场。请从上方入口导入合法名单或公开线索。</p>
  </section>
</template>

<style scoped src="./growth-pages.css"></style>
<style scoped>
.market-radar-head { margin-top: 20px; }.market-filters { display: grid; grid-template-columns: 1.3fr repeat(4, 1fr); gap: 9px; margin: 14px 0; }.market-filters label { display: grid; gap: 5px; color: var(--sg-muted); font-size: .72rem; }.market-filters input, .market-filters select { min-height: 40px; border: 1px solid var(--sg-line); border-radius: 8px; background: #fff; padding: 7px 9px; color: var(--sg-ink); }.market-workbench-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }.market-workbench-card { border: 1px solid #d8e6f2; border-radius: 12px; background: #fbfdff; padding: 14px; }.market-workbench-card header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.market-workbench-card h4 { margin: 5px 0 0; font-size: 1rem; }.market-workbench-card header b { color: #17699d; font-size: .76rem; }.demo-market-label { color: #8a5900; font-size: .68rem; font-weight: 850; }.market-worth { color: #304a61; font-size: .79rem; line-height: 1.5; }.market-workbench-card dl, .active-market-meta { display: grid; gap: 7px; margin: 0; }.market-workbench-card dl div, .active-market-meta div { display: grid; grid-template-columns: 95px 1fr; gap: 8px; }.market-workbench-card dt, .active-market-meta dt { color: var(--sg-muted); font-size: .7rem; }.market-workbench-card dd, .active-market-meta dd { margin: 0; color: #354e64; font-size: .74rem; line-height: 1.45; }.active-market-meta { margin-top: 9px; }.market-card-actions { display: flex; align-items: center; gap: 12px; margin-top: 12px; }.market-candidate-link, .market-watch-button { border: 0; background: transparent; padding: 0; color: #17699d; font: inherit; font-size: .76rem; font-weight: 850; cursor: pointer; }.market-watch-button { color: #526579; }.watched-label { color: #24704a; font-size: .75rem; font-weight: 850; }.active-market-note, .market-empty { color: var(--sg-muted); font-size: .74rem; }
.market-create-form { display: grid; grid-template-columns: 1.2fr 1fr .75fr 1fr auto; align-items: end; gap: 10px; margin: 14px 0; border: 1px solid #cfe0ee; border-radius: 12px; background: #f8fbfe; padding: 14px; }.market-create-form h4,.market-create-form p { margin: 0; }.market-create-form > div p { margin-top: 5px; color: var(--sg-muted); font-size: .72rem; line-height: 1.45; }.market-create-form label { display: grid; gap: 5px; color: var(--sg-muted); font-size: .72rem; }.market-create-form input,.market-create-form select { min-height: 42px; border: 1px solid var(--sg-line); border-radius: 8px; background: #fff; padding: 8px 10px; }.market-create-form .approval-status,.market-create-form .manual-import-error { grid-column: 1 / -1; }
@media (max-width: 1100px) { .market-create-form { grid-template-columns: repeat(2, 1fr); }.market-create-form > div,.market-create-form .approval-status,.market-create-form .manual-import-error { grid-column: 1 / -1; } }
@media (max-width: 900px) { .market-filters { grid-template-columns: repeat(2, 1fr); }.market-workbench-grid { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .market-filters { grid-template-columns: 1fr; } }
</style>
