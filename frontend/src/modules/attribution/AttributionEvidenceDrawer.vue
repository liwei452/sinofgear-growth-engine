<script setup lang="ts">
import type { AttributionTrace } from "./api"

defineProps<{ traces: AttributionTrace[] }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div class="drawer-backdrop" role="presentation" @click.self="emit('close')">
    <aside class="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-title">
      <header>
        <h2 id="evidence-title">归因依据</h2>
        <button class="button button-quiet" type="button" @click="emit('close')">关闭</button>
      </header>
      <ol class="traces">
        <li v-for="trace in traces" :key="trace.source_id">
          <span class="confidence" :data-confidence="trace.confidence">{{ trace.confidence }}</span>
          <span>{{ trace.type }}</span>
        </li>
      </ol>
      <p v-if="!traces.length" class="empty">暂无归因依据。</p>
    </aside>
  </div>
</template>

<style scoped>
.drawer-backdrop { position: fixed; inset: 0; z-index: 70; background: rgb(16 42 86 / 34%); }
.evidence-drawer { position: absolute; top: 0; right: 0; display: grid; width: min(420px, 100%); height: 100%; gap: 12px; background: #fff; padding: 20px; box-shadow: -18px 0 60px rgb(16 42 86 / 20%); }
.evidence-drawer header { display: flex; align-items: center; justify-content: space-between; }
.evidence-drawer h2 { margin: 0; font-size: 1rem; }
.traces { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.traces li { display: flex; gap: 8px; align-items: center; }
.confidence { border-radius: 999px; padding: 3px 8px; font-size: .66rem; font-weight: 800; }
.confidence[data-confidence="CONFIRMED"] { background: #e7f8ed; color: #14733c; }
.confidence[data-confidence="ASSISTED"] { background: #fff4e5; color: #9a5a10; }
.confidence[data-confidence="UNATTRIBUTED"] { background: #eef2f6; color: #4f5d6c; }
.empty { color: var(--sg-muted); }
</style>
