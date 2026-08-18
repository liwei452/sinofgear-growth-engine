<script setup lang="ts">
import { RouterLink } from "vue-router"

import AppIcon, { type IconName } from "../../shared/components/AppIcon.vue"

defineProps<{
  title: string
  description: string
  icon: IconName
  mode: string
  capabilities: string[]
  actionLabel: string
  actionTo?: string
}>()

defineEmits<{ action: [] }>()
</script>

<template>
  <article class="capability-card">
    <header>
      <span class="capability-icon"><AppIcon :name="icon" :size="22" /></span>
      <span class="mode-chip">{{ mode }}</span>
    </header>
    <div>
      <h2>{{ title }}</h2>
      <p>{{ description }}</p>
    </div>
    <ul>
      <li v-for="item in capabilities" :key="item">{{ item }}</li>
    </ul>
    <RouterLink v-if="actionTo" class="capability-action" :to="actionTo">{{ actionLabel }}</RouterLink>
    <button v-else class="capability-action" type="button" @click="$emit('action')">{{ actionLabel }}</button>
  </article>
</template>

<style scoped>
.capability-card { display: grid; min-height: 260px; align-content: start; gap: 15px; border: 1px solid var(--sg-line); border-radius: 18px; background: #fff; padding: 19px; box-shadow: var(--sg-shadow-sm); }
.capability-card header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.capability-icon { display: grid; width: 44px; height: 44px; place-items: center; border-radius: 13px; background: linear-gradient(145deg, var(--sg-brand), #45b9ff); color: #fff; box-shadow: 0 9px 20px rgb(22 135 255 / 20%); }
.mode-chip { border-radius: 999px; background: var(--sg-brand-soft); padding: 5px 8px; color: var(--sg-brand-strong); font-size: .67rem; font-weight: 850; }
.capability-card h2 { margin: 0 0 6px; color: var(--sg-ink); font-size: 1rem; }
.capability-card p { margin: 0; color: var(--sg-muted); font-size: .76rem; line-height: 1.55; }
.capability-card ul { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; color: var(--sg-ink); font-size: .74rem; }
.capability-card li::before { content: ""; display: inline-block; width: 6px; height: 6px; margin-right: 8px; border-radius: 50%; background: var(--sg-success); vertical-align: 1px; }
.capability-action { align-self: end; width: max-content; margin-top: auto; border: 0; background: transparent; padding: 0; color: var(--sg-brand-strong); font: inherit; font-size: .77rem; font-weight: 850; text-decoration: none; cursor: pointer; }
</style>
