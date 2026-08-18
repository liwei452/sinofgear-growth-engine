<script setup lang="ts">
import { computed, ref } from "vue"
import type { DiscoveryCandidate, EnrichmentCandidate, GrowthWorkspace, TargetAccount } from "./api"

type StageKey = "ALL" | "CANDIDATE" | "VERIFIED" | "ENRICHED" | "FOLLOW_UP" | "DRAFTED" | "APPROVED" | "SENT" | "REPLIED" | "DEMAND"
type AttributionRow = { id: string; kind: "ACCOUNT" | "CANDIDATE"; name: string; country: string; sources: string[]; channels: string[]; stage: StageKey | "ACCOUNT"; stageLabel: string; statusNote: string; evidence: string; eventTime: string; nextAction: string }

const props = defineProps<{ workspace: GrowthWorkspace }>()
const activeStage = ref<StageKey>("ALL")
const market = ref("ALL")
const source = ref("ALL")
const channel = ref("ALL")
const formalAccountIds = computed(() => new Set(props.workspace.target_accounts
  .filter(account => !account.is_demo).map(account => account.id)))
const formalReactivations = computed(() => (props.workspace.reactivations ?? [])
  .filter(item => !item.is_demo && formalAccountIds.value.has(item.account_id)))
const formalSignals = computed(() => props.workspace.intent_signals
  .filter(item => item.collection_method !== "DEMO_FIXTURE" && formalAccountIds.value.has(item.account_id)))
const formalProvenance = computed(() => props.workspace.field_provenance.filter(item => !item.is_demo))

const candidateMap = computed(() => {
  const result = new Map<string, DiscoveryCandidate | EnrichmentCandidate>()
  for (const item of props.workspace.discovery?.candidates ?? []) if (!item.is_demo) result.set(item.id, item)
  for (const item of props.workspace.discovery?.enrichment_candidates ?? []) if (!item.is_demo) result.set(item.id, { ...result.get(item.id), ...item } as EnrichmentCandidate)
  return result
})
const followUpIds = computed(() => new Set(props.workspace.follow_ups
  .map(item => item.account_id).filter(id => formalAccountIds.value.has(id))))
const draftIds = computed(() => new Set([
  ...props.workspace.outreach_drafts.map(item => item.account_id).filter(id => formalAccountIds.value.has(id)),
  ...formalReactivations.value.filter(item => item.draft).map(item => item.account_id),
]))
const approvedIds = computed(() => new Set([
  ...formalReactivations.value.filter(item => item.status === "APPROVED").map(item => item.account_id),
  ...(props.workspace.crm_handoffs ?? []).map(item => item.account_id).filter(id => formalAccountIds.value.has(id)),
]))
const evidenceIds = computed(() => new Set(formalSignals.value.map(item => item.account_id)))

function accountRow(account: TargetAccount): AttributionRow {
  const reactivation = formalReactivations.value.find(item => item.account_id === account.id)
  const signal = formalSignals.value.find(item => item.account_id === account.id)
  const latestEvent = reactivation?.events.at(-1)
  const channels = props.workspace.channel_packages.filter(item => item.account_id === account.id).map(item => item.channel)
  const sources = [signal?.source_label, reactivation?.relationship_source].filter((item): item is string => Boolean(item))
  const base = { id: account.id, kind: "ACCOUNT" as const, name: account.name, country: account.country, sources, channels }
  if (approvedIds.value.has(account.id)) return { ...base, stage: "APPROVED", stageLabel: "人工批准", statusNote: "已批准，尚未发送", evidence: reactivation?.evidence ?? signal?.evidence_text ?? "CRM 交接已记录", eventTime: latestEvent?.created_at ?? props.workspace.crm_handoffs?.find(item => item.account_id === account.id)?.created_at ?? "", nextAction: "人工复核后选择未来发送渠道" }
  if (draftIds.value.has(account.id)) return { ...base, stage: "DRAFTED", stageLabel: "草稿生成", statusNote: "待人工批准，尚未发送", evidence: reactivation?.evidence ?? signal?.evidence_text ?? "草稿仅引用现有账户事实", eventTime: latestEvent?.created_at ?? props.workspace.outreach_drafts.find(item => item.account_id === account.id)?.created_at ?? "", nextAction: "人工审核草稿事实与措辞" }
  if (followUpIds.value.has(account.id)) return { ...base, stage: "FOLLOW_UP", stageLabel: "加入跟进", statusNote: "尚未生成草稿", evidence: signal?.evidence_text ?? "已由人工加入跟进", eventTime: props.workspace.follow_ups.find(item => item.account_id === account.id)?.created_at ?? "", nextAction: "根据已有事实生成待审草稿" }
  if (reactivation?.tier === "OBSERVATION") return { ...base, stage: "ACCOUNT", stageLabel: "补全证据", statusNote: "证据不足，不生成触达草稿", evidence: reactivation.evidence, eventTime: latestEvent?.created_at ?? reactivation.last_interacted_at, nextAction: reactivation.recommended_action }
  return { ...base, stage: "ACCOUNT", stageLabel: "目标账户", statusNote: signal ? "已有证据信号" : "尚待补全证据", evidence: signal?.evidence_text ?? "没有已记录的账户证据", eventTime: signal?.observed_at ?? "", nextAction: signal ? "人工核实后加入跟进" : "补全公司与需求证据" }
}

function candidateRow(candidate: DiscoveryCandidate | EnrichmentCandidate): AttributionRow {
  const enriched = "latest_preview" in candidate && Boolean(candidate.latest_preview && candidate.latest_preview.mode !== "FAKE_PREVIEW")
  const accepted = candidate.status === "ACCEPTED"
  return { id: candidate.id, kind: "CANDIDATE", name: candidate.company_name, country: candidate.country, sources: [candidate.source_owner, candidate.license_contract], channels: [], stage: enriched ? "ENRICHED" : accepted ? "VERIFIED" : "CANDIDATE", stageLabel: enriched ? "资料补全" : accepted ? "人工核实" : "候选", statusNote: enriched ? "已有资料预览，尚未进入目标账户" : accepted ? "人工已接受，待补全资料" : "待人工核实", evidence: `来源所有者：${candidate.source_owner} · 使用依据：${candidate.license_contract}`, eventTime: candidate.created_at, nextAction: enriched ? "确认事实后转为目标账户" : accepted ? "准备公司资料" : "人工核实公司真实性与相关性" }
}

const rows = computed<AttributionRow[]>(() => [
  ...props.workspace.target_accounts.filter(account => !account.is_demo).map(accountRow),
  ...[...candidateMap.value.values()].map(candidateRow),
])
const countries = computed(() => [...new Set(rows.value.map(item => item.country).filter(Boolean))].sort())
const sources = computed(() => [...new Set(rows.value.flatMap(item => item.sources).filter(Boolean))].sort())
const channels = computed(() => [...new Set(rows.value.flatMap(item => item.channels).filter(Boolean))].sort())
function reachedStage(item: AttributionRow, stage: StageKey): boolean {
  if (stage === "ALL") return true
  if (stage === "CANDIDATE") return item.kind === "CANDIDATE"
  if (stage === "VERIFIED") return item.kind === "CANDIDATE" && (item.stage === "VERIFIED" || item.stage === "ENRICHED")
  if (stage === "ENRICHED") return item.kind === "CANDIDATE" && item.stage === "ENRICHED"
  if (stage === "FOLLOW_UP") return item.kind === "ACCOUNT" && followUpIds.value.has(item.id)
  if (stage === "DRAFTED") return item.kind === "ACCOUNT" && draftIds.value.has(item.id)
  if (stage === "APPROVED") return item.kind === "ACCOUNT" && approvedIds.value.has(item.id)
  return false
}
const visibleRows = computed(() => rows.value.filter(item => (market.value === "ALL" || item.country === market.value) && (source.value === "ALL" || item.sources.includes(source.value)) && (channel.value === "ALL" || item.channels.includes(channel.value)) && reachedStage(item, activeStage.value)))
const candidateCount = computed(() => candidateMap.value.size)
const verifiedCount = computed(() => [...candidateMap.value.values()].filter(item => item.status === "ACCEPTED").length)
const enrichedCount = computed(() => [...candidateMap.value.values()].filter(item => (
  "latest_preview" in item && item.latest_preview && item.latest_preview.mode !== "FAKE_PREVIEW"
)).length)
const totalAccounts = computed(() => props.workspace.target_accounts.filter(account => !account.is_demo).length)
const approvedCount = computed(() => approvedIds.value.size)
const stageItems = computed(() => [
  { key: "CANDIDATE" as const, label: "候选", value: candidateCount.value }, { key: "VERIFIED" as const, label: "人工核实", value: verifiedCount.value }, { key: "ENRICHED" as const, label: "资料补全", value: enrichedCount.value }, { key: "FOLLOW_UP" as const, label: "加入跟进", value: followUpIds.value.size }, { key: "DRAFTED" as const, label: "草稿生成", value: draftIds.value.size }, { key: "APPROVED" as const, label: "人工批准", value: approvedCount.value }, { key: "SENT" as const, label: "人工发送", value: null }, { key: "REPLIED" as const, label: "回复", value: null }, { key: "DEMAND" as const, label: "有效需求", value: null },
])
function percentage(numerator: number, denominator: number) { return denominator ? `${Math.round(numerator / denominator * 100)}%` : "无数据" }
const dataCostMicros = computed(() => formalProvenance.value.reduce((sum, item) => sum + item.source_cost_micros, 0) + formalSignals.value.reduce((sum, item) => sum + (item.evidence_envelope?.source_cost_micros ?? 0), 0))
const dataCost = computed(() => `$${(dataCostMicros.value / 1_000_000).toFixed(3)}`)
function formatTime(value: string) { return value ? new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)) : "未记录时间" }
</script>

<template>
  <section class="growth-card account-attribution" role="region" aria-labelledby="account-attribution-title">
    <div class="growth-heading"><div><p class="eyebrow">账户级归因</p><h2 id="account-attribution-title">账户获客漏斗</h2><p>只统计已保存的账户与事件。候选公司尚未转成目标账户时单独计数，不推算虚假转化率。</p></div><span>刷新后保留</span></div>
    <div class="attribution-segments"><span>许可 / 人工记录：{{ rows.length }} 条</span></div>
    <div class="attribution-funnel" aria-label="获客阶段">
      <button v-for="item in stageItems" :key="item.key" type="button" :class="{ active: activeStage === item.key }" :aria-pressed="activeStage === item.key" @click="activeStage = activeStage === item.key ? 'ALL' : item.key"><span>{{ item.label }}</span><strong>{{ item.value === null ? "尚未发生" : item.value }}</strong></button>
    </div>
    <div class="attribution-metrics" aria-label="核心指标">
      <article><span>有效账户率 {{ percentage(evidenceIds.size, totalAccounts) }}</span><small>有已记录意向证据的账户 {{ evidenceIds.size }} / 目标账户 {{ totalAccounts }}</small></article>
      <article><span>草稿批准率 {{ percentage(approvedCount, draftIds.size) }}</span><small>已批准账户 {{ approvedCount }} / 已生成草稿账户 {{ draftIds.size }}</small></article>
      <article><span>证据覆盖率 {{ percentage(evidenceIds.size, totalAccounts) }}</span><small>有来源证据账户 {{ evidenceIds.size }} / 目标账户 {{ totalAccounts }}</small></article>
      <article><span>数据成本 {{ dataCost }}</span><small>仅汇总 {{ formalProvenance.length + formalSignals.filter(item => item.evidence_envelope).length }} 条已有成本记录</small></article>
      <article><span>积极回复率 无数据</span><small>没有账户级人工发送与回复事件，暂不计算分母</small></article>
      <article><span>需求率 无数据</span><small>没有账户级有效需求事件，暂不计算分母</small></article>
    </div>
    <form class="attribution-filters" @submit.prevent>
      <label>市场<select v-model="market"><option value="ALL">全部市场</option><option v-for="item in countries" :key="item" :value="item">{{ item }}</option></select></label>
      <label>来源<select v-model="source"><option value="ALL">全部来源</option><option v-for="item in sources" :key="item" :value="item">{{ item }}</option></select></label>
      <label>渠道<select v-model="channel"><option value="ALL">全部渠道</option><option v-for="item in channels" :key="item" :value="item">{{ item }}</option></select></label>
    </form>
    <div v-if="visibleRows.length" class="attribution-records" aria-live="polite">
      <article v-for="item in visibleRows" :key="`${item.kind}-${item.id}`" :aria-label="`${item.name} ${item.kind === 'ACCOUNT' ? '归因记录' : '候选记录'}`">
        <div class="attribution-record-title"><div><small>{{ item.kind === "ACCOUNT" ? "目标账户" : "候选公司" }} · {{ item.country }}</small><h3>{{ item.name }}</h3></div><span class="verified">许可 / 人工记录</span></div>
        <dl><div><dt>当前阶段</dt><dd>{{ item.stageLabel }}</dd></div><div><dt>事件状态</dt><dd>{{ item.statusNote }}</dd></div><div><dt>证据 / 来源</dt><dd>{{ item.evidence }}</dd></div><div><dt>记录时间</dt><dd>{{ formatTime(item.eventTime) }}</dd></div></dl>
        <p><strong>系统建议下一步：</strong>{{ item.nextAction }}</p>
      </article>
    </div>
    <p v-else class="attribution-empty">当前筛选下没有已记录账户或候选证据；不会补造样例结果。</p>
    <aside class="attribution-future-note"><strong>人工发送、回复、有效需求：尚未发生 / 无数据</strong><p>当前系统不会真实发送。未来只有人工回填账户级事件后，才计算积极回复率和需求率。</p></aside>
  </section>
</template>
