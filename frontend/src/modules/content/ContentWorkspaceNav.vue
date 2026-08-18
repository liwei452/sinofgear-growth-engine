<script setup lang="ts">
import { RouterLink } from "vue-router"

import AppIcon, { type IconName } from "../../shared/components/AppIcon.vue"

type ContentWorkspace = "create" | "review" | "calendar" | "accounts"

defineProps<{
  active: ContentWorkspace
}>()

const items: Array<{ id: ContentWorkspace; label: string; to: string; icon: IconName }> = [
  { id: "create", label: "创建内容", to: "/content-factory", icon: "sparkles" },
  { id: "review", label: "审核内容", to: "/reviews", icon: "clipboard-check" },
  { id: "calendar", label: "发布日历", to: "/publishing-calendar", icon: "calendar-clock" },
  { id: "accounts", label: "平台账户", to: "/platform-accounts", icon: "share-2" },
]
</script>

<template>
  <nav class="content-workspace-nav" aria-label="内容与发布工作区">
    <RouterLink
      v-for="item in items"
      :key="item.id"
      :to="item.to"
      :class="{ active: active === item.id }"
      :aria-current="active === item.id ? 'page' : undefined"
    >
      <AppIcon :name="item.icon" :size="18" />
      <span>{{ item.label }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.content-workspace-nav {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  border: 1px solid var(--sg-line);
  border-radius: 14px;
  background: #fff;
  padding: 6px;
  box-shadow: 0 3px 16px rgb(23 34 49 / 4%);
}

a {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 44px;
  border-radius: 9px;
  color: var(--sg-muted);
  font-size: .875rem;
  font-weight: 800;
  text-decoration: none;
}

a:hover,
a:focus-visible {
  background: #f3f6f9;
  color: var(--sg-ink);
}

a.active {
  background: var(--sg-brand);
  color: #fff;
  box-shadow: 0 4px 12px rgb(18 59 92 / 18%);
}

@media (max-width: 640px) {
  .content-workspace-nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
