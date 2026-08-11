<script setup lang="ts">
import AppIcon from "../../../shared/components/AppIcon.vue"
import StatusBadge, { type StatusTone } from "../../../shared/components/StatusBadge.vue"

defineProps<{
  index: number
  title: string
  explanation: string
  statusLabel: string
  statusTone: StatusTone
  primaryAction: string
  secondaryAction?: string
}>()

defineEmits<{
  primary: []
  secondary: []
}>()
</script>

<template>
  <article class="decision-card">
    <div class="decision-card-meta">
      <span class="decision-card-index">优先级 {{ index }}</span>
      <StatusBadge :tone="statusTone" :label="statusLabel" />
    </div>
    <h3>{{ title }}</h3>
    <p>{{ explanation }}</p>
    <div class="decision-card-actions">
      <button class="button button-primary" type="button" @click="$emit('primary')">
        <AppIcon name="check" />
        {{ primaryAction }}
      </button>
      <button v-if="secondaryAction" class="button button-quiet" type="button" @click="$emit('secondary')">
        {{ secondaryAction }}
      </button>
    </div>
  </article>
</template>

<style scoped>
.decision-card {
  display: grid;
  gap: 12px;
  border-top: 1px solid var(--sg-line);
  padding: 18px 0 0;
}

.decision-card + .decision-card {
  margin-top: 18px;
}

.decision-card-meta,
.decision-card-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.decision-card-index {
  color: var(--sg-brand);
  font-size: 0.82rem;
  font-weight: 800;
}

.decision-card h3,
.decision-card p {
  margin: 0;
}

.decision-card h3 {
  font-size: 1.05rem;
}

.decision-card p {
  color: var(--sg-muted);
  line-height: 1.6;
}

.decision-card-actions .button {
  gap: 8px;
}
</style>
