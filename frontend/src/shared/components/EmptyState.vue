<script setup lang="ts">
import AppIcon, { type IconName } from "./AppIcon.vue"

defineProps<{
  icon: IconName
  title: string
  description: string
}>()
</script>

<template>
  <section class="empty-state">
    <span class="empty-state-icon" aria-hidden="true"><AppIcon :name="icon" :size="22" /></span>
    <div class="empty-state-copy">
      <h3>{{ title }}</h3>
      <p>{{ description }}</p>
    </div>
    <div v-if="$slots.default" class="empty-state-actions"><slot /></div>
  </section>
</template>
