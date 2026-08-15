<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query"
import { computed, ref, watch } from "vue"

import {
  approveReactivationDraft,
  createReactivationDraft,
  growthQueryKeys,
  selectReactivation,
  type Reactivation,
  type TargetAccount,
} from "./api"

const props = defineProps<{ accounts: TargetAccount[]; reactivations: Reactivation[] }>()
const queryClient = useQueryClient()
const formalAccounts = computed(() => props.accounts.filter(account => !account.is_demo))
const records = ref<Reactivation[]>(props.reactivations.filter(record => !record.is_demo))
const accountId = ref("")
const relationshipSource = ref<Reactivation["relationship_source"]>("PAST_INQUIRY")
const lastInteractedAt = ref("")
const interactionSummary = ref("")
const relationshipConfirmed = ref(false)
const errorMessage = ref("")

watch(() => props.reactivations, value => { records.value = value.filter(record => !record.is_demo) })

function replaceRecord(record: Reactivation): void {
  records.value = [record, ...records.value.filter(item => item.id !== record.id)]
}

const selectMutation = useMutation({
  mutationFn: selectReactivation,
  onSuccess: async (record) => {
    replaceRecord(record)
    accountId.value = ""
    interactionSummary.value = ""
    lastInteractedAt.value = ""
    relationshipConfirmed.value = false
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: (error) => { errorMessage.value = error instanceof Error ? error.message : "无法加入重新激活。" },
})
const draftMutation = useMutation({
  mutationFn: createReactivationDraft,
  onSuccess: async (result) => {
    const record = records.value.find(item => item.id === result.id)
    if (record) replaceRecord({ ...record, status: "DRAFTED", draft: {
      id: result.draft_id,
      english_draft: result.english_draft,
      chinese_explanation: result.chinese_explanation,
      status: "DRAFT",
    } })
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: (error) => { errorMessage.value = error instanceof Error ? error.message : "证据不足，不能生成草稿。" },
})
const approveMutation = useMutation({
  mutationFn: approveReactivationDraft,
  onSuccess: async (result) => {
    const record = records.value.find(item => item.id === result.id)
    if (record?.draft) replaceRecord({ ...record, status: "APPROVED", draft: { ...record.draft, status: "APPROVED" } })
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: (error) => { errorMessage.value = error instanceof Error ? error.message : "暂时无法批准草稿。" },
})

function submit(): void {
  errorMessage.value = ""
  if (!accountId.value || !lastInteractedAt.value || !interactionSummary.value.trim() || !relationshipConfirmed.value) {
    errorMessage.value = "请完整填写已有关系、最后互动和历史摘要，并确认名单使用权。"
    return
  }
  selectMutation.mutate({
    account_id: accountId.value,
    relationship_source: relationshipSource.value,
    last_interacted_at: new Date(lastInteractedAt.value).toISOString(),
    interaction_summary: interactionSummary.value.trim(),
    relationship_confirmed: true,
  })
}

function tierLabel(tier: Reactivation["tier"]): string {
  return { STRATEGIC: "战略账户", NURTURE: "培育账户", OBSERVATION: "观察账户" }[tier]
}
</script>

<template>
  <section class="growth-card reactivation-workbench" aria-labelledby="reactivation-title">
    <div class="growth-heading">
      <div><h2 id="reactivation-title">沉睡线索重新激活</h2><p>只处理已有关系或合法自有名单；AI 准备草稿，始终由你审核。</p></div>
      <span>绝不自动发送</span>
    </div>
    <form class="reactivation-form" @submit.prevent="submit">
      <label>已有关系账户<select v-model="accountId" required><option value="">选择已有账户</option><option v-for="account in formalAccounts" :key="account.id" :value="account.id">{{ account.name }}</option></select></label>
      <label>关系来源<select v-model="relationshipSource"><option value="EXISTING_CUSTOMER">已有客户</option><option value="PAST_INQUIRY">历史询盘</option><option value="TRADE_SHOW">展会接触</option><option value="OWNED_CRM">合法自有 CRM 名单</option></select></label>
      <label>最后互动时间<input v-model="lastInteractedAt" type="datetime-local" required></label>
      <label class="summary-field">历史互动摘要<textarea v-model="interactionSummary" rows="2" required placeholder="只写已发生并可核实的互动"></textarea></label>
      <label class="relationship-confirm"><input v-model="relationshipConfirmed" type="checkbox">确认这是已有关系或合法自有名单</label>
      <button class="button button-primary" type="submit" :disabled="selectMutation.isPending.value">加入重新激活</button>
    </form>
    <p v-if="errorMessage" class="approval-status" role="alert">{{ errorMessage }}</p>

    <div v-if="records.length" class="reactivation-list">
      <article v-for="record in records" :key="record.id" class="reactivation-card" :aria-label="`${record.account_name} 重新激活`">
        <header><div><h3>{{ record.account_name }}</h3><p>{{ record.industry }} · {{ tierLabel(record.tier) }}</p></div><b>{{ record.status === "APPROVED" ? "已批准，未发送" : "人工待审" }}</b></header>
        <dl>
          <div><dt>为何值得重新联系</dt><dd>{{ record.why_reactivate }}</dd></div>
          <div><dt>建议动作</dt><dd>{{ record.recommended_action }}</dd></div>
          <div><dt>历史依据</dt><dd>{{ record.interaction_summary }}</dd></div>
          <div><dt>近期证据</dt><dd>{{ record.evidence }}</dd></div>
          <div><dt>风险</dt><dd>{{ record.risk }}</dd></div>
        </dl>
        <p v-if="record.tier === 'OBSERVATION'" class="observation-note">观察账户证据不足，只建议补全，不生成触达草稿。</p>
        <section v-if="record.draft" class="reactivation-draft">
          <h4>待审草稿</h4><p>{{ record.draft.english_draft }}</p><small>{{ record.draft.chinese_explanation }}</small>
        </section>
        <div class="reactivation-actions">
          <button v-if="record.tier !== 'OBSERVATION' && !record.draft" class="button button-secondary" type="button" @click="draftMutation.mutate(record.id)">生成待审草稿</button>
          <button v-if="record.draft?.status === 'DRAFT'" class="button button-primary" type="button" @click="approveMutation.mutate(record.id)">人工批准草稿</button>
          <span>批准只记录状态 · 绝不自动发送</span>
        </div>
        <ol class="reactivation-timeline">
          <li :class="{ done: record.events.some(event => event.event_type === 'REACTIVATION_SELECTED') }">选入重新激活</li>
          <li :class="{ done: Boolean(record.draft) }">生成草稿</li>
          <li :class="{ done: record.status === 'APPROVED' }">人工批准</li>
          <li>未来人工发送</li><li>未来回复</li>
        </ol>
      </article>
    </div>
  </section>
</template>

<style scoped>
.reactivation-workbench { margin-bottom: 16px; }.reactivation-form { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }.reactivation-form label { display: grid; gap: 5px; color: var(--sg-muted); font-size: .74rem; }.reactivation-form select, .reactivation-form input, .reactivation-form textarea { border: 1px solid var(--sg-line); border-radius: 8px; background: #fff; padding: 9px; color: var(--sg-ink); }.summary-field { grid-column: span 2; }.relationship-confirm { display: flex !important; align-items: center; grid-column: span 2; }.reactivation-list { display: grid; gap: 12px; margin-top: 16px; }.reactivation-card { border: 1px solid #d8e6f2; border-radius: 12px; padding: 14px; background: #fbfdff; }.reactivation-card header { display: flex; justify-content: space-between; gap: 12px; }.reactivation-card h3 { margin: 5px 0; }.reactivation-card header p { margin: 0; color: var(--sg-muted); }.reactivation-card header b { color: #17699d; font-size: .78rem; }.reactivation-card dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }.reactivation-card dl div { border-top: 1px solid #e5eef5; padding-top: 8px; }.reactivation-card dt { color: var(--sg-muted); font-size: .7rem; }.reactivation-card dd { margin: 3px 0 0; font-size: .78rem; }.observation-note { color: #8a5900; font-weight: 750; }.reactivation-draft { border-left: 3px solid #75a9cc; padding-left: 12px; }.reactivation-actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; }.reactivation-actions span { color: var(--sg-muted); font-size: .72rem; }.reactivation-timeline { display: flex; gap: 8px; flex-wrap: wrap; padding: 0; list-style: none; }.reactivation-timeline li { border-radius: 999px; background: #eef2f5; padding: 5px 8px; color: var(--sg-muted); font-size: .68rem; }.reactivation-timeline li.done { background: #e5f4ea; color: #24704a; }
@media (max-width: 760px) { .reactivation-form { grid-template-columns: 1fr; }.summary-field, .relationship-confirm { grid-column: auto; }.reactivation-card dl { grid-template-columns: 1fr; } }
</style>
