<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import {
  addOpportunityFollowUp,
  createOpportunityDraft,
  growthQueryKeys,
  growthWorkspaceQueryOptions,
} from "./api"

const queryClient = useQueryClient()
const workspaceQuery = useQuery(growthWorkspaceQueryOptions())
const locallyFollowed = ref(new Set<string>())
const selectedAccountId = ref<string | null>(null)
const evidenceOpen = ref(false)
const draftOpen = ref(false)
const draftText = ref("仅建议文本，不会自动发送；请先确认对方角色、当地规则和退订要求。")
const actionError = ref("")

function confidenceFor(accountId: string): number {
  return Math.max(
    ...(workspaceQuery.data.value?.intent_signals
      .filter((signal) => signal.account_id === accountId)
      .map((signal) => signal.confidence) ?? []),
    0,
  )
}

const sortedAccounts = computed(() => {
  const workspace = workspaceQuery.data.value
  if (!workspace?.target_accounts.length) return []
  return [...workspace.target_accounts].sort((left, right) => confidenceFor(right.id) - confidenceFor(left.id))
})
const activeAccount = computed(() => {
  return sortedAccounts.value.find((account) => account.id === selectedAccountId.value)
    ?? sortedAccounts.value[0]
})
const activeSignal = computed(() => workspaceQuery.data.value?.intent_signals
  .filter((signal) => signal.account_id === activeAccount.value?.id)
  .sort((left, right) => Date.parse(right.observed_at) - Date.parse(left.observed_at))[0])
const activeContact = computed(() => workspaceQuery.data.value?.contacts
  .find((contact) => contact.account_id === activeAccount.value?.id))
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
  label: activeAccount.value?.data_label ?? "Demo / Fake",
  confidence: activeSignal.value?.confidence ?? 91,
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
    draftText.value = `${draft["English draft"]} ${draft["Chinese explanation"]}`
    draftOpen.value = true
  } catch {
    actionError.value = "联系草稿暂时无法生成，请稍后重试。"
  }
}
</script>

<template>
  <div class="growth-page">
    <header class="growth-hero"><div><p class="eyebrow">客户机会</p><h1>证据化客户机会</h1><p>目标公司不是联系人，公开信号也不是已确认询盘。</p></div><span class="fake-label">Demo / Fake</span></header>
    <dl class="object-legend">
      <div><dt>目标公司</dt><dd>符合 ICP、值得研究的企业</dd></div>
      <div><dt>联系人</dt><dd>公开可验证的角色或联系路径</dd></div>
      <div><dt>需求信号</dt><dd>带时间和原始证据的变化</dd></div>
      <div><dt>入站线索</dt><dd>主动留下联系信息的人或企业</dd></div>
    </dl>
    <section v-if="sortedAccounts.length" class="growth-card opportunity-queue" aria-labelledby="opportunity-queue-title">
      <div class="growth-heading"><div><h2 id="opportunity-queue-title">今日机会队列</h2><p>按需求信号强度排序，点击公司查看证据与联系路径。</p></div><span>{{ sortedAccounts.length }} 家目标公司</span></div>
      <div class="opportunity-queue-grid">
        <button
          v-for="account in sortedAccounts" :key="account.id" type="button"
          class="opportunity-choice" :class="{ active: account.id === activeAccount?.id }"
          :aria-pressed="account.id === activeAccount?.id" @click="selectAccount(account.id)"
        >
          <span><strong>{{ account.name }}</strong><small>{{ account.country }} · {{ account.industry }}</small></span>
          <b>{{ confidenceFor(account.id) >= 80 ? "优先跟进" : confidenceFor(account.id) >= 60 ? "继续核实" : "继续观察" }} · {{ confidenceFor(account.id) }}</b>
        </button>
      </div>
    </section>
    <article class="growth-card opportunity-detail">
      <div class="opportunity-title"><div><span class="fake-label">{{ detail.label }}</span><h2>{{ detail.name }}</h2><p>{{ detail.country }} · {{ detail.industry }} · {{ detail.size }} 人</p></div><strong>{{ detail.confidence >= 80 ? "高意向" : detail.confidence >= 60 ? "中高意向" : "继续观察" }} · {{ detail.confidence }}</strong></div>
      <div class="evidence-columns">
        <section><h3>为什么现在值得跟进</h3><p>{{ detail.confidence >= 80 ? "公开信号较强，适合人工核实采购范围与时间。" : "当前证据有限，建议继续观察。" }}</p></section>
        <section><h3>需求信号</h3><p>{{ detail.signal }}</p></section>
        <section><h3>公开联系路径</h3><p>{{ detail.contact }}</p></section>
      </div>
      <div class="page-actions">
        <button class="button button-primary" type="button" :disabled="followed || followMutation.isPending.value" @click="addFollowUp">{{ followed ? "已加入跟进" : "加入跟进" }}</button>
        <button class="button button-secondary" type="button" :disabled="draftMutation.isPending.value" @click="generateDraft">{{ draftMutation.isPending.value ? "正在生成…" : "生成联系草稿" }}</button>
        <button class="button button-secondary" type="button" @click="evidenceOpen = !evidenceOpen">查看证据</button>
      </div>
      <p v-if="actionError" role="alert" class="approval-status">{{ actionError }}</p>
      <section v-if="evidenceOpen" class="evidence-detail"><h3>原始证据</h3><p>来源：{{ detail.source }} · {{ detail.evidence }}</p></section>
      <section v-if="draftOpen" class="evidence-detail"><h3>英文草稿 / 中文说明</h3><p>{{ draftText }}</p></section>
      <p class="crm-note">CRM 是人工确认后的可选出口，不是本页主操作。</p>
    </article>
  </div>
</template>
<style scoped src="./growth-pages.css"></style>
