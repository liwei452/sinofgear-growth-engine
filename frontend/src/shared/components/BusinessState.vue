<script setup lang="ts">
import { computed } from "vue"

import AppIcon, { type IconName } from "./AppIcon.vue"

const props = defineProps<{
  kind: "loading" | "empty" | "blocked" | "error" | "success" | "unknown"
  title: string
  message: string
  actionLabel?: string
}>()

const emit = defineEmits<{ action: [] }>()

const icon = computed<IconName>(() => ({
  loading: "bot",
  empty: "inbox",
  blocked: "clipboard-check",
  error: "panel-left",
  success: "circle-check",
  unknown: "calendar-clock",
})[props.kind])

const liveRole = computed(() => props.kind === "error" || props.kind === "blocked" ? "alert" : "status")
</script>

<template>
  <section class="business-state" :class="`business-state-${kind}`" :role="liveRole" aria-live="polite">
    <span class="business-state-icon" role="img" :aria-label="title">
      <AppIcon :name="icon" :size="22" />
    </span>
    <div class="business-state-copy">
      <h2>{{ title }}</h2>
      <p>{{ message }}</p>
    </div>
    <button v-if="actionLabel" class="button button-secondary" type="button" @click="emit('action')">
      {{ actionLabel }}
    </button>
  </section>
</template>
