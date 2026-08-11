<script setup lang="ts">
import { computed } from "vue"

import AppIcon, { type AppIconName } from "../../../shared/components/AppIcon.vue"
import StatusBadge, { type StatusTone } from "../../../shared/components/StatusBadge.vue"

const props = defineProps<{
  number: number
  title: string
  description: string
  state: "current" | "complete" | "locked"
}>()

const status = computed<{ label: string; tone: StatusTone; icon: AppIconName }>(() => ({
  current: { label: "正在进行", tone: "brand", icon: "sparkles" },
  complete: { label: "已完成", tone: "success", icon: "check" },
  locked: { label: "尚未开始", tone: "neutral", icon: "document" },
})[props.state])
</script>

<template>
  <li class="guided-step" :class="`guided-step--${state}`">
    <article>
      <header>
        <span class="step-number" aria-hidden="true">{{ number }}</span>
        <AppIcon :name="status.icon" />
        <h2 :id="`guided-step-${number}-title`">{{ title }}</h2>
        <StatusBadge :tone="status.tone" :label="status.label" />
      </header>
      <section
        v-if="state === 'current'"
        class="step-body"
        role="region"
        :aria-label="title"
        aria-current="step"
      >
        <p>{{ description }}</p>
        <slot />
      </section>
    </article>
  </li>
</template>

<style scoped>
.guided-step{list-style:none}.guided-step article{overflow:hidden;border:1px solid #d8dee8;border-radius:1rem;background:#fff}.guided-step header{display:grid;grid-template-columns:auto auto 1fr auto;align-items:center;gap:.7rem;padding:1rem}.guided-step h2{margin:0;font-size:1.05rem}.step-number{display:grid;place-items:center;width:1.8rem;height:1.8rem;border-radius:50%;background:#edf1f5;color:#44546a;font-weight:800}.step-body{display:grid;gap:1rem;padding:0 1rem 1rem 4.25rem;border-top:1px solid #e7ebf0}.step-body p{margin:1rem 0 0;color:#4f6072}.guided-step--current article{border-color:#2f745c;box-shadow:0 10px 28px rgba(30,90,69,.1)}.guided-step--current .step-number{background:#245b47;color:#fff}.guided-step--locked{opacity:.72}@media(max-width:600px){.guided-step header{grid-template-columns:auto auto 1fr}.guided-step header :deep(.status-badge){grid-column:3;justify-self:start}.step-body{padding-left:1rem}}@media(prefers-reduced-motion:reduce){.guided-step article{scroll-behavior:auto}}
</style>
