<script setup lang="ts">
import { ref } from "vue"
import { useModalFocus } from "../composables/useModalFocus"

defineProps<{ title: string; titleId: string }>()
const emit = defineEmits<{ close: [] }>()
const backdrop = ref<HTMLElement|null>(null)
const dialog = ref<HTMLElement|null>(null)
const initialFocus = ref<HTMLElement|null>(null)
useModalFocus({backdrop,dialog,initialFocus,close:()=>emit("close")})
</script>
<template>
  <div ref="backdrop" class="operation-backdrop" data-testid="operation-modal-backdrop" @click.self="emit('close')">
    <section ref="dialog" class="operation-dialog" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <h2 :id="titleId" ref="initialFocus" tabindex="-1">{{ title }}</h2>
      <slot />
    </section>
  </div>
</template>
<style scoped>
.operation-backdrop{position:fixed;inset:0;background:#0008;display:grid;place-items:center;padding:1rem;z-index:10}
.operation-dialog{width:min(36rem,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.1rem;border:1px solid var(--border-color,#d8dee8);border-radius:1rem;background:white}
</style>
