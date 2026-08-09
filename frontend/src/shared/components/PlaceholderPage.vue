<script setup lang="ts">
import { computed } from "vue"
import { RouterLink, useRoute } from "vue-router"

const route = useRoute()
const title = computed(() => String(route.meta.title ?? "功能"))
</script>

<template>
  <section class="card placeholder-page" :aria-labelledby="`placeholder-${String(route.name ?? 'page')}`">
    <span class="placeholder-icon" aria-hidden="true">↗</span>
    <p class="eyebrow">功能即将开放</p>
    <h1 :id="`placeholder-${String(route.name ?? 'page')}`">{{ title }}</h1>
    <p>这个入口已经准备好，具体业务能力将在后续阶段接入。</p>
    <p class="muted">本阶段先确保登录、导航和使用路径稳定，不展示虚构业务数据。</p>
    <div class="placeholder-actions">
      <RouterLink class="button button-primary" to="/">返回首页</RouterLink>
      <RouterLink class="text-link" to="/#next-steps">查看下一步建议</RouterLink>
    </div>
  </section>
</template>
