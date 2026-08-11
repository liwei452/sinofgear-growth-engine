<script setup lang="ts">
import { computed } from "vue"

import StatusBadge, { type StatusTone } from "../../../shared/components/StatusBadge.vue"

const props = defineProps<{
  title: string
  detail: string
  statusLabel: string
  statusTone: StatusTone
  progress: number | null
}>()

const hasProgress = computed(() => Number.isInteger(props.progress) && props.progress !== null
  && props.progress >= 0 && props.progress <= 100)
</script>

<template>
  <article class="activity-row">
    <div class="activity-row-heading">
      <div>
        <h3>{{ title }}</h3>
        <p>{{ detail }}</p>
      </div>
      <StatusBadge :tone="statusTone" :label="statusLabel" />
    </div>
    <div
      v-if="hasProgress"
      class="activity-progress"
      role="progressbar"
      :aria-label="`${title}的进度`"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="progress!"
    >
      <span :style="{ width: `${progress}%` }" />
      <span class="activity-progress-copy">已完成 {{ progress }}%</span>
    </div>
    <div
      v-else
      class="activity-progress activity-progress-indeterminate"
      role="progressbar"
      :aria-label="`${title}的进度`"
    >
      <span />
      <span class="activity-progress-copy">进度待确认</span>
    </div>
  </article>
</template>

<style scoped>
.activity-row {
  display: grid;
  gap: 12px;
  border-top: 1px solid var(--sg-line);
  padding: 16px 0 0;
}

.activity-row + .activity-row {
  margin-top: 16px;
}

.activity-row-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.activity-row h3,
.activity-row p {
  margin: 0;
}

.activity-row h3 {
  font-size: 1rem;
}

.activity-row p {
  margin-top: 4px;
  color: var(--sg-muted);
  line-height: 1.5;
}

.activity-progress {
  position: relative;
  overflow: hidden;
  height: 8px;
  border-radius: 999px;
  background: var(--sg-brand-tint);
}

.activity-progress > span:first-child {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--sg-brand);
}

.activity-progress-copy {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.activity-progress-indeterminate > span:first-child {
  width: 38%;
  animation: activity-progress 1.25s ease-in-out infinite;
}

@keyframes activity-progress {
  from { transform: translateX(-105%); }
  to { transform: translateX(370%); }
}

@media (prefers-reduced-motion: reduce) {
  .activity-progress-indeterminate > span:first-child { animation: none; }
}
</style>
