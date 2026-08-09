<script setup lang="ts">
import { computed, ref } from "vue"
import { useQuery, useQueryClient } from "@tanstack/vue-query"

import { ApiError } from "../../api/client"
import { currentUserQueryOptions } from "../auth/auth"
import AliasResolver from "./AliasResolver.vue"
import KnowledgeConceptDialog from "./KnowledgeConceptDialog.vue"
import {
  knowledgeQueryKeys,
  listAliases,
  listConcepts,
  listEvidence,
  listRelations,
  reviewConcept,
  type ConceptType,
  type KnowledgeConcept,
  type KnowledgeScope,
  type KnowledgeStatus,
  type ReviewAction,
} from "./api"

const queryClient = useQueryClient()
const currentUserQuery = useQuery(currentUserQueryOptions())
const conceptsQuery = useQuery({ queryKey: knowledgeQueryKeys.concepts(), queryFn: listConcepts })
const aliasesQuery = useQuery({ queryKey: knowledgeQueryKeys.aliases(), queryFn: listAliases })
const relationsQuery = useQuery({ queryKey: knowledgeQueryKeys.relations(), queryFn: listRelations })
const evidenceQuery = useQuery({ queryKey: knowledgeQueryKeys.evidence(), queryFn: listEvidence })

const search = ref("")
const status = ref<"" | KnowledgeStatus>("")
const conceptType = ref<"" | ConceptType>("")
const scope = ref<"" | KnowledgeScope>("")
const dialogOpen = ref(false)
const notice = ref("")
const actionError = ref("")
const actionId = ref("")
const rejectingId = ref("")
const rejectionReason = ref("")

const permissions = computed(() => currentUserQuery.data.value?.membership.permissions ?? [])
const has = (permission: string) => permissions.value.includes(permission)
const canCreate = computed(() => has("knowledge.create"))
const filtered = computed(() => {
  const term = search.value.trim().toLocaleLowerCase()
  return (conceptsQuery.data.value ?? []).filter((concept) => {
    const matchesText = !term || [concept.label_zh, concept.label_en, concept.code]
      .some((value) => value.toLocaleLowerCase().includes(term))
    return matchesText && (!status.value || concept.status === status.value)
      && (!conceptType.value || concept.concept_type === conceptType.value)
      && (!scope.value || concept.scope === scope.value)
  })
})
const isPending = computed(() => [conceptsQuery, aliasesQuery, relationsQuery, evidenceQuery]
  .some((query) => query.isPending.value))
const firstError = computed(() => [conceptsQuery, aliasesQuery, relationsQuery, evidenceQuery]
  .find((query) => query.isError.value)?.error.value)

const statusLabels: Record<KnowledgeStatus, string> = {
  SUGGESTED: "待审核", APPROVED: "已通过", REJECTED: "已驳回", DEPRECATED: "已停用",
}
const typeLabels: Record<ConceptType, string> = {
  PRODUCT_TYPE: "产品类型", PARAMETER: "参数", MATERIAL: "材料", PROCESS: "工艺", STANDARD: "标准",
  APPLICATION: "应用", INDUSTRY: "行业", CUSTOMER_TYPE: "客户类型", PURCHASE_INTENT: "采购意图",
}

function canReview(concept: KnowledgeConcept): boolean {
  return concept.scope === "SYSTEM"
    ? has("knowledge.manage_system")
    : has("knowledge.review_organization") || has("knowledge.manage_system")
}

function canDeprecate(concept: KnowledgeConcept): boolean {
  return has("knowledge.deprecate") && (concept.scope === "ORGANIZATION" || has("knowledge.manage_system"))
}

async function runAction(concept: KnowledgeConcept, action: ReviewAction, comment = ""): Promise<void> {
  if (action === "reject" && !comment.trim()) {
    actionError.value = "请填写驳回原因。"
    return
  }
  actionId.value = concept.id
  actionError.value = ""
  notice.value = ""
  try {
    const updated = await reviewConcept(concept.id, action, comment.trim())
    queryClient.setQueryData<KnowledgeConcept[]>(knowledgeQueryKeys.concepts(), (items = []) =>
      items.map((item) => item.id === updated.id ? updated : item))
    const verb = action === "approve" ? "已通过" : action === "reject" ? "已驳回"
      : action === "deprecate" ? "已停用" : "已提交审核"
    notice.value = `${verb}“${updated.label_zh || updated.label_en}”`
    rejectingId.value = ""
    rejectionReason.value = ""
  } catch (error) {
    actionError.value = error instanceof ApiError ? error.userMessage : "审核操作没有完成，请稍后重试。"
  } finally { actionId.value = "" }
}

async function created(concept: KnowledgeConcept): Promise<void> {
  dialogOpen.value = false
  notice.value = `已提交“${concept.label_zh || concept.label_en}”，等待审核。`
  await queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.concepts() })
}

async function retryAll(): Promise<void> {
  await Promise.all([conceptsQuery.refetch(), aliasesQuery.refetch(), relationsQuery.refetch(), evidenceQuery.refetch()])
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.userMessage : "知识库暂时无法加载，请稍后重试。"
}
</script>

<template>
  <main class="page-stack knowledge-library" aria-labelledby="knowledge-title">
    <header class="library-header">
      <div><p class="eyebrow">统一团队语言</p><h1 id="knowledge-title">知识库</h1><p>统一产品、材料和应用的叫法，让内容、搜索和客户沟通引用同一套已审核知识。</p></div>
      <button v-if="canCreate" class="primary-action" type="button" @click="dialogOpen = true">新增知识建议</button>
    </header>

    <section class="count-grid" aria-label="知识库数据概览">
      <p><strong>{{ aliasesQuery.data.value?.length ?? 0 }} 个名称</strong></p>
      <p><strong>{{ relationsQuery.data.value?.length ?? 0 }} 条关系</strong></p>
      <p><strong>{{ evidenceQuery.data.value?.length ?? 0 }} 条证据资料</strong></p>
    </section>
    <AliasResolver />
    <p v-if="notice" role="status" class="success-message">{{ notice }}</p>
    <p v-if="actionError" role="alert" class="error-message">{{ actionError }}</p>

    <section class="filter-panel" aria-label="知识筛选">
      <label>搜索知识<input v-model="search" type="search" placeholder="中文、English 或编码"></label>
      <label>状态<select v-model="status"><option value="">全部状态</option><option value="SUGGESTED">待审核知识</option><option value="APPROVED">通过</option><option value="REJECTED">驳回</option><option value="DEPRECATED">停用</option></select></label>
      <label>类型<select v-model="conceptType"><option value="">全部类型</option><option v-for="(label,value) in typeLabels" :key="value" :value="value">{{ label }}</option></select></label>
      <label>范围<select v-model="scope"><option value="">全部范围</option><option value="SYSTEM">系统</option><option value="ORGANIZATION">本组织</option></select></label>
    </section>

    <p v-if="isPending" role="status">正在加载知识库…</p>
    <section v-else-if="firstError" role="alert" class="state-panel">
      <h2>知识库没有加载成功</h2><p>{{ errorMessage(firstError) }}</p><button type="button" @click="retryAll">重新加载知识库</button>
    </section>
    <section v-else-if="!filtered.length" class="state-panel"><h2>没有找到符合条件的知识</h2><p>可以调整搜索词或筛选条件后再试。</p></section>
    <section v-else class="concept-list" aria-label="知识概念">
      <article v-for="concept in filtered" :key="concept.id" class="concept-card">
        <header><div><h2>{{ concept.label_zh || concept.label_en }}</h2><p v-if="concept.label_zh && concept.label_en">{{ concept.label_en }}</p></div><span class="status-pill">{{ statusLabels[concept.status] }}</span></header>
        <p class="concept-code">{{ concept.code }}</p><p>{{ concept.description || "暂无说明" }}</p>
        <dl><div><dt>类型</dt><dd>{{ typeLabels[concept.concept_type] }}</dd></div><div><dt>范围</dt><dd>{{ concept.scope === "SYSTEM" ? "系统" : "本组织" }}</dd></div><div><dt>依据</dt><dd>{{ concept.evidence.length }} 条证据</dd></div></dl>
        <div class="review-actions">
          <button v-if="concept.status === 'SUGGESTED' && canCreate" type="button" :disabled="actionId === concept.id" @click="runAction(concept,'submit-review')">提交审核</button>
          <template v-if="concept.status === 'SUGGESTED' && canReview(concept)">
            <button type="button" :disabled="actionId === concept.id" @click="runAction(concept,'approve')">通过</button>
            <button type="button" :disabled="actionId === concept.id" @click="rejectingId = concept.id; actionError = ''">驳回</button>
          </template>
          <button v-if="concept.status === 'APPROVED' && canDeprecate(concept)" type="button" :disabled="actionId === concept.id" @click="runAction(concept,'deprecate')">停用</button>
        </div>
        <form v-if="rejectingId === concept.id" class="reject-form" @submit.prevent="runAction(concept,'reject',rejectionReason)">
          <label>驳回原因（必填）<textarea v-model="rejectionReason" rows="2" /></label><button type="submit">确认驳回</button><button type="button" @click="rejectingId = ''">取消</button>
        </form>
      </article>
    </section>
    <KnowledgeConceptDialog v-if="dialogOpen" @close="dialogOpen = false" @saved="created" />
  </main>
</template>

<style scoped>
.library-header,.concept-card header,.review-actions{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem}.count-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}.count-grid p,.concept-card,.filter-panel,.state-panel{padding:1rem;border:1px solid var(--border-color,#d8dee8);border-radius:1rem;background:#fff}.count-grid p{margin:0}.filter-panel{display:grid;grid-template-columns:2fr repeat(3,1fr);gap:1rem}.filter-panel label,.reject-form label{display:grid;gap:.4rem}.concept-list{display:grid;gap:1rem}.concept-card h2{margin:0}.concept-card header p{margin:.25rem 0 0}.concept-code{display:inline-block;padding:.2rem .45rem;border-radius:.35rem;background:#eef3f8;font-family:monospace}.concept-card dl{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}.concept-card dl div{display:grid;gap:.2rem}.concept-card dd{margin:0}.review-actions{justify-content:flex-end}.reject-form{display:grid;grid-template-columns:1fr auto auto;align-items:end;gap:.75rem;margin-top:1rem}.success-message{padding:.75rem 1rem;border-radius:.75rem;background:#e9f8ef}.error-message{padding:.75rem 1rem;border-radius:.75rem;background:#fff0ed;color:#79291d}.status-pill{padding:.25rem .6rem;border-radius:999px;background:#eef3f8}@media(max-width:760px){.library-header{flex-direction:column}.count-grid,.filter-panel,.concept-card dl,.reject-form{grid-template-columns:1fr}.primary-action{width:100%}}
</style>
