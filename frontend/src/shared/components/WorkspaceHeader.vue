<script setup lang="ts">
import { computed } from "vue"

import { businessStatus } from "../presentation/businessStatus"

const props = defineProps<{
  title: string
  description?: string
  status?: string
}>()

const statusDetail = computed(() => props.status ? businessStatus(props.status) : null)
</script>

<template>
  <header class="workspace-header">
    <div class="workspace-header-copy">
      <h1>{{ title }}</h1>
      <p v-if="description" class="workspace-description">{{ description }}</p>
      <p
        v-if="statusDetail"
        class="workspace-status"
        :class="`workspace-status-${statusDetail.tone}`"
        :title="status"
      >
        <strong>{{ statusDetail.label }}</strong>
        <span>{{ statusDetail.consequence }}</span>
      </p>
    </div>
    <div v-if="$slots.actions" class="workspace-header-actions"><slot name="actions" /></div>
  </header>
</template>
