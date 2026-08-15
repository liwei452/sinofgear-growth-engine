<script setup lang="ts">
import type { ChannelPackage } from "./api"
import type { PackageFactEvidence } from "./packagePayload"

defineProps<{
  channelPackage: ChannelPackage | undefined
  approved: boolean
  modeLabel: string
  connectionDisplay: string
  connectionActionLabel: string
  connectionConnected: boolean
  publishingRouteLabel: string
  packageTitle: string
  formatLabel: string
  script: string
  shots: string
  voiceover: string
  subtitles: string
  hashtags: string
  cta: string
  utm: string
  facts: PackageFactEvidence[]
  approving: boolean
  exporting: boolean
  connecting: boolean
}>()

const emit = defineEmits<{
  approve: []
  download: []
  connect: []
}>()
</script>

<template>
  <article
    v-if="channelPackage"
    id="channel-package-TIKTOK"
    class="tiktok-package"
    tabindex="-1"
    aria-label="TikTok 内容包"
  >
    <span class="fake-label">{{ modeLabel }}</span>
    <h3>TikTok</h3>
    <div class="channel-connection">
      <span>{{ connectionDisplay }}</span>
      <button
        v-if="!connectionConnected"
        class="button button-secondary"
        type="button"
        :disabled="connecting"
        :aria-label="connectionActionLabel"
        @click="emit('connect')"
      >
        {{ connectionActionLabel }}
      </button>
    </div>
    <p class="publishing-route">{{ publishingRouteLabel }}</p>
    <p v-if="packageTitle" class="package-source">{{ packageTitle }}</p>
    <p class="package-lead">{{ formatLabel }} · 手工发布包 · {{ modeLabel }}</p>
    <dl>
      <div><dt>脚本</dt><dd>{{ script }}</dd></div>
      <div><dt>分镜</dt><dd>{{ shots }}</dd></div>
      <div><dt>目标语言口播</dt><dd>{{ voiceover }}</dd></div>
      <div><dt>目标语言字幕</dt><dd>{{ subtitles }}</dd></div>
      <div><dt>标题 / 标签 / CTA</dt><dd>{{ packageTitle || "待补全" }} · {{ hashtags }} · {{ cta }}</dd></div>
      <div><dt>归因</dt><dd>UTM：{{ utm }}</dd></div>
      <div><dt>回填</dt><dd>发布结果、播放、完播、点击、回复、询盘可手工录入</dd></div>
    </dl>
    <details v-if="facts.length" class="package-evidence">
      <summary>查看已验证事实依据</summary>
      <article v-for="fact in facts" :key="fact.id">
        <strong>{{ fact.fieldName }}：{{ fact.value }}</strong>
        <p>{{ fact.sourceFilename }}<template v-if="fact.sourcePage"> · 第 {{ fact.sourcePage }} 页</template></p>
        <blockquote>{{ fact.sourceExcerpt }}</blockquote>
      </article>
    </details>
    <div class="package-actions">
      <button
        class="button button-secondary"
        type="button"
        :disabled="approved || approving"
        aria-label="批准 TikTok 内容包"
        @click="emit('approve')"
      >
        {{ approved ? "已批准" : "批准" }}
      </button>
      <button
        v-if="approved"
        class="button button-secondary"
        type="button"
        :disabled="exporting"
        aria-label="下载 TikTok 发布包"
        @click="emit('download')"
      >
        下载
      </button>
    </div>
  </article>
</template>

<style scoped src="./growth-pages.css"></style>
