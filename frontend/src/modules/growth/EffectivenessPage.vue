<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import { createMetricReceipt, growthQueryKeys, growthWorkspaceQueryOptions } from "./api"
import AccountAttributionPanel from "./AccountAttributionPanel.vue"

const queryClient = useQueryClient()
const workspaceQuery = useQuery(growthWorkspaceQueryOptions())
const channel = ref("TIKTOK")
const views = ref(6820)
const clicks = ref(186)
const replies = ref(0)
const inquiries = ref(1)
const savedMessage = ref("")
const saveError = ref("")

const latestReceipts = computed(() => {
  const seen = new Set<string>()
  return (workspaceQuery.data.value?.metric_receipts ?? []).filter((receipt) => {
    if (seen.has(receipt.channel)) return false
    seen.add(receipt.channel)
    return true
  })
})
function recordedMetric(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key]
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null
}
function metricText(payload: Record<string, unknown>, key: string, label: string): string {
  const value = recordedMetric(payload, key)
  return value === null ? `${label}无数据` : `${value.toLocaleString()} ${label}`
}
const recordedClicks = computed(() => latestReceipts.value.reduce(
  (total, receipt) => total + (recordedMetric(receipt.payload, "clicks") ?? 0), 0,
))
const hasRepliesOrInquiries = computed(() => latestReceipts.value.some(receipt =>
  recordedMetric(receipt.payload, "replies") !== null || recordedMetric(receipt.payload, "inquiries") !== null,
))

const metricMutation = useMutation({
  mutationFn: createMetricReceipt,
  onSuccess: async () => {
    savedMessage.value = "指标已保存到本地工作区。"
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => { saveError.value = "指标暂时无法保存，请稍后重试。" },
})

async function saveMetrics(): Promise<void> {
  savedMessage.value = ""
  saveError.value = ""
  await metricMutation.mutateAsync({
    channel: channel.value,
    payload: {
      views: Number(views.value), clicks: Number(clicks.value), replies: Number(replies.value),
      inquiries: Number(inquiries.value),
    },
    is_demo: true,
  }).catch(() => undefined)
}
</script>

<template>
  <div class="growth-page">
    <header class="growth-hero"><div><p class="eyebrow">效果</p><h1>推广效果</h1><p>每个结论都保留时间范围、分子、分母和数据来源。</p></div><span class="fake-label">Demo / Fake</span></header>
    <AccountAttributionPanel v-if="workspaceQuery.data.value" :workspace="workspaceQuery.data.value" />
    <div class="attribution-auxiliary-label"><strong>以下只显示已保存的渠道回填</strong><span>Demo / Fake 与人工记录逐条标识，不计入上方账户漏斗。</span></div>
    <section class="metric-grid" aria-label="渠道回填摘要">
      <article><span>已回填渠道</span><strong>{{ latestReceipts.length }}</strong><p>仅统计每个渠道最新一条记录</p></article>
      <article><span>已记录点击</span><strong>{{ latestReceipts.length ? recordedClicks.toLocaleString() : "无数据" }}</strong><p>来自已保存渠道记录</p></article>
      <article><span>回复与询盘</span><strong>{{ hasRepliesOrInquiries ? "已有记录" : "尚未发生 / 无数据" }}</strong><p>不根据曝光或点击推算</p></article>
    </section>
    <section class="growth-card">
      <div class="growth-heading"><div><h2>渠道与结果</h2><p>只展示人工保存的记录，不补造时间范围或趋势。</p></div></div>
      <p v-if="!latestReceipts.length" class="attribution-empty">尚未回填渠道结果</p>
      <div v-else class="performance-list">
        <article v-for="receipt in latestReceipts" :key="receipt.id">
          <strong>{{ receipt.channel }} · {{ receipt.is_demo ? "Demo / Fake" : "人工记录" }}</strong>
          <span>{{ metricText(receipt.payload, "views", "播放或访问") }}</span>
          <span>{{ metricText(receipt.payload, "clicks", "点击") }}</span>
          <span>{{ metricText(receipt.payload, "replies", "回复") }} · {{ metricText(receipt.payload, "inquiries", "询盘") }}</span>
        </article>
      </div>
      <form class="metric-backfill" aria-labelledby="metric-backfill-title" @submit.prevent="saveMetrics">
        <div class="growth-heading"><div><h2 id="metric-backfill-title">手工回填渠道结果</h2><p>只保存人工确认的结果，不连接或操作真实平台。</p></div><span class="fake-label">Demo / Fake</span></div>
        <div class="metric-fields">
          <label>渠道<select v-model="channel"><option value="TIKTOK">TikTok</option><option value="LINKEDIN">LinkedIn</option><option value="INSTAGRAM">Instagram</option><option value="FACEBOOK">Facebook</option></select></label>
          <label>播放或访问<input v-model.number="views" type="number" min="0" required /></label>
          <label>点击<input v-model.number="clicks" type="number" min="0" required /></label>
          <label>回复<input v-model.number="replies" type="number" min="0" required /></label>
          <label>询盘<input v-model.number="inquiries" type="number" min="0" required /></label>
        </div>
        <button class="button button-primary" type="submit" :disabled="metricMutation.isPending.value">{{ metricMutation.isPending.value ? "正在保存…" : "保存回填" }}</button>
        <p v-if="savedMessage" role="status" class="approval-status">{{ savedMessage }}</p>
        <p v-if="saveError" role="alert" class="approval-status">{{ saveError }}</p>
      </form>
      <aside class="sample-warning"><strong>样本不足时不自动调整策略</strong><p>只有已保存结果才参与展示；渠道回填不能替代账户级发送、回复和需求证据。</p></aside>
    </section>
  </div>
</template>
<style scoped src="./growth-pages.css"></style>
