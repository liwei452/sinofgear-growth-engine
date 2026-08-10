<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"
import { RouterLink } from "vue-router"

import { currentUserQueryOptions } from "../auth/auth"

const currentUserQuery = useQuery(currentUserQueryOptions())
const canReadCampaigns = computed(() =>
  currentUserQuery.data.value?.membership.permissions.includes("campaigns.read") ?? false)
</script>

<template>
  <section class="card placeholder-page" aria-labelledby="promotion-title">
    <span class="placeholder-icon" aria-hidden="true">↗</span>
    <p class="eyebrow">推广入口</p>
    <h1 id="promotion-title">推广</h1>
    <p>推广工作区正在准备中</p>
    <p class="muted">现阶段可以在 AI 内容工厂查看和处理已经接入的推广内容，不会在这里展示尚未接入的能力。</p>
    <RouterLink
      v-if="canReadCampaigns"
      class="button button-primary"
      to="/content-factory"
    >
      前往 AI 内容工厂
    </RouterLink>
    <p v-else>你当前没有使用内容工厂的权限；如需开展推广，请联系管理员。</p>
  </section>
</template>
