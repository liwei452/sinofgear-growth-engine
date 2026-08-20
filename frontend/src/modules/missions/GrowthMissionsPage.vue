<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import { currentUserQueryOptions } from "../auth/auth"
import { missionsQueryOptions } from "./api"
import GrowthMissionCreateDialog from "./GrowthMissionCreateDialog.vue"

const queryClient = useQueryClient()
const currentUserQuery = useQuery(currentUserQueryOptions())
const missionsQuery = useQuery(missionsQueryOptions())

const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const canManage = computed(() => permissions.value.includes("missions.manage"))
const createOpen = ref(false)

const missions = computed(() => missionsQuery.data.value ?? [])

function onCreated(): void {
  createOpen.value = false
  void queryClient.invalidateQueries({ queryKey: ["growth", "missions"] })
}
</script>

<template>
  <section class="missions-page">
    <header class="missions-hero">
      <div>
        <p class="eyebrow">GROWTH MISSIONS</p>
        <h1>增长任务</h1>
        <p>以目标市场、产品、周期和结果指标为主线，统一推进客户开发与社媒增长。</p>
      </div>
      <button
        v-if="canManage"
        class="button button-primary"
        type="button"
        @click="createOpen = true"
      >
        创建增长任务
      </button>
    </header>

    <p v-if="missionsQuery.isLoading.value" class="empty-card">正在读取增长任务…</p>
    <p v-else-if="missionsQuery.isError.value" class="empty-card error" role="alert">
      增长任务暂时无法读取。
    </p>
    <div v-else-if="missions.length" class="mission-grid">
      <RouterLink
        v-for="mission in missions"
        :key="mission.id"
        class="mission-card"
        :to="`/missions/${mission.id}`"
      >
        <p class="eyebrow">{{ mission.status }}</p>
        <h2>{{ mission.title }}</h2>
        <p class="objective">{{ mission.objective }}</p>
        <dl class="mission-facts">
          <div>
            <dt>周期</dt>
            <dd>{{ mission.start_date }} ~ {{ mission.end_date }}</dd>
          </div>
          <div>
            <dt>健康状态</dt>
            <dd>{{ mission.health_status }}</dd>
          </div>
        </dl>
        <div class="lane-summary">
          <span>客户开发 {{ mission.lane_counts.ACQUISITION + mission.lane_counts.OUTREACH }}</span>
          <span>社媒增长 {{ mission.lane_counts.SOCIAL }}</span>
          <span>RFQ {{ mission.target_rfq_count }}</span>
        </div>
      </RouterLink>
    </div>
    <div v-else class="empty-card">
      <strong>还没有增长任务</strong>
      <p>管理者可以从右上角创建一个增长任务，再让 Agent 生成两条执行线计划。</p>
    </div>

    <GrowthMissionCreateDialog
      v-if="createOpen"
      :busy="false"
      @cancel="createOpen = false"
      @created="onCreated"
    />
  </section>
</template>

<style scoped>
.missions-page { display: grid; gap: 18px; }
.missions-hero { display: flex; align-items: center; justify-content: space-between; gap: 20px; border-radius: 20px; background: linear-gradient(120deg, var(--sg-brand-deep) 0%, var(--sg-brand-strong) 60%, var(--sg-brand-light) 100%); padding: 26px 30px; color: #fff; }
.missions-hero h1 { margin: 4px 0 7px; font-size: clamp(1.5rem, 2vw, 1.9rem); }
.missions-hero p:last-child { max-width: 720px; margin: 0; color: #eaf5ff; font-size: .82rem; line-height: 1.6; }
.eyebrow { margin: 0; color: #bfe0ff; font-size: .65rem; font-weight: 900; letter-spacing: .1em; }
.mission-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.mission-card { display: grid; gap: 10px; border: 1px solid #e5ecf6; border-radius: 16px; background: #fff; padding: 18px; text-decoration: none; color: inherit; }
.mission-card h2 { margin: 0; font-size: 1.05rem; }
.mission-card .eyebrow { color: var(--sg-brand); }
.objective { margin: 0; color: var(--sg-muted); font-size: .8rem; line-height: 1.5; }
.mission-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 0; }
.mission-facts dt { color: var(--sg-muted); font-size: .68rem; }
.mission-facts dd { margin: 2px 0 0; font-size: .78rem; }
.lane-summary { display: flex; flex-wrap: wrap; gap: 6px; }
.lane-summary span { border-radius: 999px; background: #f0f5fc; padding: 4px 8px; color: #2a5aa6; font-size: .68rem; }
.empty-card { display: grid; justify-items: start; gap: 8px; margin: 0; border: 1px dashed #bfd9f4; border-radius: 16px; background: #fff; padding: 24px; color: var(--sg-muted); }
.empty-card p { margin: 0; font-size: .78rem; }
.error { color: var(--sg-danger); }
</style>
