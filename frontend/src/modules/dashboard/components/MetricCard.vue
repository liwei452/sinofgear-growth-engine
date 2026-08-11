<script setup lang="ts">
defineProps<{
  label: string
  value: string
  conclusion: string
}>()
</script>

<template>
  <article class="metric-card">
    <p>{{ label }}</p>
    <strong>{{ value }}</strong>
    <span>{{ conclusion }}</span>
  </article>
</template>

<style scoped>
.metric-card {
  display: grid;
  gap: 7px;
  min-width: 0;
  border: 1px solid var(--sg-line);
  border-radius: var(--sg-radius-sm);
  background: var(--sg-surface-elevated);
  padding: 16px;
}

.metric-card p,
.metric-card span {
  margin: 0;
  color: var(--sg-muted);
  line-height: 1.5;
}

.metric-card strong {
  color: var(--sg-brand);
  font-size: 1.45rem;
}
</style>
