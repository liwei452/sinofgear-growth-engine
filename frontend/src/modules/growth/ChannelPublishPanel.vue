<script setup lang="ts">
import { computed } from "vue"

import type { ChannelPackage, PlatformConnection } from "./api"

export type ChannelReadiness = {
  channel: PlatformConnection["channel"]
  label: string
  package: ChannelPackage | undefined
  ready: boolean
  issue: "MISSING_PACKAGE" | "REVIEW" | "FORMAT" | "CONNECTION" | null
}

const props = defineProps<{
  reviewPackages: ChannelPackage[]
  allPackagesApproved: boolean
  batchReviewConfirmed: boolean
  manualExportIssues: string[]
  channelReadiness: ChannelReadiness[]
  allChannelsReady: boolean
  pendingReadinessCount: number
  publishingRouteSummary: string
  approvingAll: boolean
  exportingAll: boolean
  publishing: boolean
  publishLocked: boolean
  channelLabel: (channel: string) => string
}>()

const emit = defineEmits<{
  "update:batchReviewConfirmed": [value: boolean]
  approveAll: []
  downloadAll: []
  publish: []
  focusChannel: [channel: PlatformConnection["channel"]]
}>()

const batchReviewConfirmed = computed({
  get: () => props.batchReviewConfirmed,
  set: value => emit("update:batchReviewConfirmed", value),
})
</script>

<template>
  <section v-if="reviewPackages.length === 4" class="batch-review-panel" aria-label="四渠道内容总审核">
    <div>
      <p class="eyebrow">一次人工总审核</p>
      <h3>{{ allPackagesApproved ? "四个平台内容均已人工批准" : "核对四个平台版本后统一批准" }}</h3>
      <ul>
        <li v-for="channelPackage in reviewPackages" :key="channelPackage.id">
          <strong>{{ channelLabel(channelPackage.channel) }}</strong>
          <span>{{ String(channelPackage.payload.title ?? "待核对内容") }}</span>
        </li>
      </ul>
      <label v-if="!allPackagesApproved" class="batch-review-confirmation">
        <input v-model="batchReviewConfirmed" type="checkbox">
        <span>我已核对四个平台内容与事实证据</span>
      </label>
      <p v-else>批准只记录人工审核，不会发送或请求任何真实平台。</p>
    </div>
    <button
      v-if="!allPackagesApproved"
      class="button button-primary"
      type="button"
      :disabled="!batchReviewConfirmed || approvingAll"
      aria-label="批准 4 个渠道内容"
      @click="emit('approveAll')"
    >
      {{ approvingAll ? "正在批准…" : "批准 4 个渠道内容" }}
    </button>
  </section>

  <section v-if="channelReadiness.some(item => item.package)" class="batch-review-panel manual-export-panel" aria-label="四渠道手工发布包">
    <div>
      <p class="eyebrow">官方接口未就绪时的安全兜底</p>
      <h3>{{ allPackagesApproved ? "四渠道手工发布包可以下载" : `还需处理 ${manualExportIssues.length} 项` }}</h3>
      <ul v-if="manualExportIssues.length">
        <li v-for="issue in manualExportIssues" :key="issue"><span>{{ issue }}</span></li>
      </ul>
      <p v-else>包含四个平台文案、素材引用、UTM 与事实证据；下载不会发布到任何平台。</p>
    </div>
    <button
      class="button button-secondary"
      type="button"
      :disabled="!allPackagesApproved || exportingAll"
      aria-label="下载四渠道手工发布包"
      @click="emit('downloadAll')"
    >
      {{ exportingAll ? "正在准备…" : "下载四渠道手工发布包" }}
    </button>
  </section>

  <section v-if="channelReadiness.some(item => item.package)" class="publish-panel" aria-label="四渠道发布就绪检查">
    <div>
      <p class="eyebrow">四渠道发布就绪检查</p>
      <h3>{{ allChannelsReady ? "四个渠道均可提交" : `还有 ${pendingReadinessCount} 个渠道需要处理` }}</h3>
      <p>{{ publishingRouteSummary }}</p>
      <ul class="readiness-list">
        <li v-for="item in channelReadiness" :key="item.channel">
          <span>{{ channelLabel(item.channel) }} · {{ item.label }}</span>
          <a
            v-if="item.issue === 'MISSING_PACKAGE' || item.issue === 'FORMAT'"
            class="readiness-action"
            href="/reviews"
            :aria-label="item.issue === 'FORMAT' ? `补全 ${channelLabel(item.channel)} 发布格式` : `准备 ${channelLabel(item.channel)} 内容包`"
          >{{ item.issue === 'FORMAT' ? '去补全' : '准备内容' }}</a>
          <button
            v-else-if="item.issue === 'REVIEW' || item.issue === 'CONNECTION'"
            class="readiness-action"
            type="button"
            :aria-label="item.issue === 'REVIEW' ? `审核 ${channelLabel(item.channel)} 内容` : `处理 ${channelLabel(item.channel)} 账号`"
            @click="emit('focusChannel', item.channel)"
          >
            {{ item.issue === 'REVIEW' ? '去审核' : '去连接' }}
          </button>
        </li>
      </ul>
      <p>全部内容须人工批准且账号就绪；未连接官方账号时请下载手工发布包。</p>
    </div>
    <button
      class="button button-primary"
      type="button"
      :disabled="!allChannelsReady || publishing || publishLocked"
      @click="emit('publish')"
    >
      {{ publishing ? "正在提交…" : allChannelsReady ? "一键发布到 4 个渠道" : `还有 ${pendingReadinessCount} 个渠道未就绪` }}
    </button>
  </section>
</template>
