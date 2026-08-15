<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"
import { RouterLink } from "vue-router"

import {
  addOpportunityFollowUp,
  createOpportunityDraft,
  growthQueryKeys,
  growthWorkspaceQueryOptions,
} from "../growth/api"

type Opportunity = {
  id: string
  company: string
  country: string
  profile: string
  need: string
  summary: string
  source: string
  discovered: string
  intent: string
  evidence: string
  dataLabel: string
}

const queryClient = useQueryClient()
const workspaceQuery = useQuery(growthWorkspaceQueryOptions())
const locallyFollowed = ref(new Set<string>())
const actionError = ref("")
const draftFor = ref<{
  opportunity: Opportunity
  englishDraft: string
  chineseExplanation: string
} | null>(null)
const evidenceFor = ref(new Set<string>())

const countryLabels: Record<string, string> = {
  Germany: "德国", Italy: "意大利", Sweden: "瑞典", China: "中国", USA: "美国",
}
const channelLabels: Record<string, string> = {
  LINKEDIN: "LinkedIn", FACEBOOK: "Facebook", INSTAGRAM: "Instagram", TIKTOK: "TikTok", YOUTUBE: "YouTube",
}

function isDemoLabel(value: string | undefined): boolean {
  return /demo|fake/i.test(value ?? "")
}

function recordedNumber(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key]
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null
}

const opportunities = computed<Opportunity[]>(() => {
  const workspace = workspaceQuery.data.value
  if (!workspace?.target_accounts.length) return []
  return workspace.target_accounts.filter((account) => !account.is_demo).flatMap((account) => {
    const signal = workspace.intent_signals
      .filter((candidate) => candidate.account_id === account.id && !isDemoLabel(candidate.data_label))
      .sort((left, right) => Date.parse(right.observed_at) - Date.parse(left.observed_at))[0]
    if (!signal) return []
    const confidence = signal?.confidence ?? 0
    return [{
      id: account.id,
      company: account.name,
      country: countryLabels[account.country] ?? account.country,
      profile: [account.industry || "行业待确认", account.employee_range ? `${account.employee_range} 人` : "规模待确认"].join(" · "),
      need: signal.evidence_text,
      summary: confidence >= 80
        ? "公开信号较强，建议人工核实采购范围、批量与时间。"
        : "当前证据有限，建议继续观察并补充可验证信息。",
      source: signal.source_label,
      discovered: new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(signal.observed_at)),
      intent: confidence >= 80 ? "高意向" : confidence >= 60 ? "中高意向" : "继续观察",
      evidence: signal.evidence_text,
      dataLabel: signal.data_label || account.data_label,
    }]
  })
})
const channelMetrics = computed(() => {
  const receipts = (workspaceQuery.data.value?.metric_receipts ?? []).filter(receipt => !receipt.is_demo)
  const seen = new Set<string>()
  return receipts.flatMap((receipt) => {
    if (seen.has(receipt.channel)) return []
    seen.add(receipt.channel)
    const candidates = [
      ["播放或访问", recordedNumber(receipt.payload, "views")],
      ["点击", recordedNumber(receipt.payload, "clicks")],
      ["回复", recordedNumber(receipt.payload, "replies")],
      ["询盘", recordedNumber(receipt.payload, "inquiries")],
    ] as const
    const metric = candidates.find(([, value]) => value !== null)
    if (!metric) return []
    return [{ name: channelLabels[receipt.channel] ?? receipt.channel, metric: metric[0], value: metric[1] as number }]
  })
})

const persistedFollowed = computed(() => new Set(
  (workspaceQuery.data.value?.follow_ups ?? []).map((item) => item.account_id),
))

function isFollowed(id: string): boolean {
  return locallyFollowed.value.has(id) || persistedFollowed.value.has(id)
}

const followUpMutation = useMutation({
  mutationFn: addOpportunityFollowUp,
  onSuccess: async (_result, accountId) => {
    locallyFollowed.value = new Set([...locallyFollowed.value, accountId])
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => { actionError.value = "暂时无法加入跟进，请稍后重试。" },
})

const draftMutation = useMutation({ mutationFn: createOpportunityDraft })

async function addFollowUp(id: string): Promise<void> {
  actionError.value = ""
  if (!workspaceQuery.data.value?.target_accounts.some((account) => account.id === id && !account.is_demo)) return
  await followUpMutation.mutateAsync(id).catch(() => undefined)
}

async function generateDraft(opportunity: Opportunity): Promise<void> {
  actionError.value = ""
  if (!workspaceQuery.data.value?.target_accounts.some((account) => account.id === opportunity.id && !account.is_demo)) return
  try {
    const draft = await draftMutation.mutateAsync(opportunity.id)
    draftFor.value = {
      opportunity,
      englishDraft: draft["English draft"],
      chineseExplanation: draft["Chinese explanation"],
    }
  } catch {
    actionError.value = "联系草稿暂时无法生成，请稍后重试。"
  }
}

function toggleEvidence(id: string) {
  const next = new Set(evidenceFor.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  evidenceFor.value = next
}
</script>

<template>
  <div class="today-page">
    <header class="today-intro">
      <div>
        <p class="eyebrow">今天</p>
        <h1>早上好，SinofGear 团队</h1>
        <p>这里仅显示已保存并可追溯的采购机会、公司事实和渠道反馈。</p>
      </div>
    </header>

    <p v-if="workspaceQuery.isPending.value" class="workspace-state" role="status">正在读取可持久化工作区…</p>
    <p v-else-if="workspaceQuery.isError.value" class="workspace-state" role="alert">暂时无法读取工作区，请稍后重试；页面不会使用演示数据替代。</p>
    <p v-if="actionError" class="workspace-state action-error" role="alert">{{ actionError }}</p>

    <div class="today-grid">
      <section class="workspace-card opportunities-panel" aria-labelledby="today-opportunities">
        <div class="panel-heading">
          <div>
            <h2 id="today-opportunities">今天发现的采购机会</h2>
            <p>按证据完整度和当前需求排序，不等同于已确认采购。</p>
          </div>
          <RouterLink to="/opportunities">查看全部</RouterLink>
        </div>

        <div v-if="opportunities.length" class="opportunity-list">
          <article
            v-for="opportunity in opportunities"
            :key="opportunity.id"
            class="opportunity-card"
            :aria-label="`${opportunity.company} 采购机会`"
          >
            <div class="company-block">
              <span class="company-avatar" aria-hidden="true">{{ opportunity.company.slice(0, 1) }}</span>
              <strong>{{ opportunity.company }}</strong>
              <span>{{ opportunity.country }}</span>
              <span>{{ opportunity.profile }}</span>
            </div>
            <div class="signal-block">
              <div class="signal-topline">
                <span class="demo-badge">{{ opportunity.dataLabel }}</span>
                <span class="intent-badge">{{ opportunity.intent }}</span>
              </div>
              <h3>{{ opportunity.need }}</h3>
              <p>{{ opportunity.summary }}</p>
              <dl class="signal-meta">
                <div><dt>信号来源</dt><dd>{{ opportunity.source }}</dd></div>
                <div><dt>发现时间</dt><dd>{{ opportunity.discovered }}</dd></div>
              </dl>
              <div class="opportunity-actions">
                <button
                  class="button button-primary"
                  type="button"
                  :disabled="isFollowed(opportunity.id) || followUpMutation.isPending.value"
                  @click="addFollowUp(opportunity.id)"
                >
                  {{ isFollowed(opportunity.id) ? "已加入跟进" : "加入跟进" }}
                </button>
                <button
                  class="button button-secondary" type="button"
                  :disabled="draftMutation.isPending.value" @click="generateDraft(opportunity)"
                >
                  {{ draftMutation.isPending.value ? "正在生成…" : "生成联系草稿" }}
                </button>
                <button class="evidence-button" type="button" @click="toggleEvidence(opportunity.id)">
                  {{ evidenceFor.has(opportunity.id) ? "收起证据" : "查看证据" }}
                </button>
              </div>
              <div
                v-if="evidenceFor.has(opportunity.id)"
                class="evidence-box"
                role="region"
                :aria-label="`${opportunity.company} 原始证据`"
              >
                <strong>原始证据摘要</strong>
                <p>{{ opportunity.evidence }}</p>
                <p>完整来源、观察时间与许可信息请在客户机会页复核。</p>
              </div>
            </div>
          </article>
        </div>
        <div v-else class="workspace-empty">
          <h3>今天还没有已验证的采购机会</h3>
          <p>只有带真实来源与观察时间、并通过人工核实的需求信号才会出现在这里。</p>
          <RouterLink class="button button-primary" to="/opportunities">选择市场或导入合法名单</RouterLink>
        </div>
      </section>

      <div class="insight-column">
        <section class="workspace-card visibility-panel" aria-labelledby="visibility-title">
          <div class="panel-heading">
            <div>
              <h2 id="visibility-title">AI 品牌与搜索曝光</h2>
              <p>评分可解释，不代表搜索平台官方排名。</p>
            </div>
          </div>
          <div class="workspace-empty">
            <h3>还没有真实 AI 可见度监测记录</h3>
            <p>该实验模块需要完整回答、平台、模型、地区、引用 URL 和观察时间；没有记录时不生成评分。</p>
            <RouterLink class="button button-primary button-block" to="/company">补充公司事实</RouterLink>
          </div>
        </section>

        <section class="workspace-card channels-panel" aria-labelledby="channel-performance">
          <div class="panel-heading">
            <div>
              <h2 id="channel-performance">渠道表现</h2>
              <p>只显示人工保存的真实渠道结果。</p>
            </div>
          </div>
          <div v-if="channelMetrics.length" class="channel-grid">
            <article v-for="channel in channelMetrics" :key="channel.name" :aria-label="`${channel.name} 渠道表现`">
              <strong>{{ channel.name }}</strong>
              <p>{{ channel.metric }} <b>{{ channel.value.toLocaleString() }}</b></p>
            </article>
          </div>
          <div v-else class="workspace-empty">
            <h3>还没有人工回填的渠道结果</h3>
            <p>发布、点击、回复和询盘只有在人工保存后才会展示。</p>
            <RouterLink class="button button-primary" to="/analytics">回填渠道结果</RouterLink>
          </div>
        </section>
      </div>
    </div>

    <div v-if="draftFor" class="modal-backdrop" @click.self="draftFor = null">
      <section class="draft-dialog" role="dialog" aria-modal="true" aria-labelledby="draft-title">
        <span class="demo-badge">{{ draftFor.opportunity.dataLabel }}</span>
        <h2 id="draft-title">联系草稿</h2>
        <p class="safe-note">草稿不会自动发送，请人工核对事实和联系人后再自行使用。</p>
        <h3>English draft</h3>
        <p>{{ draftFor.englishDraft }}</p>
        <h3>中文说明</h3>
        <p>{{ draftFor.chineseExplanation }}</p>
        <button class="button button-secondary" type="button" @click="draftFor = null">关闭</button>
      </section>
    </div>
  </div>
</template>

<style scoped>
.today-page { display: grid; gap: 22px; }
.today-intro, .panel-heading, .signal-topline, .opportunity-actions { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.today-intro h1 { margin: 0; font-size: clamp(1.65rem, 3vw, 2.35rem); }
.today-intro p:last-child, .panel-heading p { margin: 7px 0 0; color: var(--sg-muted); }
.demo-badge, .intent-badge { display: inline-flex; border-radius: 999px; padding: 5px 9px; font-size: .72rem; font-weight: 800; white-space: nowrap; }
.demo-badge { background: #eef2f6; color: #4f5d6c; }
.intent-badge { background: #e7f8ed; color: #14733c; }
.today-grid { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(430px, .92fr); gap: 22px; align-items: start; }
.workspace-card { border: 1px solid var(--sg-line); border-radius: 14px; background: white; padding: 22px; box-shadow: 0 3px 16px rgb(23 34 49 / 4%); }
.workspace-empty { display: grid; gap: 10px; justify-items: start; border: 1px dashed var(--sg-line); border-radius: 12px; padding: 20px; background: #fbfcfd; }
.workspace-empty h3, .workspace-empty p { margin: 0; }.workspace-empty p { color: var(--sg-muted); line-height: 1.6; }
.panel-heading { align-items: flex-start; border-bottom: 1px solid var(--sg-line); padding-bottom: 16px; }
.panel-heading h2 { margin: 0; font-size: 1.1rem; }
.panel-heading a { color: var(--sg-brand); font-weight: 750; text-decoration: none; }
.opportunity-list, .insight-column { display: grid; gap: 16px; }
.opportunity-list { margin-top: 16px; }
.opportunity-card { display: grid; grid-template-columns: 150px 1fr; gap: 20px; border: 1px solid var(--sg-line); border-radius: 12px; padding: 18px; }
.company-block { display: grid; align-content: start; gap: 6px; border-right: 1px solid var(--sg-line); padding-right: 18px; color: var(--sg-muted); font-size: .82rem; }
.company-block strong { color: var(--sg-ink); font-size: .95rem; }
.company-avatar { display: grid; width: 44px; height: 44px; place-items: center; margin-bottom: 6px; border-radius: 50%; background: var(--sg-brand-soft); color: var(--sg-brand); font-weight: 900; }
.signal-block h3 { margin: 12px 0 8px; font-size: 1rem; }
.signal-block > p { margin: 0; color: var(--sg-muted); line-height: 1.6; }
.signal-meta { display: flex; flex-wrap: wrap; gap: 18px; margin: 14px 0; }
.signal-meta div { display: grid; gap: 3px; }
.signal-meta dt { color: var(--sg-muted); font-size: .72rem; }
.signal-meta dd { margin: 0; font-size: .82rem; font-weight: 700; }
.opportunity-actions { justify-content: flex-start; flex-wrap: wrap; }
.evidence-button { min-height: 44px; border: 0; background: transparent; color: var(--sg-brand); font-weight: 750; cursor: pointer; }
.evidence-box { margin-top: 14px; border-left: 3px solid var(--sg-brand); border-radius: 6px; background: #f6f9fc; padding: 12px 14px; }
.evidence-box p { margin: 5px 0 0; font-size: .82rem; line-height: 1.55; }
.visibility-score { display: grid; grid-template-columns: 150px 1fr; gap: 20px; align-items: center; padding: 20px 0; }
.visibility-score > strong { color: #0c9b5e; font-size: 2.6rem; }
.visibility-score > strong span { color: var(--sg-muted); font-size: 1rem; }
.visibility-score p { margin: 6px 0 0; color: var(--sg-muted); line-height: 1.5; }
.knowledge-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 16px; }
.knowledge-grid section { border: 1px solid var(--sg-line); border-radius: 10px; padding: 12px; }
.knowledge-grid h3 { margin: 0; font-size: .9rem; }
.knowledge-grid ul { margin: 10px 0 0; padding-left: 18px; color: var(--sg-muted); font-size: .8rem; line-height: 1.6; }
.safe-note { margin: 9px 0 0; color: var(--sg-muted); font-size: .8rem; text-align: center; }
.channel-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 9px; margin-top: 16px; }
.channel-grid article { min-width: 0; border: 1px solid var(--sg-line); border-radius: 10px; padding: 11px; }
.channel-grid article > strong { font-size: .8rem; }
.channel-grid p { margin: 10px 0 4px; color: var(--sg-muted); font-size: .72rem; }
.channel-grid p b { display: block; margin-top: 3px; color: var(--sg-ink); font-size: 1rem; }
.channel-grid article > span { color: #0c8a55; font-size: .75rem; font-weight: 800; }
.sparkline { display: flex; height: 24px; align-items: end; gap: 3px; margin-top: 7px; }
.sparkline i { flex: 1; border-radius: 2px 2px 0 0; background: #a9cdf1; }
.sparkline i:nth-child(1) { height: 25%; } .sparkline i:nth-child(2) { height: 50%; } .sparkline i:nth-child(3) { height: 38%; } .sparkline i:nth-child(4) { height: 78%; } .sparkline i:nth-child(5) { height: 62%; }
.modal-backdrop { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; background: rgb(17 31 47 / 48%); padding: 20px; }
.draft-dialog { width: min(100%, 620px); max-height: 90vh; overflow-y: auto; border-radius: 14px; background: white; padding: 26px; box-shadow: var(--sg-shadow); }
.draft-dialog h2 { margin: 10px 0 0; }.draft-dialog h3 { margin: 20px 0 6px; font-size: .95rem; }.draft-dialog p { line-height: 1.65; }.draft-dialog .safe-note { text-align: left; }
@media (max-width: 1180px) { .today-grid { grid-template-columns: 1fr; }.opportunities-panel { order: 1; }.insight-column { order: 2; } }
@media (max-width: 680px) { .today-intro, .panel-heading { align-items: flex-start; flex-direction: column; }.workspace-card { padding: 16px; }.opportunity-card { grid-template-columns: 1fr; }.company-block { grid-template-columns: auto 1fr; border-right: 0; border-bottom: 1px solid var(--sg-line); padding: 0 0 14px; }.company-avatar { grid-row: span 3; }.knowledge-grid { grid-template-columns: 1fr; }.channel-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
