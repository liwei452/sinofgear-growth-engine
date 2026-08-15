<script setup lang="ts">
import type { PlatformConnection } from "./api"

export type SocialChannelStatus = {
  code: PlatformConnection["channel"]
  name: string
  actionName: string
  status: string
  capability: string
  connected: boolean
  accountId: string | null
  actionLabel: string
  reauthorizationRequired: boolean
  blocked: boolean
}

defineProps<{
  channels: SocialChannelStatus[]
  connecting: boolean
  disconnecting: boolean
}>()

const emit = defineEmits<{
  connect: [channel: PlatformConnection["channel"]]
  disconnect: [channel: PlatformConnection["channel"], name: string]
}>()
</script>

<template>
  <section class="growth-card social-readiness" aria-label="社媒账号连接状态">
    <div class="growth-heading">
      <div>
        <h2>社媒账号连接</h2>
        <p>连接只激活官方账号边界；任何内容仍需人工批准后才能提交。</p>
      </div>
      <span>5 个渠道</span>
    </div>
    <div class="social-readiness-grid">
      <article v-for="channel in channels" :key="channel.code">
        <div>
          <h3>{{ channel.name }}</h3>
          <span class="connection-state">{{ channel.status }}</span>
        </div>
        <p>{{ channel.capability }}</p>
        <div class="social-readiness-actions">
          <button
            v-if="channel.connected && channel.accountId"
            class="button button-secondary"
            type="button"
            :disabled="disconnecting"
            :aria-label="`断开 ${channel.actionName} 连接`"
            @click="emit('disconnect', channel.code, channel.name)"
          >
            断开连接
          </button>
          <button
            v-else-if="!channel.blocked"
            class="button button-secondary"
            type="button"
            :disabled="connecting"
            :aria-label="channel.actionLabel"
            @click="emit('connect', channel.code)"
          >
            {{ channel.reauthorizationRequired ? "重新授权" : "连接账号" }}
          </button>
          <small v-else>无需在此输入密钥</small>
        </div>
      </article>
    </div>
  </section>
</template>
