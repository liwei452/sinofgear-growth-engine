<script setup lang="ts">
import AppIcon, { type IconName } from "../../shared/components/AppIcon.vue"

const props = defineProps<{
  opportunities: number | null
  approvals: number | null
  readyToPublish: number | null
  inquiries: number | null
}>()

const items: Array<{
  key: keyof typeof props
  label: string
  icon: IconName
  tone: string
}> = [
  { key: "opportunities", label: "新机会", icon: "users-round", tone: "blue" },
  { key: "approvals", label: "等待审批", icon: "clipboard-check", tone: "amber" },
  { key: "readyToPublish", label: "待发布", icon: "send", tone: "violet" },
  { key: "inquiries", label: "有效询盘", icon: "inbox", tone: "green" },
]
</script>

<template>
  <section class="dashboard-kpis" aria-label="今日核心状态">
    <article v-for="item in items" :key="item.key" :class="`kpi-${item.tone}`">
      <span class="kpi-icon" aria-hidden="true"><AppIcon :name="item.icon" :size="21" /></span>
      <div>
        <span>{{ item.label }}</span>
        <strong>{{ props[item.key] === null ? "无数据" : props[item.key] }}</strong>
      </div>
    </article>
  </section>
</template>

<style scoped>
.dashboard-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.dashboard-kpis article { display: flex; min-width: 0; align-items: center; gap: 13px; border: 1px solid var(--sg-line); border-radius: 16px; background: white; padding: 18px; box-shadow: var(--sg-shadow-sm); }
.kpi-icon { display: grid; width: 44px; height: 44px; flex: 0 0 auto; place-items: center; border-radius: 13px; background: var(--sg-brand-soft); color: var(--sg-brand); }
.kpi-amber .kpi-icon { background: #fff5e6; color: #e88d18; }
.kpi-violet .kpi-icon { background: #f1edff; color: #7356d8; }
.kpi-green .kpi-icon { background: var(--sg-success-soft); color: var(--sg-success); }
.dashboard-kpis div { display: grid; gap: 4px; min-width: 0; }
.dashboard-kpis span:not(.kpi-icon) { color: var(--sg-muted); font-size: .8rem; }
.dashboard-kpis strong { overflow: hidden; color: var(--sg-ink); font-size: 1.35rem; text-overflow: ellipsis; }
@media (max-width: 980px) { .dashboard-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 540px) { .dashboard-kpis { grid-template-columns: 1fr; }.dashboard-kpis article { padding: 14px; } }
</style>
