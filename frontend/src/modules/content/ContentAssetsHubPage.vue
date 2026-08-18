<script setup lang="ts">
const destinations = [
  { label: "任务内容", to: "/missions?view=content", description: "从增长任务进入内容生成。" },
  { label: "已批准内容", to: "/reviews?status=approved", description: "查看已批准并可复用的内容。" },
  { label: "素材库", to: "/assets", description: "管理图片、视频与文档素材。" },
  { label: "知识参考", to: "/knowledge", description: "查看已确认的产品与公司知识。" },
]
</script>

<template>
  <main class="content-hub">
    <header class="hub-hero">
      <div>
        <p class="eyebrow">CONTENT & ASSETS</p>
        <h1>内容与素材</h1>
        <p>集中管理任务内容、已批准内容、素材与知识参考。</p>
      </div>
    </header>
    <div class="hub-grid">
      <RouterLink v-for="item in destinations" :key="item.to" class="hub-card" :to="item.to">
        <h2>{{ item.label }}</h2>
        <p>{{ item.description }}</p>
      </RouterLink>
    </div>
  </main>
</template>

<style scoped>
.content-hub { display: grid; gap: 16px; }
.hub-hero { border-radius: 20px; background: linear-gradient(120deg, #0b3b8f 0%, #0875eb 60%, #3eb6ff 100%); padding: 24px 28px; color: #fff; }
.hub-hero h1 { margin: 4px 0 7px; }
.hub-hero p { margin: 0; color: #eaf5ff; font-size: .82rem; }
.eyebrow { margin: 0; color: #bfe0ff; font-size: .65rem; font-weight: 900; letter-spacing: .1em; }
.hub-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
.hub-card { display: grid; gap: 7px; border: 1px solid #e5ecf6; border-radius: 16px; background: #fff; padding: 18px; text-decoration: none; color: inherit; }
.hub-card h2 { margin: 0; font-size: 1rem; }
.hub-card p { margin: 0; color: var(--sg-muted); font-size: .78rem; line-height: 1.5; }
</style>
