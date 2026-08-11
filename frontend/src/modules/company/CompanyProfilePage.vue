<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"
import { RouterLink } from "vue-router"

import AppIcon from "../../shared/components/AppIcon.vue"
import StatusBadge from "../../shared/components/StatusBadge.vue"
import { assetKeys, listAssets } from "../assets/api"
import { currentUserQueryOptions } from "../auth/auth"
import { knowledgeQueryKeys, listConcepts, listEvidence, type ConceptType } from "../knowledge/api"
import { listProducts, productQueryKeys } from "../products/api"

const currentUserQuery = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUserQuery.data.value?.organization.id ?? "")
const organizationName = computed(() => currentUserQuery.data.value?.organization.name?.trim() || "公司名称暂不可用")
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const has = (permission: string): boolean => permissions.value.includes(permission)
const canReadProducts = computed(() => has("products.read"))
const canReadKnowledge = computed(() => has("knowledge.read"))
const canReadAssets = computed(() => has("assets.read"))
const canManageProducts = computed(() => has("products.manage"))
const canCreateKnowledge = computed(() => has("knowledge.create"))
const canManageAssets = computed(() => has("assets.manage"))

const productsQuery = useQuery({
  queryKey: computed(() => productQueryKeys.list(organizationId.value, { status: "ACTIVE" })),
  queryFn: ({ signal }) => listProducts({ status: "ACTIVE" }, { signal }),
  enabled: computed(() => Boolean(organizationId.value) && canReadProducts.value),
  retry: false,
})
const knowledgeQuery = useQuery({
  queryKey: computed(() => [...knowledgeQueryKeys.concepts(organizationId.value), "approved-company"]),
  queryFn: ({ signal }) => listConcepts({ signal, status: "APPROVED" }),
  enabled: computed(() => Boolean(organizationId.value) && canReadKnowledge.value),
  retry: false,
})
const evidenceQuery = useQuery({
  queryKey: computed(() => [...knowledgeQueryKeys.evidence(organizationId.value), "approved-company"]),
  queryFn: ({ signal }) => listEvidence({ signal, status: "APPROVED" }),
  enabled: computed(() => Boolean(organizationId.value) && canReadKnowledge.value),
  retry: false,
})
const assetsQuery = useQuery({
  queryKey: computed(() => assetKeys.list(organizationId.value, { status: "ACTIVE" })),
  queryFn: ({ signal }) => listAssets({ status: "ACTIVE" }, { signal }),
  enabled: computed(() => Boolean(organizationId.value) && canReadAssets.value),
  retry: false,
})

const products = computed(() => (productsQuery.data.value?.results ?? [])
  .filter((item) => item.status === "ACTIVE"))
const concepts = computed(() => (knowledgeQuery.data.value ?? [])
  .filter((item) => item.status === "APPROVED"))
const assets = computed(() => (assetsQuery.data.value?.results ?? [])
  .filter((item) => item.status === "ACTIVE"))
const evidence = computed(() => (evidenceQuery.data.value ?? [])
  .filter((item) => item.status === "APPROVED"))
const unique = (values: Array<string | null | undefined>) => [...new Set(
  values.map((value) => value?.trim()).filter((value): value is string => Boolean(value)),
)]
const conceptLabels = (types: ConceptType[]) => unique(concepts.value
  .filter((concept) => types.includes(concept.concept_type))
  .map((concept) => concept.label_zh || concept.label_en))
const linkedLabels = (roles: string[]) => unique(products.value.flatMap((item) =>
  (item.concept_links ?? [])
    .filter((link) => roles.includes(link.role))
    .map((link) => link.concept?.label_zh || link.concept?.label_en),
))
const productNames = computed(() => products.value.map((item) =>
  item.name_zh?.trim() || item.name_en?.trim() || "名称暂不可用"))
const capabilities = computed(() => unique([
  ...products.value.flatMap((item) => item.manufacturing_capabilities ?? []),
  ...products.value.flatMap((item) => item.inspection_capabilities ?? []),
  ...conceptLabels(["CAPABILITY"]),
  ...linkedLabels(["CAPABILITY"]),
]))
const industries = computed(() => conceptLabels(["INDUSTRY"]))
const processes = computed(() => unique([...conceptLabels(["PROCESS"]), ...linkedLabels(["PROCESS"])]))
const standards = computed(() => unique([...conceptLabels(["STANDARD"]), ...linkedLabels(["STANDARD"])]))
const evidenceCount = computed(() => new Set(evidence.value.map((item) => item.id)).size)

const coverage = computed(() => [
  Boolean(organizationId.value && organizationName.value !== "公司名称暂不可用"),
  products.value.length > 0,
  capabilities.value.length > 0,
  industries.value.length > 0,
  processes.value.length > 0,
  standards.value.length > 0,
  evidenceCount.value > 0,
  assets.value.length > 0,
].filter(Boolean).length)
const canConfirmEverySource = computed(() => canReadProducts.value && canReadKnowledge.value && canReadAssets.value)
const sourcesPending = computed(() => (
  (canReadProducts.value && productsQuery.isPending.value)
  || (canReadKnowledge.value && (knowledgeQuery.isPending.value || evidenceQuery.isPending.value))
  || (canReadAssets.value && assetsQuery.isPending.value)
))
const sourceFailed = computed(() => (
  (canReadProducts.value && productsQuery.isError.value)
  || (canReadKnowledge.value && (knowledgeQuery.isError.value || evidenceQuery.isError.value))
  || (canReadAssets.value && assetsQuery.isError.value)
))
const coverageText = computed(() => {
  if (sourcesPending.value) return "正在核对真实资料"
  if (sourceFailed.value) return `当前可确认 ${coverage.value} 项；读取失败的资料未计为缺失`
  return canConfirmEverySource.value
    ? `已覆盖 ${coverage.value} 项，共 8 项`
    : `当前可确认 ${coverage.value} 项；无权限的资料未计为缺失`
})

type Gap = { title: string; explanation: string; to: string; action: string; allowed: boolean }
const gaps = computed<Gap[]>(() => {
  const result: Gap[] = []
  const productsReady = canReadProducts.value && productsQuery.isSuccess.value
  const knowledgeReady = canReadKnowledge.value && knowledgeQuery.isSuccess.value
  const evidenceReady = canReadKnowledge.value && evidenceQuery.isSuccess.value
  const assetsReady = canReadAssets.value && assetsQuery.isSuccess.value
  if (productsReady && !products.value.length) result.push({ title: "补充产品", explanation: "让 AI 知道实际销售的产品和交付范围。", to: "/products", action: "去产品库补充产品", allowed: canManageProducts.value })
  if (productsReady && knowledgeReady && !capabilities.value.length) result.push({ title: "补充能力", explanation: "记录制造与检测能力，避免 AI 猜测。", to: "/products", action: "去产品库补充能力", allowed: canManageProducts.value })
  if (knowledgeReady && !industries.value.length) result.push({ title: "补充行业", explanation: "记录真实服务行业，帮助 AI 缩小目标范围。", to: "/knowledge", action: "去知识库补充行业", allowed: canCreateKnowledge.value })
  if (knowledgeReady && !processes.value.length) result.push({ title: "补充工艺", explanation: "记录已确认的加工工艺。", to: "/knowledge", action: "去知识库补充工艺", allowed: canCreateKnowledge.value })
  if (knowledgeReady && !standards.value.length) result.push({ title: "补充标准", explanation: "记录适用标准，减少对外表达风险。", to: "/knowledge", action: "去知识库补充标准", allowed: canCreateKnowledge.value })
  if (knowledgeReady && evidenceReady && !evidenceCount.value) result.push({ title: "补充证据", explanation: "为产品、能力和标准补充可追溯依据。", to: "/knowledge", action: "去知识库补充证据", allowed: canCreateKnowledge.value })
  if (assetsReady && !assets.value.length) result.push({ title: "上传素材", explanation: "上传真实图片、视频或文档供内容使用。", to: "/assets", action: "去素材库上传素材", allowed: canManageAssets.value })
  return result
})

function productCountLabel(count: number): string { return `当前页有 ${count} 个产品` }
function assetCountLabel(count: number): string { return `当前页有 ${count} 份素材` }
function refetchCapabilities() {
  if (canReadProducts.value) void productsQuery.refetch()
  if (canReadKnowledge.value) void knowledgeQuery.refetch()
}
</script>

<template>
  <main class="page-stack company-profile-page">
    <header class="company-profile-header">
      <div>
        <p class="eyebrow">我的公司</p>
        <h1>AI 对公司的了解</h1>
        <p>以下内容只来自当前组织可读取的真实资料；缺失项不会由 AI 自行补写。</p>
      </div>
    </header>

    <section class="coverage-card" role="region" aria-label="资料完整度">
      <div><p class="eyebrow">真实资料覆盖</p><h2>{{ coverageText }}</h2><p>检查身份、产品、能力、行业、工艺、标准、证据和素材八类资料。</p></div>
      <StatusBadge :tone="coverage === 8 && !sourcesPending && !sourceFailed ? 'success' : 'warning'" :label="sourcesPending ? '正在核对' : coverage === 8 && !sourceFailed ? '资料已覆盖' : '仍有可补充项'" />
    </section>

    <section class="gap-panel" role="region" aria-label="建议补充">
      <div class="section-heading"><div><p class="eyebrow">优先处理缺口</p><h2>建议补充</h2></div><span>{{ gaps.length }} 项</span></div>
      <p v-if="sourcesPending" role="status">正在核对可见资料…</p>
      <p v-else-if="!gaps.length">当前没有能确认的资料缺口。无权限查看的来源不会被误判为缺失。</p>
      <ol v-else class="gap-list">
        <li v-for="gap in gaps" :key="gap.title">
          <div><strong>{{ gap.title }}</strong><p>{{ gap.explanation }}</p></div>
          <RouterLink v-if="gap.allowed" class="primary-action" :to="gap.to">{{ gap.action }}</RouterLink>
          <span v-else class="muted">请联系管理员补充</span>
        </li>
      </ol>
    </section>

    <div class="knowledge-grid">
      <section class="knowledge-card identity-card" role="region" aria-label="公司身份">
        <div class="card-title"><AppIcon name="company" /><h2>公司身份</h2></div>
        <strong>{{ organizationName }}</strong><p>来自当前登录组织。</p>
      </section>

      <section class="knowledge-card" role="region" aria-label="产品">
        <div class="card-title"><AppIcon name="company" /><h2>产品</h2></div>
        <p v-if="!canReadProducts">你没有查看产品资料的权限。</p>
        <p v-else-if="productsQuery.isPending.value" role="status">正在读取产品资料…</p>
        <div v-else-if="productsQuery.isError.value" role="alert"><p>产品资料暂时无法读取。</p><button type="button" @click="productsQuery.refetch()">重新加载产品资料</button></div>
        <template v-else>
          <p v-if="products.length">{{ productCountLabel(products.length) }}</p>
          <div v-if="products.length" class="tag-list"><span v-for="(name, index) in productNames" :key="`${name}-${index}`">{{ name }}</span></div>
          <div v-else><strong>还没有产品资料</strong><p>{{ canManageProducts ? "先记录真实产品和交付范围。" : "如需补充，请联系管理员。" }}</p></div>
          <RouterLink class="text-link" to="/products">{{ products.length ? (canManageProducts ? "管理产品资料" : "查看产品资料") : (canManageProducts ? "去产品库补充" : "查看产品库") }}</RouterLink>
          <p v-if="products.length && !canManageProducts" class="muted">如需补充或编辑，请联系管理员。</p>
        </template>
      </section>

      <section class="knowledge-card" role="region" aria-label="能力">
        <div class="card-title"><AppIcon name="settings" /><h2>能力</h2></div>
        <p v-if="!canReadProducts && !canReadKnowledge">你没有查看能力资料的权限。</p>
        <p v-else-if="(canReadProducts && productsQuery.isPending.value) || (canReadKnowledge && knowledgeQuery.isPending.value)" role="status">正在读取能力资料…</p>
        <div v-else-if="(canReadProducts && productsQuery.isError.value) || (canReadKnowledge && knowledgeQuery.isError.value)" role="alert"><p>部分能力资料暂时无法读取。</p><button type="button" @click="refetchCapabilities">重新加载能力资料</button></div>
        <div v-else-if="capabilities.length" class="tag-list"><span v-for="item in capabilities" :key="item">{{ item }}</span></div>
        <p v-else>还没有已确认的制造或检测能力。</p>
      </section>

      <section class="knowledge-card" role="region" aria-label="行业">
        <div class="card-title"><AppIcon name="globe" /><h2>行业</h2></div>
        <p v-if="!canReadKnowledge">你没有查看行业知识的权限。</p><p v-else-if="knowledgeQuery.isPending.value" role="status">正在读取行业资料…</p><div v-else-if="knowledgeQuery.isError.value" role="alert"><p>行业资料暂时无法读取。</p><button @click="knowledgeQuery.refetch()">重新加载行业资料</button></div><div v-else-if="industries.length" class="tag-list"><span v-for="item in industries" :key="item">{{ item }}</span></div><p v-else>还没有已确认的目标行业。</p>
      </section>

      <section class="knowledge-card" role="region" aria-label="工艺">
        <div class="card-title"><AppIcon name="settings" /><h2>工艺</h2></div>
        <p v-if="!canReadKnowledge">你没有查看工艺知识的权限。</p><p v-else-if="knowledgeQuery.isPending.value" role="status">正在读取工艺资料…</p><div v-else-if="knowledgeQuery.isError.value" role="alert"><p>工艺资料暂时无法读取。</p><button @click="knowledgeQuery.refetch()">重新加载工艺资料</button></div><div v-else-if="processes.length" class="tag-list"><span v-for="item in processes" :key="item">{{ item }}</span></div><p v-else>还没有已确认的加工工艺。</p>
      </section>

      <section class="knowledge-card" role="region" aria-label="标准">
        <div class="card-title"><AppIcon name="check" /><h2>标准</h2></div>
        <p v-if="!canReadKnowledge">你没有查看标准知识的权限。</p><p v-else-if="knowledgeQuery.isPending.value" role="status">正在读取标准资料…</p><div v-else-if="knowledgeQuery.isError.value" role="alert"><p>标准资料暂时无法读取。</p><button @click="knowledgeQuery.refetch()">重新加载标准资料</button></div><div v-else-if="standards.length" class="tag-list"><span v-for="item in standards" :key="item">{{ item }}</span></div><p v-else>还没有已确认的适用标准。</p>
      </section>

      <section class="knowledge-card" role="region" aria-label="证据覆盖">
        <div class="card-title"><AppIcon name="document" /><h2>证据覆盖</h2></div>
        <p v-if="!canReadKnowledge">你没有查看证据资料的权限。</p><p v-else-if="evidenceQuery.isPending.value || knowledgeQuery.isPending.value" role="status">正在读取证据资料…</p><div v-else-if="evidenceQuery.isError.value || knowledgeQuery.isError.value" role="alert"><p>证据资料暂时无法读取。</p><button @click="evidenceQuery.refetch(); knowledgeQuery.refetch()">重新加载证据资料</button></div><template v-else><p v-if="concepts.length">当前可见 {{ concepts.length }} 条知识</p><strong v-else>还没有公司知识</strong><p v-if="evidenceCount">当前可确认 {{ evidenceCount }} 条证据依据。</p><p v-else>还没有可追溯的证据依据。</p></template>
        <RouterLink v-if="canReadKnowledge" class="text-link" to="/knowledge">{{ concepts.length || evidenceCount ? (canCreateKnowledge ? "管理公司知识" : "查看知识库") : (canCreateKnowledge ? "去知识库补充" : "查看知识库") }}</RouterLink>
        <p v-if="canReadKnowledge && !canCreateKnowledge" class="muted">如需补充或编辑，请联系管理员。</p>
      </section>

      <section class="knowledge-card" role="region" aria-label="素材">
        <div class="card-title"><AppIcon name="document" /><h2>素材</h2></div>
        <p v-if="!canReadAssets">你没有查看素材的权限。</p><p v-else-if="assetsQuery.isPending.value" role="status">正在读取素材…</p><div v-else-if="assetsQuery.isError.value" role="alert"><p>素材暂时无法读取。</p><button type="button" @click="assetsQuery.refetch()">重新加载素材</button></div>
        <template v-else><p v-if="assets.length">{{ assetCountLabel(assets.length) }}</p><div v-else><strong>还没有可用素材</strong><p>{{ canManageAssets ? "上传真实图片、视频或文档。" : "如需补充，请联系管理员。" }}</p></div><RouterLink class="text-link" to="/assets">{{ assets.length ? (canManageAssets ? "管理素材" : "查看素材") : (canManageAssets ? "去素材库补充" : "查看素材库") }}</RouterLink><p v-if="assets.length && !canManageAssets" class="muted">如需补充或编辑，请联系管理员。</p></template>
      </section>
    </div>
  </main>
</template>

<style scoped>
.company-profile-page{display:grid;gap:1rem}.company-profile-header h1{margin:.2rem 0}.coverage-card,.gap-panel,.knowledge-card{padding:1.1rem;border:1px solid var(--sg-line,var(--border-color,#d8dee8));border-radius:var(--sg-radius-md,1rem);background:var(--sg-surface,#fff)}.coverage-card,.section-heading,.card-title,.gap-list li{display:flex;align-items:center;justify-content:space-between;gap:1rem}.coverage-card{border-left:4px solid var(--sg-brand,#005ba8)}.coverage-card h2,.section-heading h2,.card-title h2{margin:.2rem 0}.gap-list{display:grid;gap:.75rem;margin:1rem 0 0;padding:0;list-style:none}.gap-list li{padding:.9rem;border-radius:.75rem;background:var(--sg-canvas,#f6f8fb)}.gap-list p{margin:.25rem 0;color:var(--sg-muted,#667085)}.knowledge-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.knowledge-card{min-width:0}.identity-card{grid-column:1/-1}.card-title{justify-content:flex-start}.card-title :deep(.app-icon){width:1.2rem;color:var(--sg-brand,#005ba8)}.tag-list{display:flex;flex-wrap:wrap;gap:.5rem;margin:.75rem 0}.tag-list span{padding:.35rem .65rem;border-radius:999px;background:var(--sg-brand-soft,#eef6ff);color:var(--sg-brand,#005ba8)}.muted{color:var(--sg-muted,#667085)}@media(max-width:760px){.coverage-card,.gap-list li,.section-heading{align-items:stretch;flex-direction:column}.knowledge-grid{grid-template-columns:1fr}.gap-list .primary-action{width:100%;text-align:center}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style>
