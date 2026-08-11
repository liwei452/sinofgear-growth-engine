<script setup lang="ts">
defineProps<{
  title: string
  explanation: string
  primaryLabel: string
  state?: "loading" | "ready" | "error"
}>()

defineEmits<{ primary: []; retry: [] }>()
</script>

<template>
  <section id="next-steps" class="next-step-panel" role="region" :aria-label="title">
    <div>
      <p class="eyebrow">建议行动</p>
      <h2>{{ title }}</h2>
      <p>{{ explanation }}</p>
    </div>
    <p v-if="state === 'loading'" role="status" aria-live="polite">正在准备建议…</p>
    <div v-else-if="state === 'error'" class="next-step-error" role="alert">
      <p>建议暂时无法准备。</p>
      <button type="button" @click="$emit('retry')">重新加载</button>
    </div>
    <button v-else class="primary-action" type="button" @click="$emit('primary')">
      {{ primaryLabel }}
    </button>
  </section>
</template>

<style scoped>
.next-step-panel{display:flex;align-items:center;justify-content:space-between;gap:1.25rem;padding:1.25rem;border:1px solid var(--sg-line,var(--border-color,#d8dee8));border-radius:var(--sg-radius-md,1rem);background:linear-gradient(135deg,var(--sg-brand-soft,#eef6ff),#fff)}
.next-step-panel h2,.next-step-panel p{margin:.2rem 0}.next-step-panel>div:first-child{max-width:46rem}.next-step-error{display:flex;align-items:center;gap:.75rem}
@media(max-width:700px){.next-step-panel,.next-step-error{align-items:stretch;flex-direction:column}.next-step-panel>.primary-action{width:100%}}
</style>
