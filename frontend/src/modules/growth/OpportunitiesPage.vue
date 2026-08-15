<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import {
  addOpportunityFollowUp,
  createOpportunityDraft,
  growthQueryKeys,
  growthWorkspaceQueryOptions,
  handoffOpportunityToMockCRM,
  reviewOpportunity,
} from "./api"
import ManualOpportunityImportForm from "./ManualOpportunityImportForm.vue"
import AutomaticDiscoveryCard from "./AutomaticDiscoveryCard.vue"
import CandidateListImportForm from "./CandidateListImportForm.vue"
import CandidateEnrichmentQueue from "./CandidateEnrichmentQueue.vue"
import DiscoveryCandidateQueue from "./DiscoveryCandidateQueue.vue"
import MarketPilotComparison from "./MarketPilotComparison.vue"
import ReactivationWorkbench from "./ReactivationWorkbench.vue"

const queryClient = useQueryClient()
const workspaceQuery = useQuery(growthWorkspaceQueryOptions())
const locallyFollowed = ref(new Set<string>())
const selectedAccountId = ref<string | null>(null)
const evidenceOpen = ref(false)
const draftOpen = ref(false)
const generatedDraftEnglish = ref("")
const generatedDraftChinese = ref("")
const generatedDraftId = ref("")
const actionError = ref("")
const handoffStatus = ref("")
const importOpen = ref(false)
const importStatus = ref("")
const selectedMarketName = ref("")
const marketImportOpen = ref(false)

function selectMarket(payload: { countryCode: string; countryName: string }): void {
  selectedMarketName.value = payload.countryName
  marketImportOpen.value = true
  importOpen.value = true
  window.requestAnimationFrame(() => document.getElementById("candidate-discovery-entry")?.scrollIntoView({ behavior: "smooth", block: "start" }))
}

const scoreLabels = {
  icp_fit: "ICP 匹配",
  intent_strength: "意向强度",
  recency: "信号时效",
  role_relevance: "角色相关",
  evidence_coverage: "证据覆盖",
  risk_penalty: "风险扣分",
} as const

function latestSignalFor(accountId: string) {
  return workspaceQuery.data.value?.intent_signals
    .filter((signal) => signal.account_id === accountId)
    .sort((left, right) => Date.parse(right.observed_at) - Date.parse(left.observed_at))[0]
}

function confidenceFor(accountId: string): number {
  return Math.max(
    ...(workspaceQuery.data.value?.intent_signals
      .filter((signal) => signal.account_id === accountId)
      .map((signal) => signal.confidence) ?? []),
    0,
  )
}

function priorityFor(accountId: string): "优先跟进" | "继续观察" {
  return latestSignalFor(accountId)?.priority_label ?? "继续观察"
}

function accountTierFor(accountId: string): "战略账户" | "培育账户" | "观察账户" {
  const signal = latestSignalFor(accountId)
  if (!signal) return "观察账户"
  const score = signal.score_breakdown
  if (!score) return "观察账户"
  if (score.icp_fit >= 70 && score.evidence_coverage >= 60 && score.intent_strength >= 60) return "战略账户"
  if (score.icp_fit >= 55 && signal.confidence >= 50) return "培育账户"
  return "观察账户"
}

function nextActionFor(accountId: string): { action: string; reason: string } {
  const tier = accountTierFor(accountId)
  if (tier === "战略账户") return { action: "人工深度跟进", reason: "ICP、证据覆盖与意向同时达到当前门槛" }
  if (tier === "培育账户") return { action: "进入内容培育与信号监测", reason: "客户匹配，但当前意向证据不足" }
  return { action: "AI 继续补全，暂不触达", reason: "现有数据或证据置信度不足" }
}

function formatDate(value: string | undefined): string {
  if (!value) return "时间未记录"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return "时间未记录"
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(parsed)
}

function isSafeSourceUrl(value: string | undefined): boolean {
  return Boolean(value?.startsWith("https://"))
}

function licenseLabel(value: string | undefined): string {
  const labels: Record<string, string> = {
    TED_SEARCH_API_PUBLIC_DATA: "TED 官方公开数据",
    OPEN_GOVERNMENT_LICENCE_3_0: "英国开放政府许可 3.0",
    USER_ASSERTED_PERMISSION: "用户确认有权使用",
    DEMO_FIXTURE: "演示数据",
  }
  return value ? labels[value] ?? "许可信息待核实" : "许可信息未记录"
}

function reviewStatusLabel(value: string | undefined): string {
  if (value === "PENDING_REVIEW") return "待人工审查"
  if (value === "APPROVED") return "已人工审查"
  return "审查状态未记录"
}

function sourceCostLabel(value: number | undefined): string {
  if (value === 0) return "免费公开来源"
  if (typeof value === "number") return `来源成本 ${(value / 1_000_000).toFixed(2)}`
  return "来源成本未记录"
}

function sourceTypeLabel(value: string | undefined): string {
  const labels: Record<string, string> = {
    DIRECT_CUSTOMS: "本国直接报关数据",
    CARRIER_BOL: "承运人或提单数据",
    MIRROR_TRADE: "贸易伙伴镜像推算",
    AGGREGATE_TRADE: "宏观贸易背景（非公司采购证据）",
    TENDER: "官方招投标",
    COMPANY_WEB: "企业官网或公开目录",
  }
  return value ? `${value} · ${labels[value] ?? "来源类型待核实"}` : "来源类型未记录"
}

const sortedAccounts = computed(() => {
  const workspace = workspaceQuery.data.value
  if (!workspace?.target_accounts.length) return []
  return [...workspace.target_accounts].sort((left, right) => {
    const priorityDifference = Number(priorityFor(right.id) === "优先跟进")
      - Number(priorityFor(left.id) === "优先跟进")
    return priorityDifference || confidenceFor(right.id) - confidenceFor(left.id)
  })
})
const activeAccount = computed(() => {
  return sortedAccounts.value.find((account) => account.id === selectedAccountId.value)
    ?? sortedAccounts.value[0]
})
const activeSignal = computed(() => activeAccount.value ? latestSignalFor(activeAccount.value.id) : undefined)
const activeContact = computed(() => workspaceQuery.data.value?.contacts
  .find((contact) => contact.account_id === activeAccount.value?.id))
const activeFollowUp = computed(() => workspaceQuery.data.value?.follow_ups
  .find((item) => item.account_id === activeAccount.value?.id))
const activeSavedDraft = computed(() => workspaceQuery.data.value?.outreach_drafts
  .filter((item) => item.account_id === activeAccount.value?.id)
  .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))[0])
const activeReview = computed(() => workspaceQuery.data.value?.opportunity_reviews
  ?.filter((item) => item.account_id === activeAccount.value?.id)
  .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))[0])
const activeHandoff = computed(() => workspaceQuery.data.value?.crm_handoffs
  ?.find((item) => item.account_id === activeAccount.value?.id))
const scoreItems = computed(() => {
  const breakdown = activeSignal.value?.score_breakdown
  if (!breakdown) return []
  return (Object.keys(scoreLabels) as Array<keyof typeof scoreLabels>).map((key) => ({
    key,
    label: scoreLabels[key],
    value: breakdown[key],
  }))
})
const displayedDraft = computed(() => {
  if (draftOpen.value && generatedDraftEnglish.value) {
    return {
      id: generatedDraftId.value,
      english: generatedDraftEnglish.value,
      chinese: generatedDraftChinese.value,
      createdAt: undefined,
    }
  }
  if (!activeSavedDraft.value) return null
  return {
    id: activeSavedDraft.value.id,
    english: activeSavedDraft.value.english_draft,
    chinese: activeSavedDraft.value.chinese_explanation,
    createdAt: activeSavedDraft.value.created_at,
  }
})
const followed = computed(() => Boolean(activeAccount.value && (
  locallyFollowed.value.has(activeAccount.value.id) ||
  workspaceQuery.data.value?.follow_ups.some((item) => item.account_id === activeAccount.value?.id)
)))

const detail = computed(() => ({
  id: activeAccount.value?.id ?? "packtech-demo",
  name: activeAccount.value?.name ?? "PackTech GmbH",
  country: activeAccount.value?.country === "Germany" ? "德国" : activeAccount.value?.country ?? "德国",
  industry: activeAccount.value?.industry ?? "包装机械",
  size: activeAccount.value?.employee_range ?? "51–200",
  label: activeAccount.value?.is_demo === false
    ? "许可 / 用户提供来源"
    : activeAccount.value?.data_label ?? "Demo / Fake",
  confidence: activeSignal.value?.confidence ?? 91,
  priority: activeSignal.value?.priority_label ?? "继续观察",
  signal: activeSignal.value?.evidence_text ?? "公开采购岗位：精密传动采购；发现于 2026-08-14 09:20。",
  source: activeSignal.value?.source_label ?? "公开招聘页与公司新闻页",
  evidence: activeSignal.value?.evidence_text ?? "公开招聘页与公司新闻页 · 人工导入网页快照 · 内部演示许可。",
  contact: activeContact.value
    ? `${String(activeContact.value.full_name)} · ${String(activeContact.value.role_title)}`
    : "公司官网采购联系页；未抓取 LinkedIn，未保存个人邮箱。",
}))

const followMutation = useMutation({
  mutationFn: addOpportunityFollowUp,
  onSuccess: async (_result, accountId) => {
    locallyFollowed.value = new Set([...locallyFollowed.value, accountId])
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => { actionError.value = "暂时无法加入跟进，请稍后重试。" },
})
const draftMutation = useMutation({ mutationFn: createOpportunityDraft })
const reviewMutation = useMutation({
  mutationFn: reviewOpportunity,
  onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
})
const handoffMutation = useMutation({
  mutationFn: handoffOpportunityToMockCRM,
  onSuccess: async () => {
    handoffStatus.value = "已保存到 Mock CRM，未发送任何消息。"
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
})

async function addFollowUp(): Promise<void> {
  actionError.value = ""
  if (!activeAccount.value) {
    return
  }
  await followMutation.mutateAsync(activeAccount.value.id).catch(() => undefined)
}

function selectAccount(accountId: string): void {
  selectedAccountId.value = accountId
  evidenceOpen.value = false
  draftOpen.value = false
  generatedDraftId.value = ""
  handoffStatus.value = ""
  actionError.value = ""
}

async function generateDraft(): Promise<void> {
  actionError.value = ""
  if (!activeAccount.value) {
    draftOpen.value = true
    return
  }
  try {
    const draft = await draftMutation.mutateAsync(activeAccount.value.id)
    generatedDraftId.value = draft.id
    generatedDraftEnglish.value = draft["English draft"]
    generatedDraftChinese.value = draft["Chinese explanation"]
    draftOpen.value = true
  } catch {
    actionError.value = "联系草稿暂时无法生成，请稍后重试。"
  }
}

async function saveReview(decision: "PRIORITIZE" | "OBSERVE" | "PROCESSED"): Promise<void> {
  actionError.value = ""
  handoffStatus.value = ""
  if (!activeAccount.value) return
  try {
    await reviewMutation.mutateAsync({ accountId: activeAccount.value.id, decision })
  } catch {
    actionError.value = "暂时无法保存人工判断，请稍后重试。"
  }
}

async function handoffToCRM(): Promise<void> {
  actionError.value = ""
  if (!activeAccount.value || !displayedDraft.value?.id) return
  try {
    await handoffMutation.mutateAsync({
      accountId: activeAccount.value.id,
      draftId: displayedDraft.value.id,
    })
  } catch {
    actionError.value = "交接条件尚未满足，请先确认机会与证据。"
  }
}

async function handleImported(accountId: string): Promise<void> {
  selectedAccountId.value = accountId
  evidenceOpen.value = false
  draftOpen.value = false
  generatedDraftId.value = ""
  handoffStatus.value = ""
  importOpen.value = false
  importStatus.value = ""
  await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  importStatus.value = "已保存为待核实机会；系统没有访问来源网页，也没有联系客户。"
}
</script>

<template>
  <div class="growth-page">
    <header class="growth-hero"><div><p class="eyebrow">客户机会</p><h1>证据化客户机会</h1><p>目标公司不是联系人，公开信号也不是已确认询盘。</p></div><span class="fake-label">人工审核后跟进</span></header>
    <dl class="object-legend">
      <div><dt>目标公司</dt><dd>符合 ICP、值得研究的企业</dd></div>
      <div><dt>联系人</dt><dd>公开可验证的角色或联系路径</dd></div>
      <div><dt>需求信号</dt><dd>带时间和原始证据的变化</dd></div>
      <div><dt>入站线索</dt><dd>主动留下联系信息的人或企业</dd></div>
    </dl>
    <AutomaticDiscoveryCard
      v-if="workspaceQuery.data.value?.discovery"
      :discovery="workspaceQuery.data.value.discovery"
    />
    <ReactivationWorkbench
      v-if="workspaceQuery.data.value"
      :accounts="workspaceQuery.data.value.target_accounts"
      :reactivations="workspaceQuery.data.value.reactivations ?? []"
    />
    <section id="candidate-discovery-entry" class="market-candidate-entry">
      <p v-if="selectedMarketName" class="market-selection-note"><strong>{{ selectedMarketName }}</strong> · 先导入许可名单或公开线索，再进入人工核实。</p>
      <CandidateListImportForm :open="marketImportOpen" :market-name="selectedMarketName" />
    </section>
    <DiscoveryCandidateQueue
      v-if="workspaceQuery.data.value?.discovery?.candidates?.length"
      :candidates="workspaceQuery.data.value.discovery.candidates"
    />
    <CandidateEnrichmentQueue
      v-if="workspaceQuery.data.value?.discovery?.enrichment_candidates?.length"
      :candidates="workspaceQuery.data.value.discovery.enrichment_candidates"
    />
    <MarketPilotComparison
      v-if="workspaceQuery.data.value?.market_pilots"
      :summary="workspaceQuery.data.value.market_pilots"
      @select-market="selectMarket"
    />
    <div class="opportunity-import-bar">
      <div><strong>已有公开采购线索？</strong><span>保存证据后由你决定是否跟进。</span></div>
      <button class="button button-secondary" type="button" :aria-expanded="importOpen" @click="importOpen = !importOpen">{{ importOpen ? "收起导入" : "导入公开线索" }}</button>
    </div>
    <ManualOpportunityImportForm v-if="importOpen" @imported="handleImported" @cancelled="importOpen = false" />
    <p v-if="importStatus" class="approval-status" role="status">{{ importStatus }}</p>
    <section v-if="sortedAccounts.length" class="growth-card opportunity-queue" aria-labelledby="opportunity-queue-title">
      <div class="growth-heading"><div><h2 id="opportunity-queue-title">今日机会队列</h2><p>先按证据门槛、再按信号强度排序；点击公司查看依据。</p></div><span>{{ sortedAccounts.length }} 家目标公司</span></div>
      <div class="opportunity-queue-grid">
        <button
          v-for="account in sortedAccounts" :key="account.id" type="button"
          class="opportunity-choice" :class="{ active: account.id === activeAccount?.id }"
          :aria-pressed="account.id === activeAccount?.id" @click="selectAccount(account.id)"
        >
          <span><strong>{{ account.name }}</strong><small>{{ account.country }} · {{ account.industry }} · {{ accountTierFor(account.id) }}</small></span>
          <b>{{ priorityFor(account.id) }} · {{ confidenceFor(account.id) }}</b>
        </button>
      </div>
    </section>
    <article class="growth-card opportunity-detail">
      <div class="opportunity-title"><div><span class="fake-label">{{ detail.label }}</span><h2>{{ detail.name }}</h2><p>{{ detail.country }} · {{ detail.industry }} · {{ detail.size }} 人</p></div><strong>{{ detail.priority }} · {{ detail.confidence }}</strong></div>
      <div class="evidence-columns">
        <section><h3>为什么现在值得跟进</h3><p>{{ detail.priority === "优先跟进" ? "公开信号与证据覆盖达到当前规则门槛，适合人工核实采购范围与时间。" : "当前证据仍有缺口，建议继续观察并补充核实。" }}</p></section>
        <section><h3>需求信号</h3><p>{{ detail.signal }}</p></section>
        <section><h3>公开联系路径</h3><p>{{ detail.contact }}</p></section>
      </div>
      <section class="opportunity-human-review" aria-labelledby="opportunity-review-title">
        <div>
          <h3 id="opportunity-review-title">人工判断</h3>
          <p v-if="activeReview">人工判断：{{ activeReview.status_label }}</p>
          <p v-else>AI 建议：{{ detail.priority }}</p>
          <small>每次选择都会追加记录，不会修改原始证据或 AI 评分。</small>
        </div>
        <div class="opportunity-review-actions">
          <button class="button button-secondary" type="button" :disabled="reviewMutation.isPending.value" @click="saveReview('PRIORITIZE')">确认优先跟进</button>
          <button class="button button-secondary" type="button" :disabled="reviewMutation.isPending.value" @click="saveReview('OBSERVE')">继续观察</button>
          <button class="button button-secondary" type="button" :disabled="reviewMutation.isPending.value" @click="saveReview('PROCESSED')">标记已处理</button>
        </div>
      </section>
      <section class="account-next-action">
        <h3>AI 建议下一动作</h3>
        <p><strong>{{ accountTierFor(detail.id) }} · {{ nextActionFor(detail.id).action }}</strong> · {{ nextActionFor(detail.id).reason }}</p>
        <small>账户分层综合现有价值匹配、证据覆盖和意向强度；发送仍需人工批准。</small>
      </section>
      <div class="page-actions">
        <button class="button button-primary" type="button" :disabled="followed || followMutation.isPending.value" @click="addFollowUp">{{ followed ? "已加入跟进" : "加入跟进" }}</button>
        <button class="button button-secondary" type="button" :disabled="draftMutation.isPending.value" @click="generateDraft">{{ draftMutation.isPending.value ? "正在生成…" : "生成联系草稿" }}</button>
        <button class="button button-secondary" type="button" @click="evidenceOpen = !evidenceOpen">查看证据</button>
      </div>
      <p v-if="actionError" role="alert" class="approval-status">{{ actionError }}</p>
      <section v-if="evidenceOpen" class="evidence-detail evidence-review">
        <div class="evidence-review-head">
          <div><h3>原始证据</h3><p>{{ detail.evidence }}</p></div>
          <a
            v-if="isSafeSourceUrl(activeSignal?.source_url)" class="evidence-source-link"
            :href="activeSignal?.source_url" target="_blank" rel="noopener noreferrer"
          >打开原始来源</a>
        </div>
        <dl class="evidence-metadata">
          <div><dt>来源</dt><dd>{{ detail.source }}</dd></div>
          <div><dt>发现时间</dt><dd>{{ formatDate(activeSignal?.observed_at) }}</dd></div>
          <div><dt>采集方式</dt><dd>{{ activeSignal?.collection_method_label || "采集方式未说明" }}</dd></div>
          <div v-if="activeSignal?.evidence_envelope"><dt>许可与使用</dt><dd>{{ licenseLabel(activeSignal.evidence_envelope.license_contract) }}</dd></div>
          <div v-if="activeSignal?.evidence_envelope"><dt>审查状态</dt><dd>{{ reviewStatusLabel(activeSignal.evidence_envelope.review_status) }}</dd></div>
          <div v-if="activeSignal?.evidence_envelope"><dt>来源成本</dt><dd>{{ sourceCostLabel(activeSignal.evidence_envelope.source_cost_micros) }}</dd></div>
          <div v-if="activeSignal?.evidence_envelope?.source_type"><dt>证据来源类型</dt><dd>{{ sourceTypeLabel(activeSignal.evidence_envelope.source_type) }}</dd></div>
          <div v-if="activeSignal?.evidence_envelope?.matched_keywords"><dt>命中关键词</dt><dd>{{ activeSignal.evidence_envelope.matched_keywords.join("、") || "未命中产品关键词" }}</dd></div>
          <div v-if="activeSignal?.evidence_envelope?.company_match_confidence !== undefined"><dt>企业匹配置信度</dt><dd>{{ activeSignal.evidence_envelope.company_match_confidence }}%</dd></div>
          <div v-if="activeSignal?.evidence_envelope?.ai_exclusion_reasons"><dt>AI 排除理由</dt><dd>{{ activeSignal.evidence_envelope.ai_exclusion_reasons.join("；") || "无 AI 排除项" }}</dd></div>
          <div v-if="activeSignal?.evidence_envelope?.screenshot_reference">
            <dt>截图证据</dt>
            <dd>{{ activeSignal.evidence_envelope.screenshot_reference.file_name }} · {{ formatDate(activeSignal.evidence_envelope.screenshot_reference.captured_at) }}（仅元数据）</dd>
          </div>
          <div><dt>评分规则</dt><dd>{{ activeSignal?.scoring_rule_version || "规则版本未记录" }}</dd></div>
          <div><dt>证据哈希</dt><dd><code>{{ activeSignal?.content_hash ? `${activeSignal.content_hash.slice(0, 12)}…` : "未记录" }}</code></dd></div>
        </dl>
        <h3>评分依据</h3>
        <div v-if="scoreItems.length" class="opportunity-score-grid">
          <span v-for="item in scoreItems" :key="item.key">{{ item.label }} {{ item.value }}</span>
        </div>
        <p v-else>评分明细暂缺，不能仅凭总分判断。</p>
        <div class="uncertainty-list">
          <h4>仍需确认</h4>
          <ul v-if="activeSignal?.uncertainty_notes?.length">
            <li v-for="note in activeSignal?.uncertainty_notes ?? []" :key="note">{{ note }}</li>
          </ul>
          <p v-else>暂未记录不确定项，仍需人工复核原始来源。</p>
        </div>
      </section>
      <section v-if="activeFollowUp || displayedDraft" class="evidence-detail follow-up-timeline">
        <h3>跟进记录</h3>
        <p v-if="activeFollowUp">{{ formatDate(activeFollowUp.created_at) }} · 已加入跟进</p>
        <div v-if="displayedDraft" class="saved-draft">
          <div><span class="fake-label">从未发送</span><small>{{ displayedDraft.createdAt ? formatDate(displayedDraft.createdAt) : "刚刚生成" }}</small></div>
          <h4>英文建议</h4><p>{{ displayedDraft.english }}</p>
          <h4>中文解释</h4><p>{{ displayedDraft.chinese }}</p>
          <button
            v-if="activeReview?.decision === 'PRIORITIZE' && !activeHandoff"
            class="button button-secondary"
            type="button"
            :disabled="handoffMutation.isPending.value"
            @click="handoffToCRM"
          >
            {{ handoffMutation.isPending.value ? "正在保存…" : "确认草稿并交给 Mock CRM" }}
          </button>
        </div>
      </section>
      <p v-if="handoffStatus || activeHandoff" class="approval-status" role="status">{{ handoffStatus || "已保存到 Mock CRM，未发送任何消息。" }}</p>
      <p class="crm-note">CRM 是人工确认后的可选出口，不是本页主操作。</p>
    </article>
  </div>
</template>
<style scoped src="./growth-pages.css"></style>
<style scoped>
.market-selection-note { margin: 0 0 10px; border-radius: 10px; background: #edf6fd; padding: 10px 12px; color: #24516f; font-size: .8rem; }
.account-next-action { margin-top: 14px; border-radius: 10px; background: #f1f6fa; padding: 12px; }.account-next-action h3 { margin: 0 0 6px; }.account-next-action p { margin: 0; color: #304a61; }.account-next-action small { display: block; margin-top: 6px; color: var(--sg-muted); }
</style>
