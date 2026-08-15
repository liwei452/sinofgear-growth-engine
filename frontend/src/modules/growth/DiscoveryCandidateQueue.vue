<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import {
  growthQueryKeys,
  reviewDiscoveryCandidate,
  type DiscoveryCandidate,
} from "./api"

const props = defineProps<{ candidates: DiscoveryCandidate[] }>()
const queryClient = useQueryClient()
const reviewedIds = ref(new Set<string>())
const actionStatus = ref("")
const actionError = ref("")

const visibleCandidates = computed(() => (
  props.candidates.filter((candidate) => !reviewedIds.value.has(candidate.id))
))

const mutation = useMutation({
  mutationFn: ({ id, decision }: { id: string; decision: "ACCEPT" | "DISMISS" }) => (
    reviewDiscoveryCandidate(id, decision)
  ),
  onSuccess: async (result) => {
    reviewedIds.value = new Set([...reviewedIds.value, result.id])
    actionStatus.value = result.message
    actionError.value = ""
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => {
    actionStatus.value = ""
    actionError.value = "这家公司暂时无法完成核实，请刷新后重试。"
  },
})

function review(id: string, decision: "ACCEPT" | "DISMISS"): void {
  actionStatus.value = ""
  actionError.value = ""
  mutation.mutate({ id, decision })
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date(value))
}
</script>

<template>
  <section v-if="visibleCandidates.length || actionStatus" class="growth-card candidate-review-queue">
    <div class="candidate-review-heading">
      <div>
        <span class="section-kicker">发现候选</span>
        <h2>待核实公司</h2>
        <p>先确认它是不是目标公司，再进入公司资料补全。</p>
      </div>
      <span v-if="visibleCandidates.length" class="candidate-count">{{ visibleCandidates.length }} 家待处理</span>
    </div>
    <p v-if="actionStatus" class="approval-status" role="status">{{ actionStatus }}</p>
    <p v-if="actionError" class="manual-import-error" role="alert">{{ actionError }}</p>
    <article v-for="candidate in visibleCandidates" :key="candidate.id" class="candidate-review-card">
      <div class="candidate-review-title">
        <div>
          <span v-if="candidate.is_demo" class="demo-badge">Demo</span>
          <h3>{{ candidate.company_name }}</h3>
          <p>{{ candidate.country }}<template v-if="candidate.industry"> · {{ candidate.industry }}</template></p>
        </div>
        <span class="status-pill">{{ candidate.status_label }}</span>
      </div>
      <dl class="candidate-source-facts">
        <div><dt>名单来源</dt><dd>{{ candidate.source_owner }}</dd></div>
        <div><dt>许可依据</dt><dd>{{ candidate.license_contract }}</dd></div>
        <div><dt>导入方式</dt><dd>{{ candidate.import_format }} · {{ formatDate(candidate.created_at) }}</dd></div>
      </dl>
      <a v-if="candidate.website" class="candidate-website" :href="candidate.website" target="_blank" rel="noopener noreferrer">查看公司官网</a>
      <p class="candidate-intent-warning">尚未发现采购意向，不会自动联系</p>
      <div class="candidate-review-actions">
        <button class="button button-primary" type="button" :disabled="mutation.isPending.value" @click="review(candidate.id, 'ACCEPT')">加入资料补全</button>
        <button class="button button-secondary" type="button" :disabled="mutation.isPending.value" @click="review(candidate.id, 'DISMISS')">忽略</button>
      </div>
    </article>
  </section>
</template>

<style scoped src="./growth-pages.css"></style>
