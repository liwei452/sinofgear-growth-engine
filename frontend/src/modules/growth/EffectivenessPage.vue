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

const latestTikTokReceipt = computed(() => workspaceQuery.data.value?.metric_receipts
  .find((receipt) => receipt.channel === "TIKTOK"))

const displayedTikTok = computed(() => ({
  views: Number(latestTikTokReceipt.value?.payload.views ?? 6820),
  clicks: Number(latestTikTokReceipt.value?.payload.clicks ?? 74),
  inquiries: Number(latestTikTokReceipt.value?.payload.inquiries ?? 1),
}))

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
    <div class="attribution-auxiliary-label"><strong>以下为 Demo / Fake 渠道回填样例</strong><span>仅辅助检查内容与渠道，不计入上方账户漏斗。</span></div>
    <section class="metric-grid">
      <article><span>内容带来访问</span><strong>15.5</strong><p>点击 186 / 已发布内容包 12</p></article>
      <article><span>人工触达回复率</span><strong>26.5%</strong><p>回复 9 / 已人工触达 34</p></article>
      <article><span>访问转询盘</span><strong>1.6%</strong><p>询盘 3 / 落地页访问 186</p></article>
    </section>
    <section class="growth-card">
      <div class="growth-heading"><div><h2>渠道与结果</h2><p>2026-08-08 至 2026-08-14 · Fake 回填与本地 UTM 点击</p></div></div>
      <div class="performance-list">
        <article><strong>TikTok</strong><span>{{ displayedTikTok.views.toLocaleString() }} 播放</span><span>{{ displayedTikTok.clicks }} 点击</span><span>{{ displayedTikTok.inquiries }} 询盘</span></article>
        <article><strong>LinkedIn</strong><span>1,248 访问</span><span>63 点击</span><span>2 回复</span></article>
        <article><strong>Instagram</strong><span>418 触达</span><span>21 点击</span><span>0 询盘</span></article>
        <article><strong>Facebook</strong><span>567 访问</span><span>18 点击</span><span>1 回复</span></article>
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
      <aside class="sample-warning"><strong>样本不足，暂不自动调整策略</strong><p>仅 3 个询盘，无法证明单一渠道造成转化；继续保留首触、末触和客户自报来源。</p></aside>
    </section>
  </div>
</template>
<style scoped src="./growth-pages.css"></style>
