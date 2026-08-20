<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed, ref } from "vue"
import { RouterLink, useRoute } from "vue-router"

import { currentUserQueryOptions } from "../auth/auth"
import { listSocialAccounts, platformAccountKeys } from "../platformAccounts/api"
import { getProductAIStatus } from "./api"

type Destination = { label: string; to: string; permission?: string; administratorOnly?: boolean }
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
const organizationId = computed(() => currentUser.data.value?.organization.id ?? "")
const canReadPublishing = computed(() => permissions.value.has("publishing.read"))
const socialAccounts = useQuery({
  queryKey: computed(() => platformAccountKeys.accounts(organizationId.value)),
  queryFn: listSocialAccounts,
  enabled: computed(() => Boolean(organizationId.value) && canReadPublishing.value),
})
const productAI = useQuery({
  queryKey: computed(() => ["settings", organizationId.value, "product-ai"]),
  queryFn: getProductAIStatus,
  enabled: computed(() => Boolean(organizationId.value)),
})
const aiStatus = computed(() => {
  if (productAI.isPending.value) return "正在读取产品 AI 状态"
  if (productAI.isError.value) return "产品 AI 状态暂时无法读取"
  const status = productAI.data.value
  if (!status) return "产品 AI 状态尚未配置"
  if (status.mode === "CONFIGURED_AI") return "可生成待确认事实"
  if (status.mode === "CONFIGURATION_REQUIRED") return "当前不能生成待确认事实；真实 AI 配置不完整"
  return "当前不能生成待确认事实"
})
const channelStatus = computed(() => {
  if (!canReadPublishing.value) return "没有渠道账户查看权限；手工发布包仍可用"
  if (socialAccounts.isPending.value) return "正在读取渠道账户"
  if (socialAccounts.isError.value) return "渠道状态暂时无法读取"
  const active = (socialAccounts.data.value ?? []).filter(account => account.status === "ACTIVE")
  if (!active.length) return "尚未添加渠道账户；手工发布包仍可用"
  const configured = active.filter(account => account.publish_mode === "API_AUTO" && account.credential_configured)
  if (!configured.length) return `${active.length} 个有效渠道账户；官方接口尚未配置`
  return `${active.length} 个有效渠道账户，其中 ${configured.length} 个已配置接口凭据`
})
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
const advancedOpen = ref(false)

const primaryGroups: SettingsGroup[] = [
  {
    title: "当前阻塞",
    description: "显示会影响当前业务推进的真实缺口；没有阻塞时不会虚构待办。",
    status: "当前没有已记录的阻塞",
    destinations: [{ label: "查看增长任务", to: "/missions", permission: "missions.read" }],
  },
  {
    title: "AI 模型",
    description: "模型状态会影响产品资料能否生成待确认事实，不会代替人工确认。",
    destinations: [{ label: "查看资料与事实", to: "/company", administratorOnly: true }],
  },
  {
    title: "推广与发布连接",
    description: "连接状态决定内容能否进入对应渠道；未连接时仍可使用人工发布包。",
    destinations: [
      { label: "渠道账户", to: "/platform-accounts", permission: "publishing.read", administratorOnly: true },
      { label: "内容审核与发布", to: "/content-factory", permission: "publishing.read" },
    ],
  },
  {
    title: "通知与 CRM",
    description: "CRM、邮件和 Webhook 尚未接入；当前不会向外发送。",
    status: "尚未配置",
    destinations: [],
  },
]

const advancedGroups: SettingsGroup[] = [
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
    title: "公司与产品",
    description: "维护公司资料、产品和经过人工确认的事实。",
    administratorOnly: true,
    destinations: [
      { label: "公司资料", to: "/company" },
      { label: "产品库", to: "/products", permission: "products.read" },
      { label: "素材与资料理解", to: "/assets", permission: "assets.read" },
    ],
  },
  {
    title: "获客与市场",
    description: "选择市场并导入有许可的名单或公开线索。",
    administratorOnly: true,
    destinations: [
      { label: "谷歌地图自动获客", to: "/maps-discovery", permission: "leads.manage" },
      { label: "市场与客户来源", to: "/missions", permission: "missions.read" },
    ],
  },
  {
    title: "高级管理",
    description: "仅管理员可访问知识与高级数据入口。",
    status: "真实模型与预算仅由管理员管理",
    administratorOnly: true,
    destinations: [
      { label: "AI 模型", to: "/settings/ai-model" },
      { label: "知识库", to: "/knowledge", permission: "knowledge.read" },
      { label: "数据归因", to: "/attribution", permission: "missions.read" },
    ],
  },
]

function visibleGroups(groups: SettingsGroup[]) {
  return groups
  .filter(group => !group.administratorOnly || isAdministrator.value)
  .map(group => ({
    ...group,
    status: group.title === "推广与发布连接" ? channelStatus.value
      : group.title === "AI 模型" ? aiStatus.value
        : group.title === "当前阻塞" && blocked.value ? "当前页面缺少所需权限，请联系管理员" : group.status,
    destinations: group.destinations.filter(destination => (
      (!destination.permission || permissions.value.has(destination.permission))
      && (!destination.administratorOnly || isAdministrator.value)
    )),
  }))
}
const visiblePrimaryGroups = computed(() => visibleGroups(primaryGroups))
const visibleAdvancedGroups = computed(() => visibleGroups(advancedGroups))
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
        v-for="group in visiblePrimaryGroups"
        :key="group.title"
        class="settings-card"
        role="region"
        :aria-label="group.title"
        data-testid="settings-primary-group"
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
    <button v-if="isAdministrator" class="button button-quiet" type="button" :aria-expanded="advancedOpen" @click="advancedOpen = !advancedOpen">{{ advancedOpen ? "收起高级设置" : "展开高级设置" }}</button>
    <div v-if="advancedOpen && visibleAdvancedGroups.length" class="settings-grid">
      <section v-for="group in visibleAdvancedGroups" :key="group.title" class="settings-card" role="region" :aria-label="group.title">
        <div><h2>{{ group.title }}</h2><p>{{ group.description }}</p></div>
        <span v-if="group.status" class="settings-status">{{ group.status }}</span>
        <nav v-if="group.destinations.length" :aria-label="`${group.title}入口`"><RouterLink v-for="destination in group.destinations" :key="destination.to" :to="destination.to">{{ destination.label }}</RouterLink></nav>
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
