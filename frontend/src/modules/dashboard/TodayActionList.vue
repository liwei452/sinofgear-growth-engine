<script setup lang="ts">
import { RouterLink } from "vue-router"

import AppIcon, { type IconName } from "../../shared/components/AppIcon.vue"

defineProps<{
  items: Array<{
    id: string
    icon: IconName
    title: string
    description: string
    count?: number
    to: string
    tone: "primary" | "accent" | "neutral"
  }>
}>()
</script>

<template>
  <section class="today-actions" aria-label="今日优先事项">
    <RouterLink
      v-for="item in items"
      :key="item.id"
      :to="item.to"
      class="today-action"
      :class="`today-action-${item.tone}`"
    >
      <span class="today-action-icon" aria-hidden="true"><AppIcon :name="item.icon" :size="21" /></span>
      <span class="today-action-copy">
        <span class="today-action-title">
          <strong>{{ item.title }}</strong>
          <b v-if="item.count">{{ item.count }}</b>
        </span>
        <small>{{ item.description }}</small>
      </span>
      <span class="today-action-arrow" aria-hidden="true">→</span>
    </RouterLink>
  </section>
</template>

<style scoped>
.today-actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.today-action { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 13px; min-height: 104px; border: 1px solid var(--sg-line); border-radius: var(--sg-radius-md); background: #fff; padding: 16px; color: var(--sg-ink); text-decoration: none; box-shadow: var(--sg-shadow-sm); transition: transform var(--sg-motion-fast), border-color var(--sg-motion-fast), box-shadow var(--sg-motion-fast); }
.today-action:hover { border-color: #9db3c3; transform: translateY(-2px); box-shadow: 0 12px 26px rgb(23 34 49 / 8%); }
.today-action-icon { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 11px; background: var(--sg-brand-soft); color: var(--sg-brand); }
.today-action-accent .today-action-icon { background: var(--sg-accent-soft); color: var(--sg-accent); }
.today-action-neutral .today-action-icon { background: #edf0ed; color: #46535d; }
.today-action-copy { min-width: 0; }
.today-action-title { display: flex; align-items: center; gap: 8px; }
.today-action-title strong { font-size: .95rem; }
.today-action-title b { display: inline-grid; min-width: 23px; height: 23px; place-items: center; border-radius: 999px; background: var(--sg-brand); color: white; font-size: .75rem; }
.today-action small { display: block; margin-top: 6px; color: var(--sg-muted); font-size: .875rem; line-height: 1.45; }
.today-action-arrow { color: var(--sg-muted); font-size: 1.15rem; }
@media (max-width: 980px) { .today-actions { grid-template-columns: 1fr; }.today-action { min-height: 84px; } }
@media (max-width: 420px) { .today-action { grid-template-columns: auto minmax(0, 1fr); }.today-action-arrow { display: none; } }
</style>
