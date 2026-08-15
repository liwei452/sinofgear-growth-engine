<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query"
import { ref } from "vue"

import {
  addCandidateToFollowUp,
  createOpportunityDraft,
  growthQueryKeys,
  prepareCandidateEnrichment,
  type CandidateEnrichmentPreview,
  type EnrichmentCandidate,
  type OutreachDraft,
} from "./api"

const props = withDefaults(defineProps<{
  candidates: EnrichmentCandidate[]
  outreachDrafts?: OutreachDraft[]
  allowDemo?: boolean
}>(), { allowDemo: false, outreachDrafts: () => [] })
const queryClient = useQueryClient()
const previews = ref<Record<string, CandidateEnrichmentPreview>>({})
const activeCandidateId = ref("")
const actionError = ref("")
const accountIds = ref<Record<string, string>>({})
const followUpMessages = ref<Record<string, string>>({})
const drafts = ref<Record<string, { english: string; chinese: string }>>({})

const prepareMutation = useMutation({
  mutationFn: prepareCandidateEnrichment,
  onSuccess: async (preview) => {
    previews.value = { ...previews.value, [preview.candidate_id]: preview }
    actionError.value = ""
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => {
    actionError.value = "暂时无法准备公司资料，请刷新后重试。"
  },
})

const followUpMutation = useMutation({
  mutationFn: addCandidateToFollowUp,
  onSuccess: async (result) => {
    accountIds.value = { ...accountIds.value, [activeCandidateId.value]: result.account_id }
    followUpMessages.value = { ...followUpMessages.value, [activeCandidateId.value]: result.message }
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => { actionError.value = "暂时无法加入跟进，请稍后重试。" },
})

const draftMutation = useMutation({
  mutationFn: createOpportunityDraft,
  onSuccess: async (result) => {
    drafts.value = {
      ...drafts.value,
      [activeCandidateId.value]: {
        english: result["English draft"],
        chinese: result["Chinese explanation"],
      },
    }
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => { actionError.value = "暂时无法生成草稿，请稍后重试。" },
})

function previewFor(candidate: EnrichmentCandidate): CandidateEnrichmentPreview | null {
  const preview = previews.value[candidate.id] ?? candidate.latest_preview
  return preview?.mode === "FAKE_PREVIEW" && !props.allowDemo ? null : preview
}

function draftFor(candidate: EnrichmentCandidate): { english: string; chinese: string } | null {
  if (drafts.value[candidate.id]) return drafts.value[candidate.id]
  const accountId = accountIds.value[candidate.id] ?? previewFor(candidate)?.account_id
  if (!accountId) return null
  const saved = props.outreachDrafts
    .filter(draft => draft.account_id === accountId)
    .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))[0]
  return saved ? { english: saved.english_draft, chinese: saved.chinese_explanation } : null
}

function prepare(candidateId: string): void {
  activeCandidateId.value = candidateId
  actionError.value = ""
  prepareMutation.mutate(candidateId)
}

function addToFollowUp(candidateId: string): void {
  activeCandidateId.value = candidateId
  actionError.value = ""
  followUpMutation.mutate(candidateId)
}

function generateDraft(candidateId: string): void {
  const accountId = accountIds.value[candidateId] ?? previewFor(props.candidates.find(item => item.id === candidateId)!)?.account_id
  if (!accountId) return
  activeCandidateId.value = candidateId
  actionError.value = ""
  draftMutation.mutate(accountId)
}

const factLabels: Record<string, string> = {
  company_name: "公司名称",
  country: "国家 / 地区",
  industry: "行业",
  website: "公司官网",
}
</script>

<template>
  <section v-if="candidates.length" class="growth-card candidate-enrichment-queue">
    <div class="candidate-review-heading">
      <div>
        <span class="section-kicker">人工核实后</span>
        <h2>待补全公司资料</h2>
        <p>AI 先整理已有事实与缺口，结果仍需人工审核。</p>
      </div>
      <span class="candidate-count">{{ candidates.length }} 家待准备</span>
    </div>
    <p v-if="actionError" class="manual-import-error" role="alert">{{ actionError }}</p>
    <article v-for="candidate in props.candidates" :key="candidate.id" class="candidate-enrichment-card">
      <div class="candidate-review-title">
        <div><h3>{{ candidate.company_name }}</h3><p>{{ candidate.country }}<template v-if="candidate.industry"> · {{ candidate.industry }}</template></p></div>
        <span class="status-pill">待补全公司资料</span>
      </div>
      <template v-if="previewFor(candidate)">
        <p class="fake-enrichment-label">{{ previewFor(candidate)?.data_label }}</p>
        <div class="enrichment-columns">
          <section>
            <h4>已有事实与来源</h4>
            <dl class="enrichment-facts">
              <div v-for="fact in previewFor(candidate)?.facts" :key="fact.field">
                <dt>{{ factLabels[fact.field] ?? fact.field }}</dt><dd>{{ fact.value }}</dd><small>来源：{{ fact.source }}</small>
              </div>
            </dl>
          </section>
          <section>
            <h4>公开联系路径</h4>
            <ul v-if="previewFor(candidate)?.public_contact_paths.length">
              <li v-for="path in previewFor(candidate)?.public_contact_paths" :key="path.url ?? path.label">{{ path.label ?? path.url }}</li>
            </ul>
            <p v-else>尚未发现可验证的公开联系路径</p>
            <h4>缺失项 / 不确定项</h4>
            <ul><li v-for="item in previewFor(candidate)?.uncertainties" :key="item">{{ item }}</li></ul>
          </section>
        </div>
        <p class="candidate-intent-warning">{{ previewFor(candidate)?.message }}</p>
        <div class="enrichment-actions">
          <button
            v-if="!(accountIds[candidate.id] ?? previewFor(candidate)?.account_id)"
            class="button button-primary" type="button" :disabled="followUpMutation.isPending.value"
            @click="addToFollowUp(candidate.id)"
          >
            加入跟进
          </button>
          <template v-else>
            <span class="follow-up-confirmation">{{ followUpMessages[candidate.id] || "已加入人工跟进" }}</span>
            <button v-if="!draftFor(candidate)" class="button button-secondary" type="button" :disabled="draftMutation.isPending.value" @click="generateDraft(candidate.id)">生成联系草稿</button>
          </template>
        </div>
        <section v-if="draftFor(candidate)" class="candidate-draft">
          <strong>待人工审核 · 绝不自动发送</strong>
          <p>{{ draftFor(candidate)?.english }}</p>
          <small>{{ draftFor(candidate)?.chinese }}</small>
        </section>
      </template>
      <div v-else class="enrichment-empty">
        <p><strong>{{ allowDemo ? "尚未准备资料" : candidate.is_demo ? "资料理解服务尚未配置" : "待确认已导入事实" }}</strong> · {{ allowDemo ? "只会整理许可名单中的事实，不会编造联系人、邮箱或采购意向。" : candidate.is_demo ? "当前不会生成模拟公司事实；请上传真实资料或手工补充已核实信息。" : "系统只整理许可名单中已有字段，不联网核实，也不生成联系人或采购意向。" }}</p>
        <button v-if="allowDemo || !candidate.is_demo" class="button button-primary" type="button" :disabled="prepareMutation.isPending.value" @click="prepare(candidate.id)">
          {{ prepareMutation.isPending.value && activeCandidateId === candidate.id ? "正在准备…" : "准备公司资料" }}
        </button>
        <div v-if="!allowDemo" class="enrichment-actions">
          <a class="button button-primary" href="/assets">上传真实资料</a>
          <a class="button button-secondary" href="/company">补充公司信息</a>
        </div>
      </div>
    </article>
  </section>
</template>

<style scoped src="./growth-pages.css"></style>
<style scoped>
.candidate-enrichment-queue { display: grid; gap: 14px; }
.candidate-enrichment-card { border: 1px solid #d8e6f2; border-radius: 12px; background: #fbfdff; padding: 16px; }
.fake-enrichment-label { display: inline-flex; margin: 12px 0; border-radius: 999px; background: #fff3df; padding: 5px 9px; color: #8a5900; font-size: .72rem; font-weight: 850; }
.enrichment-columns { display: grid; grid-template-columns: 1.15fr .85fr; gap: 16px; }
.enrichment-columns section { border-radius: 10px; background: #f4f8fb; padding: 12px; }
.enrichment-columns h4 { margin: 0 0 9px; color: #25445e; }
.enrichment-columns ul { margin: 8px 0 14px; padding-left: 18px; color: #526579; font-size: .78rem; line-height: 1.6; }
.enrichment-columns p { color: #526579; font-size: .78rem; }
.enrichment-facts { display: grid; gap: 7px; margin: 0; }
.enrichment-facts div { display: grid; grid-template-columns: 90px 1fr; gap: 4px 8px; }
.enrichment-facts dt { color: var(--sg-muted); font-size: .72rem; }
.enrichment-facts dd { margin: 0; overflow-wrap: anywhere; color: #243b50; font-size: .8rem; font-weight: 800; }
.enrichment-facts small { grid-column: 2; color: var(--sg-muted); font-size: .68rem; }
.enrichment-empty { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-top: 12px; border-radius: 10px; background: #f4f8fb; padding: 12px; }
.enrichment-empty p { margin: 0; color: #526579; font-size: .78rem; }
.enrichment-actions { display: flex; align-items: center; gap: 10px; }.follow-up-confirmation { color: #24704a; font-size: .78rem; font-weight: 800; }.candidate-draft { margin-top: 12px; border-left: 3px solid #17699d; background: #f4f8fb; padding: 12px; }.candidate-draft strong { color: #174b70; }.candidate-draft p { white-space: pre-wrap; color: #304a61; }.candidate-draft small { color: var(--sg-muted); }
@media (max-width: 900px) { .enrichment-columns { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .enrichment-empty { align-items: flex-start; flex-direction: column; } }
</style>
