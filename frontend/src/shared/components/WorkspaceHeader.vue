<script setup lang="ts">
defineProps<{
  eyebrow?: string
  title: string
  titleId?: string
  description?: string
}>()
</script>

<template>
  <header class="workspace-header">
    <div class="workspace-header-copy">
      <p v-if="eyebrow" class="workspace-eyebrow">{{ eyebrow }}</p>
      <h1 :id="titleId">{{ title }}</h1>
      <p v-if="description" class="workspace-description">{{ description }}</p>
      <div v-if="$slots.meta" class="workspace-meta"><slot name="meta" /></div>
    </div>
    <div v-if="$slots.actions" class="workspace-header-actions"><slot name="actions" /></div>
  </header>
</template>
