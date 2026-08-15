<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query"
import { ref } from "vue"

import {
  growthQueryKeys,
  prepareCandidateEnrichment,
  type CandidateEnrichmentPreview,
  type EnrichmentCandidate,
} from "./api"

const props = defineProps<{ candidates: EnrichmentCandidate[] }>()
const queryClient = useQueryClient()
const previews = ref<Record<string, CandidateEnrichmentPreview>>({})
const activeCandidateId = ref("")
const actionError = ref("")

const mutation = useMutation({
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

function previewFor(candidate: EnrichmentCandidate): CandidateEnrichmentPreview | null {
  return previews.value[candidate.id] ?? candidate.latest_preview
}

function prepare(candidateId: string): void {
  activeCandidateId.value = candidateId
  actionError.value = ""
  mutation.mutate(candidateId)
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
      </template>
      <div v-else class="enrichment-empty">
        <p><strong>尚未准备资料</strong> · 只会整理许可名单中的事实，不会编造联系人、邮箱或采购意向。</p>
        <button class="button button-primary" type="button" :disabled="mutation.isPending.value" @click="prepare(candidate.id)">
          {{ mutation.isPending.value && activeCandidateId === candidate.id ? "正在准备…" : "准备公司资料" }}
        </button>
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
@media (max-width: 900px) { .enrichment-columns { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .enrichment-empty { align-items: flex-start; flex-direction: column; } }
</style>
