<script setup lang="ts">
import { computed, ref } from "vue"
import { useQuery, useQueryClient } from "@tanstack/vue-query"

import { ApiError } from "../../api/client"
import { currentUserQueryOptions } from "../auth/auth"
import { listConcepts, type KnowledgeConcept } from "../knowledge/api"
import ProductFormDialog from "./ProductFormDialog.vue"
import {
  getProductPage,
  listProducts,
  productQueryKeys,
  safeProductPageUrl,
  type Product,
  type ProductConceptRole,
  type ProductFilters,
  type ProductStatus,
} from "./api"

const queryClient = useQueryClient()
const currentUserQuery = useQuery(currentUserQueryOptions())
const status = ref<"" | ProductStatus>("")
const productType = ref("")
const material = ref("")
const application = ref("")
const pageUrl = ref<string | null>(null)
const dialogOpen = ref(false)
const selectedProductId = ref<string>()
const savedMessage = ref("")

const filters = computed<ProductFilters>(() => ({
  ...(status.value ? { status: status.value } : {}),
  ...(productType.value ? { type: productType.value } : {}),
  ...(material.value ? { material: material.value } : {}),
  ...(application.value ? { application: application.value } : {}),
}))

const productsQuery = useQuery({
  queryKey: computed(() => [...productQueryKeys.list(filters.value), pageUrl.value]),
  queryFn: () => pageUrl.value
    ? getProductPage(pageUrl.value)
    : listProducts(filters.value),
})
const conceptsQuery = useQuery({
  queryKey: ["knowledge", "concepts", "product-filters"],
  queryFn: listConcepts,
  enabled: computed(() => productsQuery.isSuccess.value),
})

const canManage = computed(() => currentUserQuery.data.value
  ?.membership.permissions.includes("products.manage") ?? false)
const approvedConcepts = computed(() => (conceptsQuery.data.value ?? [])
  .filter((concept) => concept.status === "APPROVED"))
const conceptsOf = (type: KnowledgeConcept["concept_type"]) => approvedConcepts.value
  .filter((concept) => concept.concept_type === type)

const statusLabels: Record<ProductStatus, string> = {
  DRAFT: "草稿",
  ACTIVE: "已启用",
  ARCHIVED: "已归档",
}

function resetPage(): void {
  pageUrl.value = null
}

function moveTo(candidate: string | null): void {
  const safe = safeProductPageUrl(candidate)
  if (safe) pageUrl.value = safe
}

function openCreate(): void {
  selectedProductId.value = undefined
  savedMessage.value = ""
  dialogOpen.value = true
}

function openProduct(product: Product): void {
  selectedProductId.value = product.id
  savedMessage.value = ""
  dialogOpen.value = true
}

async function productSaved(product: Product): Promise<void> {
  dialogOpen.value = false
  savedMessage.value = `已保存产品“${product.name_zh || product.name_en}”。`
  await queryClient.invalidateQueries({ queryKey: productQueryKeys.lists() })
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.userMessage : "产品暂时无法加载，请稍后重试。"
}

async function retryProducts(): Promise<void> {
  await productsQuery.refetch()
}

function conceptRoleLabel(role: ProductConceptRole): string {
  const labels: Record<ProductConceptRole, string> = {
    TYPE: "类型", MATERIAL: "材料", PROCESS: "工艺", STANDARD: "标准",
    APPLICATION: "应用", PARAMETER: "参数",
  }
  return labels[role]
}
</script>

<template>
  <main class="page-stack product-library" aria-labelledby="products-title">
    <header v-if="!productsQuery.isPending.value" class="library-header">
      <div>
        <p class="eyebrow">可复用的产品事实</p>
        <h1 id="products-title">产品库</h1>
        <p>把规格、交付能力和知识标签整理在一起，供后续内容与投放直接使用。</p>
      </div>
      <button v-if="canManage" class="primary-action" type="button" @click="openCreate">
        新建产品
      </button>
    </header>

    <p v-if="savedMessage" role="status" class="success-message">{{ savedMessage }}</p>

    <section class="filter-panel" aria-label="产品筛选">
      <label>
        产品状态
        <select v-model="status" @change="resetPage">
          <option value="">全部状态</option>
          <option value="DRAFT">草稿</option>
          <option value="ACTIVE">启用产品</option>
          <option value="ARCHIVED">已归档</option>
        </select>
      </label>
      <label>
        产品类型
        <select v-model="productType" @change="resetPage">
          <option value="">全部类型</option>
          <option v-for="concept in conceptsOf('PRODUCT_TYPE')" :key="concept.id" :value="concept.code">
            {{ concept.label_zh || concept.label_en }}
          </option>
        </select>
      </label>
      <label>
        材料标签
        <select v-model="material" @change="resetPage">
          <option value="">全部材料</option>
          <option v-for="concept in conceptsOf('MATERIAL')" :key="concept.id" :value="concept.code">
            {{ concept.label_zh || concept.label_en }}
          </option>
        </select>
      </label>
      <label>
        应用标签
        <select v-model="application" @change="resetPage">
          <option value="">全部应用</option>
          <option v-for="concept in conceptsOf('APPLICATION')" :key="concept.id" :value="concept.code">
            {{ concept.label_zh || concept.label_en }}
          </option>
        </select>
      </label>
    </section>

    <p v-if="productsQuery.isPending.value" role="status">正在加载产品…</p>
    <section v-else-if="productsQuery.isError.value" role="alert" class="state-panel error-state">
      <h2>产品没有加载成功</h2>
      <p>{{ errorMessage(productsQuery.error.value) }}</p>
      <button type="button" @click="retryProducts">重新加载产品</button>
    </section>
    <section v-else-if="!productsQuery.data.value?.results.length" class="state-panel empty-state">
      <h2>还没有符合条件的产品</h2>
      <p>可以清除筛选后再看，或联系有权限的同事新建产品。</p>
      <button
        v-if="status || productType || material || application" type="button"
        @click="status = ''; productType = ''; material = ''; application = ''; resetPage()"
      >
        清除筛选
      </button>
    </section>
    <section v-else aria-label="产品列表">
      <div class="product-list">
        <article v-for="product in productsQuery.data.value?.results" :key="product.id" class="product-card">
          <div class="product-heading">
            <div>
              <h2>{{ product.name_zh || product.name_en }}</h2>
              <p v-if="product.name_zh && product.name_en">{{ product.name_en }}</p>
            </div>
            <span class="status-pill" :data-status="product.status">{{ statusLabels[product.status] }}</span>
          </div>
          <dl class="product-facts">
            <div><dt>规格</dt><dd>模数 {{ product.module_min }}–{{ product.module_max }} · 齿数 {{ product.tooth_count_min }}–{{ product.tooth_count_max }} · 压力角 {{ product.pressure_angle }}°</dd></div>
            <div><dt>交付</dt><dd>{{ product.lead_time || "待补充" }} · MOQ {{ product.moq }}</dd></div>
            <div><dt>质量</dt><dd>{{ product.accuracy_grade || "待补充" }}</dd></div>
          </dl>
          <ul v-if="product.concept_links.length" class="tag-list" aria-label="知识标签">
            <li v-for="link in product.concept_links" :key="link.id">
              <span class="visually-hidden">{{ conceptRoleLabel(link.role) }}：</span>
              {{ link.concept.label_zh || link.concept.label_en }}
            </li>
          </ul>
          <div class="card-actions">
            <button type="button" @click="openProduct(product)">查看</button>
            <button v-if="canManage" type="button" @click="openProduct(product)">编辑</button>
          </div>
        </article>
      </div>
      <nav class="pagination" aria-label="产品分页">
        <button
          type="button" :disabled="!safeProductPageUrl(productsQuery.data.value?.previous ?? null)"
          @click="moveTo(productsQuery.data.value?.previous ?? null)"
        >
          上一页
        </button>
        <button
          type="button" :disabled="!safeProductPageUrl(productsQuery.data.value?.next ?? null)"
          @click="moveTo(productsQuery.data.value?.next ?? null)"
        >
          下一页
        </button>
      </nav>
    </section>

    <ProductFormDialog
      v-if="dialogOpen"
      :product-id="selectedProductId"
      :concepts="approvedConcepts"
      :read-only="!canManage"
      @close="dialogOpen = false"
      @saved="productSaved"
    />
  </main>
</template>

<style scoped>
.library-header,.product-heading,.card-actions,.pagination{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem}.filter-panel{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem}.filter-panel label{display:grid;gap:.4rem}.product-list{display:grid;gap:1rem}.product-card,.state-panel,.filter-panel{padding:1.25rem;border:1px solid var(--border-color,#d8dee8);border-radius:1rem;background:var(--surface,#fff)}.product-heading h2{margin:0}.product-heading p{margin:.25rem 0 0}.product-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}.product-facts div{display:grid;gap:.3rem}.product-facts dt{font-weight:700}.product-facts dd{margin:0}.tag-list{display:flex;gap:.5rem;flex-wrap:wrap;padding:0;list-style:none}.tag-list li,.status-pill{padding:.25rem .6rem;border-radius:999px;background:#eef3f8}.card-actions{justify-content:flex-end}.pagination{justify-content:flex-end;margin-top:1rem}.success-message{padding:.75rem 1rem;border-radius:.75rem;background:#e9f8ef}.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(max-width:760px){.library-header{align-items:stretch;flex-direction:column}.filter-panel,.product-facts{grid-template-columns:1fr}.primary-action{width:100%}}
</style>
