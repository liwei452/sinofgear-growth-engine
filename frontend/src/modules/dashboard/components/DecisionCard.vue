<script setup lang="ts">
import type { DirectorAction } from "../../director/api"
import { ordinaryDirectorAction } from "../../../shared/presentation/ordinary"
import AppIcon from "../../../shared/components/AppIcon.vue"

const props = defineProps<{
  index: number
  title: string
  explanation: string
  actions: readonly string[]
  busy: boolean
}>()

const emit = defineEmits<{ decide: [action: DirectorAction] }>()
const ordered: DirectorAction[] = ["APPROVE", "REQUEST_ADJUSTMENT", "REJECT"]
const available = (action: DirectorAction): boolean => props.actions.includes(action)
</script>

<template>
  <article class="decision-card" :aria-busy="busy">
    <div class="decision-card-meta">
      <span class="decision-card-index">优先级 {{ index }}</span>
      <span class="decision-card-note">等待你的决定</span>
    </div>
    <h3>{{ title }}</h3>
    <p>{{ explanation }}</p>
    <div class="decision-card-actions">
      <button
        v-for="action in ordered.filter(available)"
        :key="action"
        :class="['button', action === 'APPROVE' ? 'button-primary' : 'button-quiet']"
        type="button"
        :disabled="busy"
        @click="emit('decide', action)"
      >
        <AppIcon v-if="action === 'APPROVE'" name="check" />
        {{ busy ? '正在提交' : ordinaryDirectorAction(action) }}
      </button>
    </div>
  </article>
</template>

<style scoped>
.decision-card { display: grid; gap: 12px; border-top: 1px solid var(--sg-line); padding-top: 18px; }
.decision-card + .decision-card { margin-top: 18px; }
.decision-card-meta, .decision-card-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.decision-card-index { color: var(--sg-brand); font-size: .82rem; font-weight: 800; }
.decision-card-note { color: var(--sg-muted); font-size: .82rem; }
.decision-card h3, .decision-card p { margin: 0; }
.decision-card p { color: var(--sg-muted); line-height: 1.65; }
.decision-card-actions { margin-top: 2px; }
</style>
