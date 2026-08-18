<script setup lang="ts">
import AppIcon, { type IconName } from "../../shared/components/AppIcon.vue"

export type OpportunityWorkspace = "queue" | "discovery" | "import" | "reactivation" | "funnel"

defineProps<{
  active: OpportunityWorkspace
}>()

defineEmits<{
  select: [workspace: OpportunityWorkspace]
}>()

const items: Array<{ id: OpportunityWorkspace; label: string; icon: IconName }> = [
  { id: "queue", label: "机会队列", icon: "users-round" },
  { id: "discovery", label: "客户发现", icon: "map-pinned" },
  { id: "import", label: "名单导入", icon: "inbox" },
  { id: "reactivation", label: "老客激活", icon: "circle-check" },
  { id: "funnel", label: "转化漏斗", icon: "chart-column" },
]
</script>

<template>
  <nav class="opportunity-workspace-nav" aria-label="客户工作区">
    <button
      v-for="item in items"
      :key="item.id"
      type="button"
      :class="{ active: active === item.id }"
      :aria-current="active === item.id ? 'page' : undefined"
      @click="$emit('select', item.id)"
    >
      <AppIcon :name="item.icon" :size="18" />
      <span>{{ item.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.opportunity-workspace-nav {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
  border: 1px solid var(--sg-line);
  border-radius: 14px;
  background: #fff;
  padding: 6px;
  box-shadow: 0 3px 16px rgb(23 34 49 / 4%);
}

button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 44px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--sg-muted);
  font: inherit;
  font-size: .875rem;
  font-weight: 800;
  cursor: pointer;
}

button:hover,
button:focus-visible {
  background: #f3f6f9;
  color: var(--sg-ink);
}

button.active {
  background: var(--sg-brand);
  color: #fff;
  box-shadow: 0 4px 12px rgb(18 59 92 / 18%);
}

@media (max-width: 640px) {
  .opportunity-workspace-nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
