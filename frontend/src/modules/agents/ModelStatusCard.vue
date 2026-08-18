<script setup lang="ts">
import { computed } from "vue"
import { RouterLink } from "vue-router"

import AppIcon from "../../shared/components/AppIcon.vue"
import type { ProductAIStatus } from "../settings/api"

const props = defineProps<{
  status: ProductAIStatus | null
  pendingApprovals: number
}>()

const modelLabel = computed(() => {
  if (!props.status) return "模型状态暂不可用"
  if (props.status.mode === "CONFIGURED_AI") {
    return `${props.status.provider_label} · ${props.status.model}`
  }
  if (props.status.mode === "FAKE_OFFLINE") return "离线演示 · 不会调用真实模型"
  return "真实 AI 尚未配置"
})
</script>

<template>
  <section class="model-status" aria-label="Agent 运行环境">
    <div class="model-status__icon"><AppIcon name="sparkles" :size="24" /></div>
    <div>
      <p>运行环境</p>
      <strong>{{ modelLabel }}</strong>
    </div>
    <div class="model-status__metric">
      <span>等待批准</span>
      <strong>{{ pendingApprovals }}</strong>
    </div>
    <div class="model-status__metric">
      <span>费用控制</span>
      <strong>管理员预算</strong>
    </div>
    <RouterLink to="/settings/ai-model">模型设置</RouterLink>
  </section>
</template>

<style scoped>
.model-status { display: grid; grid-template-columns: auto minmax(200px, 1fr) auto auto auto; align-items: center; gap: 18px; border: 1px solid #cfe7ff; border-radius: 18px; background: linear-gradient(110deg, #fff 0%, #eef7ff 100%); padding: 16px 18px; box-shadow: var(--sg-shadow-sm); }
.model-status__icon { display: grid; width: 46px; height: 46px; place-items: center; border-radius: 14px; background: var(--sg-brand); color: #fff; }
.model-status p, .model-status span { margin: 0 0 4px; color: var(--sg-muted); font-size: .68rem; }
.model-status strong { color: var(--sg-ink); font-size: .82rem; }
.model-status__metric { display: grid; min-width: 90px; border-left: 1px solid var(--sg-line); padding-left: 18px; }
.model-status a { color: var(--sg-brand-strong); font-size: .75rem; font-weight: 850; text-decoration: none; }
@media (max-width: 800px) { .model-status { grid-template-columns: auto 1fr; }.model-status__metric, .model-status a { grid-column: 2; border-left: 0; padding-left: 0; } }
</style>
