<script setup lang="ts">
import { RouterLink } from "vue-router"

defineProps<{
  name: string
  status: string
  capability: string
  recovery: string
  tone: "ready" | "warning" | "neutral"
  actionLabel: string
  actionTo?: string
}>()

defineEmits<{ action: [] }>()
</script>

<template>
  <article class="channel-card" :class="`is-${tone}`" :aria-label="`${name} 渠道`">
    <header>
      <span class="channel-dot" aria-hidden="true" />
      <h2>{{ name }}</h2>
    </header>
    <strong>{{ status }}</strong>
    <p>{{ capability }}</p>
    <small>{{ recovery }}</small>
    <RouterLink v-if="actionTo" :to="actionTo">{{ actionLabel }}</RouterLink>
    <button v-else type="button" @click="$emit('action')">{{ actionLabel }}</button>
  </article>
</template>

<style scoped>
.channel-card { display: grid; min-width: 0; align-content: start; gap: 9px; border: 1px solid var(--sg-line); border-radius: 16px; background: #fff; padding: 16px; box-shadow: var(--sg-shadow-sm); }
.channel-card header { display: flex; align-items: center; gap: 8px; }
.channel-card h2 { margin: 0; color: var(--sg-ink); font-size: .9rem; }
.channel-dot { width: 9px; height: 9px; border-radius: 50%; background: #9cb2c6; box-shadow: 0 0 0 4px #eef3f7; }
.is-ready .channel-dot { background: var(--sg-success); box-shadow: 0 0 0 4px rgb(40 184 135 / 13%); }
.is-warning .channel-dot { background: var(--sg-warning); box-shadow: 0 0 0 4px rgb(255 170 61 / 14%); }
.channel-card > strong { min-height: 30px; color: var(--sg-ink); font-size: .76rem; line-height: 1.4; }
.channel-card p { min-height: 34px; margin: 0; color: var(--sg-muted); font-size: .7rem; line-height: 1.5; }
.channel-card small { min-height: 34px; color: #7c91a8; font-size: .65rem; line-height: 1.45; }
.channel-card a, .channel-card button { width: max-content; border: 0; background: transparent; padding: 0; color: var(--sg-brand-strong); font: inherit; font-size: .7rem; font-weight: 850; text-decoration: none; cursor: pointer; }
</style>
