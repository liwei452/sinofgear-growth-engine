<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"

import { missionsQueryOptions } from "../missions/api"
import TodayWorkInbox from "../workItems/TodayWorkInbox.vue"

const missionsQuery = useQuery(missionsQueryOptions())
const runningMissions = computed(
  () => (missionsQuery.data.value ?? []).filter((mission) => mission.status === "RUNNING"),
)
</script>

<template>
  <main class="today-page">
    <header class="today-hero">
      <div>
        <p class="eyebrow">TODAY</p>
        <h1>今日待办</h1>
        <p>先处理需要你判断的事项；Agent 自动完成的工作会进入任务时间线。</p>
      </div>
      <RouterLink v-if="!runningMissions.length" class="button button-primary" to="/missions">
        创建增长任务
      </RouterLink>
    </header>

    <TodayWorkInbox />
  </main>
</template>

<style scoped>
.today-page { display: grid; gap: 18px; }
.today-hero { display: flex; align-items: center; justify-content: space-between; gap: 20px; border-radius: 20px; background: linear-gradient(120deg, #0b3b8f 0%, #0875eb 60%, #3eb6ff 100%); padding: 24px 28px; color: #fff; }
.today-hero h1 { margin: 4px 0 7px; font-size: clamp(1.5rem, 2vw, 1.9rem); }
.today-hero p { margin: 0; color: #eaf5ff; font-size: .82rem; line-height: 1.55; }
.eyebrow { margin: 0; color: #bfe0ff; font-size: .65rem; font-weight: 900; letter-spacing: .1em; }
</style>
