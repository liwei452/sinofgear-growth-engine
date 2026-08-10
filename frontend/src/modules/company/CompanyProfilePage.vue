<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { computed } from "vue"
import { RouterLink } from "vue-router"

import { assetKeys, listAssets } from "../assets/api"
import { currentUserQueryOptions } from "../auth/auth"
import { knowledgeQueryKeys, listConcepts } from "../knowledge/api"
import { listProducts, productQueryKeys } from "../products/api"

const currentUserQuery = useQuery(currentUserQueryOptions())
const organizationId = computed(() => currentUserQuery.data.value?.organization.id ?? "")
const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const has = (permission: string): boolean => permissions.value.includes(permission)
const canReadProducts = computed(() => has("products.read"))
const canReadKnowledge = computed(() => has("knowledge.read"))
const canReadAssets = computed(() => has("assets.read"))
const canManageProducts = computed(() => has("products.manage"))
const canCreateKnowledge = computed(() => has("knowledge.create"))
const canManageAssets = computed(() => has("assets.manage"))

const productsQuery = useQuery({
  queryKey: computed(() => productQueryKeys.list(organizationId.value, {})),
  queryFn: () => listProducts(),
  enabled: computed(() => Boolean(organizationId.value) && canReadProducts.value),
  retry: false,
})
const knowledgeQuery = useQuery({
  queryKey: computed(() => knowledgeQueryKeys.concepts(organizationId.value)),
  queryFn: listConcepts,
  enabled: computed(() => Boolean(organizationId.value) && canReadKnowledge.value),
  retry: false,
})
const assetsQuery = useQuery({
  queryKey: computed(() => assetKeys.list(organizationId.value, {})),
  queryFn: () => listAssets(),
  enabled: computed(() => Boolean(organizationId.value) && canReadAssets.value),
  retry: false,
})

function productCountLabel(count: number): string {
  return `当前页有 ${count} 个产品`
}

function assetCountLabel(count: number): string {
  return `当前页有 ${count} 份素材`
}
</script>

<template>
  <div class="page-stack company-profile-page">
    <header class="company-profile-header">
      <div>
        <p class="eyebrow">AI 当前可用的事实基础</p>
        <h1>公司资料</h1>
        <p>这里汇总当前账号能看到的真实资料。补充与编辑仍在原有专业工作区完成。</p>
      </div>
    </header>

    <div class="company-profile-grid">
      <section class="profile-source-card" role="region" aria-labelledby="company-products-title">
        <div class="profile-source-heading">
          <div>
            <p class="profile-source-kicker">产品与交付能力</p>
            <h2 id="company-products-title">产品资料</h2>
          </div>
          <span class="profile-source-icon" aria-hidden="true">产</span>
        </div>
        <p v-if="!canReadProducts" class="cockpit-empty">你没有查看产品资料的权限。</p>
        <p v-else-if="productsQuery.isPending.value" class="cockpit-empty" role="status">正在读取产品资料…</p>
        <div v-else-if="productsQuery.isError.value" class="cockpit-local-error" role="alert">
          <p>产品资料暂时无法读取。</p>
          <button type="button" @click="productsQuery.refetch()">重新加载产品资料</button>
        </div>
        <template v-else>
          <p v-if="productsQuery.data.value?.results.length" class="profile-source-summary">
            {{ productCountLabel(productsQuery.data.value.results.length) }}
          </p>
          <div v-else class="profile-empty-copy">
            <strong>还没有产品资料</strong>
            <p v-if="canManageProducts">先记录真实产品、制造能力与交付范围。</p>
            <p v-else>如需补充，请联系管理员。</p>
          </div>
          <RouterLink class="text-link" to="/products">
            {{ productsQuery.data.value?.results.length
              ? (canManageProducts ? "管理产品资料" : "查看产品资料")
              : (canManageProducts ? "去产品库补充" : "查看产品库") }}
          </RouterLink>
          <p v-if="productsQuery.data.value?.results.length && !canManageProducts" class="muted">如需补充或编辑，请联系管理员。</p>
        </template>
      </section>

      <section class="profile-source-card" role="region" aria-labelledby="company-knowledge-title">
        <div class="profile-source-heading">
          <div>
            <p class="profile-source-kicker">术语与表达边界</p>
            <h2 id="company-knowledge-title">公司知识</h2>
          </div>
          <span class="profile-source-icon" aria-hidden="true">知</span>
        </div>
        <p v-if="!canReadKnowledge" class="cockpit-empty">你没有查看公司知识的权限。</p>
        <p v-else-if="knowledgeQuery.isPending.value" class="cockpit-empty" role="status">正在读取公司知识…</p>
        <div v-else-if="knowledgeQuery.isError.value" class="cockpit-local-error" role="alert">
          <p>公司知识暂时无法读取。</p>
          <button type="button" @click="knowledgeQuery.refetch()">重新加载公司知识</button>
        </div>
        <template v-else>
          <p v-if="knowledgeQuery.data.value?.length" class="profile-source-summary">
            当前可见 {{ knowledgeQuery.data.value.length }} 条知识
          </p>
          <div v-else class="profile-empty-copy">
            <strong>还没有公司知识</strong>
            <p v-if="canCreateKnowledge">补充经过确认的卖点、工艺、标准和市场术语。</p>
            <p v-else>如需补充，请联系管理员。</p>
          </div>
          <RouterLink class="text-link" to="/knowledge">
            {{ knowledgeQuery.data.value?.length
              ? (canCreateKnowledge ? "管理公司知识" : "查看公司知识")
              : (canCreateKnowledge ? "去知识库补充" : "查看知识库") }}
          </RouterLink>
          <p v-if="knowledgeQuery.data.value?.length && !canCreateKnowledge" class="muted">如需补充或编辑，请联系管理员。</p>
        </template>
      </section>

      <section class="profile-source-card" role="region" aria-labelledby="company-assets-title">
        <div class="profile-source-heading">
          <div>
            <p class="profile-source-kicker">图片、视频与文档</p>
            <h2 id="company-assets-title">素材</h2>
          </div>
          <span class="profile-source-icon" aria-hidden="true">素</span>
        </div>
        <p v-if="!canReadAssets" class="cockpit-empty">你没有查看素材的权限。</p>
        <p v-else-if="assetsQuery.isPending.value" class="cockpit-empty" role="status">正在读取素材…</p>
        <div v-else-if="assetsQuery.isError.value" class="cockpit-local-error" role="alert">
          <p>素材暂时无法读取。</p>
          <button type="button" @click="assetsQuery.refetch()">重新加载素材</button>
        </div>
        <template v-else>
          <p v-if="assetsQuery.data.value?.results.length" class="profile-source-summary">
            {{ assetCountLabel(assetsQuery.data.value.results.length) }}
          </p>
          <div v-else class="profile-empty-copy">
            <strong>还没有可用素材</strong>
            <p v-if="canManageAssets">上传真实图片、视频或文档，不在这里重复上传表单。</p>
            <p v-else>如需补充，请联系管理员。</p>
          </div>
          <RouterLink class="text-link" to="/assets">
            {{ assetsQuery.data.value?.results.length
              ? (canManageAssets ? "管理素材" : "查看素材")
              : (canManageAssets ? "去素材库补充" : "查看素材库") }}
          </RouterLink>
          <p v-if="assetsQuery.data.value?.results.length && !canManageAssets" class="muted">如需补充或编辑，请联系管理员。</p>
        </template>
      </section>
    </div>
  </div>
</template>
