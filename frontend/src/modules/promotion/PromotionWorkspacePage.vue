<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"
import { useRoute } from "vue-router"

import { ApiError } from "../../api/client"
import BusinessState from "../../shared/components/BusinessState.vue"
import WorkspaceHeader from "../../shared/components/WorkspaceHeader.vue"
import { currentUserQueryOptions } from "../auth/auth"
import { listAssets } from "../assets/api"
import { companyFactsQueryOptions } from "../growth/api"
import { missionsQueryOptions } from "../missions/api"
import { listSocialAccounts, platformAccountKeys } from "../platformAccounts/api"
import { listProducts, productQueryKeys } from "../products/api"
import { promotionSteps } from "./promotionProgress"

const currentUserQuery = useQuery(currentUserQueryOptions())
const companyFactsQuery = useQuery(companyFactsQueryOptions())
const missionsQuery = useQuery(missionsQueryOptions())
const route = useRoute()
const permissions = computed(() => new Set(currentUserQuery.data.value?.membership.permissions ?? []))
const organizationId = computed(() => currentUserQuery.data.value?.organization.id ?? "")
const isAdministrator = computed(() => currentUserQuery.data.value?.membership.role === "ADMINISTRATOR")
const canReadProducts = computed(() => permissions.value.has("products.read"))
const canReadAssets = computed(() => permissions.value.has("assets.read"))
const canReadPublishing = computed(() => permissions.value.has("publishing.read"))

const productsQuery = useQuery({
  queryKey: computed(() => productQueryKeys.list(organizationId.value, { status: "ACTIVE" })),
  queryFn: () => listProducts({ status: "ACTIVE" }),
  enabled: computed(() => Boolean(organizationId.value) && canReadProducts.value),
  retry: false,
})
const assetsQuery = useQuery({
  queryKey: computed(() => ["promotion", ...productQueryKeys.all(organizationId.value), "assets"]),
  queryFn: () => listAssets({ status: "READY" }),
  enabled: computed(() => Boolean(organizationId.value) && canReadAssets.value),
  retry: false,
})
const accountsQuery = useQuery({
  queryKey: computed(() => platformAccountKeys.accounts(organizationId.value)),
  queryFn: listSocialAccounts,
  enabled: computed(() => Boolean(organizationId.value) && canReadPublishing.value),
  retry: false,
})

const requestedMissionId = computed(() => typeof route.query.mission === "string" ? route.query.mission : "")
const selectedMission = computed(() => {
  const missions = missionsQuery.data.value ?? []
  if (requestedMissionId.value) return missions.find(mission => mission.id === requestedMissionId.value) ?? null
  return missions.length === 1 ? missions[0] : null
})
const requiresMissionSelection = computed(() => (missionsQuery.data.value?.length ?? 0) > 1 && !selectedMission.value)
function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403
}

const journeyState = computed<"loading" | "permission" | "forbidden" | "error" | "ready">(() => {
  if (currentUserQuery.isPending.value || companyFactsQuery.isPending.value || missionsQuery.isPending.value) return "loading"
  if (!canReadProducts.value || !canReadAssets.value || !canReadPublishing.value) return "permission"
  if (productsQuery.isPending.value || assetsQuery.isPending.value || accountsQuery.isPending.value) return "loading"
  if ([companyFactsQuery, missionsQuery, productsQuery, assetsQuery, accountsQuery]
    .some(query => query.isError.value && isForbidden(query.error.value))) return "forbidden"
  if (companyFactsQuery.isError.value || missionsQuery.isError.value || productsQuery.isError.value || assetsQuery.isError.value || accountsQuery.isError.value) return "error"
  return "ready"
})
const steps = computed(() => {
  const mission = selectedMission.value
  const verifiedFacts = (companyFactsQuery.data.value ?? []).some(fact => fact.verification_status === "VERIFIED" && !fact.is_demo)
  const productExists = (productsQuery.data.value?.results ?? []).some(product => product.id === mission?.primary_product_id)
  const assetsReady = (assetsQuery.data.value?.results ?? []).some(asset => (
    asset.status === "READY" && Boolean(mission?.primary_product_id)
      && asset.products.some(product => product.id === mission?.primary_product_id)
  ))
  const activeAccounts = (accountsQuery.data.value ?? []).filter(account => account.status === "ACTIVE")
  return promotionSteps({
    companyConfigured: verifiedFacts,
    marketConfigured: Boolean(mission?.target_countries.length),
    icpConfigured: Boolean(mission?.target_industries.length && mission.customer_profile && productExists),
    discoveryStarted: Boolean(mission && (mission.lane_counts.ACQUISITION + mission.lane_counts.OUTREACH > 0)),
    contentPrepared: Boolean(assetsReady || mission?.lane_counts.SOCIAL),
    channelsConfigured: activeAccounts.length > 0,
    approvalReady: mission?.latest_plan?.status === "APPROVED" || mission?.status === "RUNNING",
  }).map((step) => {
    const summary = step.id === "company" && !companyFactsQuery.data.value?.length
      ? "尚无已确认的公司事实。"
      : step.id === "market" && !mission
        ? "尚无已保存的增长任务或目标市场。"
        : step.id === "icp" && !canReadProducts.value
          ? "当前账户无权读取产品目录，无法确认客户画像。"
          : step.id === "content" && !canReadAssets.value
            ? "当前账户无权读取素材，无法确认内容是否已准备。"
            : step.summary
    const eligibleRoute = step.id === "company"
      ? (isAdministrator.value ? "/company" : undefined)
      : step.id === "market"
        ? "/missions"
        : step.id === "icp"
          ? (isAdministrator.value ? "/products" : undefined)
          : step.id === "discovery"
            ? (mission ? `/missions/${mission.id}?view=customer` : "/missions")
            : step.id === "content"
              ? "/assets"
              : step.id === "channels"
                ? (isAdministrator.value ? "/platform-accounts" : undefined)
                : mission ? `/missions/${mission.id}` : "/missions"
    const unavailableRoute = step.state === "current" && !eligibleRoute
    return {
      ...step,
      summary: unavailableRoute ? "需要管理员权限才能继续此步骤，请联系管理员完成配置。" : summary,
      route: eligibleRoute,
    }
  })
})

const currentStep = computed(() => steps.value.find(step => step.state === "current") ?? null)
const statusMessage = computed(() => {
  if (!canReadPublishing.value) return "当前账户无权读取渠道账户；可先继续准备其他步骤。"
  if (accountsQuery.isError.value) return "渠道账户暂时无法读取，尚不能确认接口配置或限制。"
  const active = (accountsQuery.data.value ?? []).filter(account => account.status === "ACTIVE")
  if (!active.length) return "尚未配置有效渠道账户；可继续使用人工发布包。"
  const apiConfigured = active.filter(account => account.publish_mode === "API_AUTO" && account.credential_configured)
  return apiConfigured.length
    ? `${active.length} 个有效渠道账户，其中 ${apiConfigured.length} 个已配置接口凭据。`
    : `${active.length} 个有效渠道账户，尚未配置自动发布接口。`
})

</script>

<template>
  <main class="promotion-page">
    <WorkspaceHeader
      title="开始推广"
      description="按已保存的公司、任务、素材和渠道状态继续推进；页面不会估算或补造进度。"
    />

    <BusinessState
      v-if="journeyState === 'loading'"
      kind="loading" title="正在读取推广记录" message="完成读取后才会确认当前步骤。"
    />
    <BusinessState
      v-else-if="journeyState === 'permission'"
      kind="blocked" title="缺少推广所需查看权限" message="无法确认产品、素材或渠道状态，工作台不会推导进度。"
    />
    <BusinessState
      v-else-if="journeyState === 'forbidden'"
      kind="blocked" title="无权读取推广记录" message="服务端拒绝读取所需记录，工作台不会推导进度。"
    />
    <BusinessState
      v-else-if="journeyState === 'error' && (companyFactsQuery.isError.value || missionsQuery.isError.value || accountsQuery.isError.value)"
      kind="error" title="推广状态暂时无法读取" message="请稍后重试；未读取到的数据不会被标记为已完成。"
      action-label="重新加载" @action="companyFactsQuery.refetch(); missionsQuery.refetch(); accountsQuery.refetch()"
    />
    <BusinessState
      v-else-if="journeyState === 'error'"
      kind="error" title="产品或素材状态暂时无法读取" message="无法确认客户画像或内容准备状态，未读取的数据不会被标记为已完成。"
      action-label="重新加载" @action="productsQuery.refetch(); assetsQuery.refetch()"
    />

    <section v-if="journeyState === 'ready' && requiresMissionSelection" class="mission-selection" aria-labelledby="mission-selection-title">
      <h2 id="mission-selection-title">请选择要推进的增长任务</h2>
      <p>不同任务的市场、客户、内容与审核记录互不混用。</p>
      <nav aria-label="选择增长任务">
        <RouterLink v-for="mission in missionsQuery.data.value" :key="mission.id" :to="`/promotion?mission=${encodeURIComponent(mission.id)}`">
          选择 {{ mission.title }}
        </RouterLink>
      </nav>
    </section>

    <section v-else-if="journeyState === 'ready'" class="journey" aria-labelledby="promotion-journey-title">
      <div class="journey-heading">
        <h2 id="promotion-journey-title">推广工作台</h2>
        <p>{{ selectedMission ? `当前任务：${selectedMission.title}` : "尚未创建增长任务" }}</p>
      </div>
      <ol class="promotion-steps">
        <li v-for="step in steps" :key="step.id" :class="`step-${step.state}`">
          <div class="step-copy">
            <span class="step-state">{{ step.state === "current" ? "当前步骤" : step.state === "complete" ? "已完成" : step.state === "blocked" ? "等待前置条件" : "后续步骤" }}</span>
            <h3>{{ step.label }}</h3>
            <p>{{ step.id === "channels" ? statusMessage : step.summary }}</p>
            <p v-if="step.id === 'approval'" class="safety-note">审核不会自动对外发布或发送内容。</p>
          </div>
          <RouterLink v-if="step.state === 'current' && step.route" class="button button-primary" :to="step.route">
            继续 {{ step.label }}
          </RouterLink>
        </li>
      </ol>
    </section>

    <BusinessState
      v-if="journeyState === 'ready' && selectedMission && !currentStep && steps.every(step => step.state === 'complete')"
      kind="success" title="推广准备记录已齐全" message="请在任务详情中确认后续执行状态。"
    />
  </main>
</template>

<style scoped>
.promotion-page { display: grid; gap: 18px; }
.journey { border: 1px solid var(--sg-line); border-radius: 14px; background: #fff; padding: 18px; }
.mission-selection { display: grid; gap: 10px; border: 1px solid var(--sg-line); border-radius: 14px; background: #fff; padding: 18px; }
.mission-selection h2, .mission-selection p { margin: 0; }
.mission-selection p { color: var(--sg-muted); font-size: .82rem; }
.mission-selection nav { display: flex; flex-wrap: wrap; gap: 10px; }
.mission-selection a { color: var(--sg-brand); font-size: .84rem; font-weight: 800; text-decoration: none; }
.journey-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 12px; }
.journey-heading h2, .step-copy h3, .step-copy p { margin: 0; }
.journey-heading p, .step-copy p { color: var(--sg-muted); font-size: .82rem; line-height: 1.5; }
.promotion-steps { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }
.promotion-steps li { display: flex; align-items: center; justify-content: space-between; gap: 16px; border-top: 1px solid var(--sg-line); padding: 14px 0; }
.promotion-steps li:first-child { border-top: 0; }
.step-copy { display: grid; gap: 5px; }
.step-copy h3 { font-size: .95rem; }
.step-state { color: var(--sg-muted); font-size: .72rem; font-weight: 800; }
.step-current .step-state { color: var(--sg-brand); }
.step-complete { opacity: .78; }
.step-blocked { opacity: .68; }
.safety-note { color: #7b5d22 !important; }
@media (max-width: 620px) { .journey-heading, .promotion-steps li { align-items: flex-start; flex-direction: column; } }
</style>
