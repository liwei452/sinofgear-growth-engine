<script setup lang="ts">
import { computed } from "vue"

import type { PublishBatch } from "./api"

const props = defineProps<{
  batch: PublishBatch
  retrying: boolean
  channelLabel: (channel: string) => string
}>()

const emit = defineEmits<{ retry: [] }>()

const succeededCount = computed(() => (
  props.batch.items.filter(item => item.status === "SUCCEEDED").length
))
const failedItems = computed(() => (
  props.batch.items.filter(item => item.status === "FAILED")
))

const resultTimeFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
})

function formatResultTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "时间不可用"
  return resultTimeFormatter.format(date).replace(",", "")
}
</script>

<template>
  <section class="publish-results" aria-label="发布结果">
    <div class="growth-heading">
      <div>
        <p class="eyebrow">{{ batch.data_label }}</p>
        <h3>渠道发布结果</h3>
      </div>
      <strong v-if="batch.status === 'SUCCEEDED'">
        {{ succeededCount }} 个渠道{{ succeededCount > 1 ? "均" : "" }}已发布成功。
      </strong>
      <strong v-else-if="failedItems.length">
        {{ succeededCount }} 个渠道发布成功，{{ failedItems.length }} 个渠道需要重试。
      </strong>
      <strong v-else>发布请求已受理。</strong>
    </div>
    <ul class="publish-result-list">
      <li v-for="item in batch.items" :key="item.id">
        <span>{{ channelLabel(item.channel) }}</span>
        <div class="publish-result-detail">
          <a
            v-if="item.status === 'SUCCEEDED'"
            :href="item.external_post_url"
            target="_blank"
            rel="noreferrer"
            :aria-label="`查看 ${channelLabel(item.channel)} 平台帖子`"
          >发布成功 · 查看平台帖子</a>
          <span v-else>{{ item.recovery_action || (item.status === "FAILED" ? "发布失败，请重试。" : "等待发布") }}</span>
          <small>
            <span>结果记录时间：</span>
            <time :datetime="item.updated_at">{{ formatResultTime(item.updated_at) }}</time>
          </small>
        </div>
      </li>
    </ul>
    <button
      v-if="failedItems.length"
      class="button button-primary"
      type="button"
      :disabled="retrying"
      @click="emit('retry')"
    >
      {{ retrying ? "正在重试…" : "重试失败渠道" }}
    </button>
  </section>
</template>
