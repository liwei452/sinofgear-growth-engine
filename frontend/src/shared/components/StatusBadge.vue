<script setup lang="ts">
export type StatusTone = "brand" | "success" | "warning" | "danger" | "neutral"

defineProps<{
  tone: StatusTone
  label: string
}>()
</script>

<template>
  <span class="status-badge" :class="`status-badge-${tone}`">{{ label }}</span>
</template>
