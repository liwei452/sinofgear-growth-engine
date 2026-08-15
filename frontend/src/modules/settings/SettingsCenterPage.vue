<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"
import { RouterLink, useRoute } from "vue-router"

import { currentUserQueryOptions } from "../auth/auth"

type Destination = { label: string; to: string; permission?: string }
type SettingsGroup = {
  title: string
  description: string
  status?: string
  destinations: Destination[]
  administratorOnly?: boolean
}

const currentUser = useQuery(currentUserQueryOptions())
const route = useRoute()
const permissions = computed(() => new Set(currentUser.data.value?.membership.permissions ?? []))
const isAdministrator = computed(() => currentUser.data.value?.membership.role === "ADMINISTRATOR")
const returnTarget = computed(() => {
  const candidate = route.query.from
  if (typeof candidate !== "string" || !candidate.startsWith("/") || candidate.startsWith("//")) return "/"
  const hasUnsafeCharacter = [...candidate].some(character => {
    const codePoint = character.codePointAt(0) ?? 0
    return character === "\\" || codePoint < 32 || codePoint === 127
  })
  if (hasUnsafeCharacter) return "/"
  return candidate
})
const blocked = computed(() => typeof route.query.blocked === "string")

const groups: SettingsGroup[] = [
  {
    title: "公司与产品",
    description: "维护公司资料、产品和经过人工确认的事实。",
    destinations: [
      { label: "公司资料", to: "/company" },
      { label: "产品库", to: "/products", permission: "products.read" },
      { label: "素材与资料理解", to: "/assets", permission: "assets.read" },
    ],
  },
  {
    title: "AI与资料理解",
    description: "资料解析只产生待确认事实，不会自动写入宣传内容。",
    status: "真实 AI Provider 尚未配置",
    destinations: [{ label: "查看上传资料", to: "/assets", permission: "assets.read" }],
  },
  {
    title: "获客与市场",
    description: "选择市场并导入有许可的名单或公开线索。",
    destinations: [{ label: "市场与客户来源", to: "/opportunities" }],
  },
  {
    title: "渠道与发布",
    description: "查看真实连接状态；未连接时使用人工发布包。",
    destinations: [
      { label: "渠道账户", to: "/platform-accounts", permission: "publishing.read" },
      { label: "发布日历", to: "/publishing-calendar", permission: "publishing.read" },
      { label: "手工发布包", to: "/promotion" },
    ],
  },
  {
    title: "CRM与通知",
    description: "CRM、邮件和 Webhook 尚未接入；当前不会向外发送。",
    status: "尚未配置",
    destinations: [],
  },
  {
    title: "团队与权限",
    description: "当前权限来自组织成员角色；成员管理界面尚未开放。",
    status: "由管理员管理",
    destinations: [],
  },
  {
    title: "用量与安全",
    description: "费用预算与安全总览尚未配置；系统不会展示或回显密钥。",
    status: "尚未配置",
    destinations: [],
  },
  {
    title: "高级管理",
    description: "仅管理员可访问知识与高级数据入口。",
    status: "Provider 管理尚未配置",
    administratorOnly: true,
    destinations: [
      { label: "知识库", to: "/knowledge", permission: "knowledge.read" },
      { label: "高级数据", to: "/admin/analytics", permission: "tracking.read" },
    ],
  },
]

const visibleGroups = computed(() => groups
  .filter(group => !group.administratorOnly || isAdministrator.value)
  .map(group => ({
    ...group,
    destinations: group.destinations.filter(destination => (
      !destination.permission || permissions.value.has(destination.permission)
    )),
  })))
</script>

<template>
  <main class="settings-page">
    <header class="settings-heading">
      <div>
        <p class="eyebrow">账户与系统</p>
        <h1>设置中心</h1>
        <p>集中查看真实配置入口；未接入的能力会明确显示为未配置。</p>
      </div>
      <RouterLink class="button button-quiet" :to="returnTarget">返回工作台</RouterLink>
    </header>

    <p v-if="blocked" class="settings-notice" role="status">当前账户没有权限打开刚才的页面，这里只显示你可用的入口。</p>

    <div class="settings-grid">
      <section
        v-for="group in visibleGroups"
        :key="group.title"
        class="settings-card"
        role="region"
        :aria-label="group.title"
      >
        <div>
          <h2>{{ group.title }}</h2>
          <p>{{ group.description }}</p>
        </div>
        <span v-if="group.status" class="settings-status">{{ group.status }}</span>
        <nav v-if="group.destinations.length" :aria-label="`${group.title}入口`">
          <RouterLink v-for="destination in group.destinations" :key="destination.to" :to="destination.to">
            {{ destination.label }}
          </RouterLink>
        </nav>
      </section>
    </div>
  </main>
</template>

<style scoped>
.settings-page { display: grid; gap: 20px; }
.settings-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.settings-heading h1 { margin: 3px 0 8px; }
.settings-heading p { margin: 0; color: var(--sg-muted); }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.settings-notice { margin: 0; border-radius: 10px; background: #eef5fb; padding: 11px 14px; color: #34546e; font-size: .82rem; }
.settings-card { display: grid; align-content: space-between; gap: 16px; min-height: 150px; border: 1px solid var(--sg-line); border-radius: 14px; background: #fff; padding: 20px; }
.settings-card h2 { margin: 0 0 7px; font-size: 1rem; }
.settings-card p { margin: 0; color: var(--sg-muted); font-size: .82rem; line-height: 1.55; }
.settings-status { color: #53697d; font-size: .76rem; font-weight: 800; }
.settings-card nav { display: flex; flex-wrap: wrap; gap: 8px 16px; }
.settings-card nav a { color: var(--sg-brand); font-size: .8rem; font-weight: 850; text-decoration: none; }
@media (max-width: 760px) { .settings-heading { display: grid; }.settings-grid { grid-template-columns: 1fr; } }
</style>
