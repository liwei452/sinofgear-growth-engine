<script setup lang="ts">
import { RouterLink } from "vue-router"

const workspaces = [
  { label: "今日", to: "/" },
  { label: "开始推广", to: "/promotion" },
  { label: "客户机会", to: "/opportunities" },
  { label: "内容与发布", to: "/content-factory" },
  { label: "效果", to: "/analytics" },
]
</script>

<template>
  <section class="help-page" aria-labelledby="help-title">
    <p class="eyebrow">使用帮助</p>
    <h1 id="help-title">从业务目标开始</h1>
    <p>从下列工作区选择当前要推进的业务目标。系统可以协助准备内容和外联工作，但发布与外联都需要人工批准后才能执行。</p>
    <nav aria-label="业务工作区">
      <RouterLink v-for="workspace in workspaces" :key="workspace.to" :to="workspace.to" class="workspace-link">
        {{ workspace.label }}
      </RouterLink>
    </nav>
  </section>
</template>

<style scoped>
.help-page { max-width: 48rem; }
.help-page nav { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-top: 1.5rem; }
.help-page a { display: inline-flex; align-items: center; min-height: 44px; padding: 0 8px; color: var(--color-primary, #1d4ed8); font-weight: 600; }
</style>
