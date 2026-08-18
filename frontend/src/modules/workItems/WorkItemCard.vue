<script setup lang="ts">
import { computed } from "vue"

import type { WorkItem } from "./api"

const props = defineProps<{ item: WorkItem; busy: boolean }>()
const emit = defineEmits<{ action: [WorkItem] }>()

const draft = computed(() => {
  const value = props.item.preview?.draft
  return typeof value === "string" ? value : ""
})

const platforms = computed(() => {
  const value = props.item.preview?.platforms
  return Array.isArray(value) ? value : []
})
</script>

<template>
  <article class="work-item-card" :data-priority="item.priority">
    <header>
      <span class="priority">{{ item.priority }}</span>
      <strong>{{ item.title }}</strong>
      <span class="mission">{{ item.mission_title }}</span>
    </header>
    <p class="summary">{{ item.summary }}</p>
    <p v-if="draft" class="draft">{{ draft }}</p>
    <ul v-if="platforms.length" class="platforms">
      <li v-for="platform in platforms" :key="String(platform.channel)">
        {{ platform.channel }}: {{ platform.title }}
      </li>
    </ul>
    <footer>
      <time>{{ item.created_at }}</time>
      <button
        class="button button-primary"
        type="button"
        :disabled="busy"
        @click="emit('action', item)"
      >
        {{ item.action_label }}
      </button>
    </footer>
  </article>
</template>

<style scoped>
.work-item-card { display: grid; gap: 8px; border: 1px solid var(--sg-line); border-radius: 12px; background: #fff; padding: 15px; }
.work-item-card[data-priority="URGENT"] { border-left: 4px solid #c0392b; }
.work-item-card[data-priority="HIGH"] { border-left: 4px solid #d9822b; }
.work-item-card header { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.priority { border-radius: 999px; background: #eef2f6; padding: 3px 7px; color: #4f5d6c; font-size: .66rem; font-weight: 800; }
.mission { color: var(--sg-muted); font-size: .7rem; }
.summary { margin: 0; color: var(--sg-ink); font-size: .8rem; line-height: 1.5; }
.draft { margin: 0; border-left: 2px solid var(--sg-brand); border-radius: 5px; background: #f6f9fc; padding: 9px 11px; color: var(--sg-ink); font-size: .78rem; line-height: 1.5; }
.platforms { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
.platforms li { color: var(--sg-muted); font-size: .72rem; }
footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
footer time { color: var(--sg-muted); font-size: .68rem; }
</style>
