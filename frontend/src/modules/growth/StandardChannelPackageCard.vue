<script setup lang="ts">
import type { PlatformConnection } from "./api"
import type { PackageFactEvidence } from "./packagePayload"

defineProps<{
  code: PlatformConnection["channel"]
  name: string
  actionName: string
  format: string
  modeLabel: string
  connectionDisplay: string
  connectionConnected: boolean
  connectionActionLabel: string
  recoveryAction: string
  publishingRouteLabel: string
  packageTitle: string
  facts: PackageFactEvidence[]
  approved: boolean
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
    :id="`channel-package-${code}`"
    tabindex="-1"
    :aria-label="`${name} 内容包`"
  >
    <span class="fake-label">{{ modeLabel }}</span>
    <h3>{{ name }}</h3>
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
        {{ recoveryAction || "连接账号" }}
      </button>
    </div>
    <p class="publishing-route">{{ publishingRouteLabel }}</p>
    <p class="package-source">{{ packageTitle || format }}</p>
    <p>{{ format }}</p>
    <strong>手工发布包</strong>
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
        :aria-label="`批准 ${actionName} 内容包`"
        @click="emit('approve')"
      >
        {{ approved ? "已批准" : "批准" }}
      </button>
      <button
        v-if="approved"
        class="button button-secondary"
        type="button"
        :disabled="exporting"
        :aria-label="`下载 ${actionName} 发布包`"
        @click="emit('download')"
      >
        下载
      </button>
    </div>
  </article>
</template>

<style scoped src="./growth-pages.css"></style>
