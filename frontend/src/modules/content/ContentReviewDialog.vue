<script setup lang="ts">
import { computed, nextTick, reactive, ref } from "vue"

import { ApiError } from "../../api/client"
import { useModalFocus } from "../../shared/composables/useModalFocus"
import { prepareChannelPackage } from "../growth/api"
import {
  contentAction, generatePlatformContent, getAIRun, getBrief, reviseMasterContent,
  revisePlatformContent, type AIRun, type MasterContent, type Platform,
  type PlatformContent,
} from "./api"

type ReviewItem = MasterContent | PlatformContent
const props = defineProps<{
  item: ReviewItem
  kind: "master" | "platform"
  permissions: string[]
  currentHead: boolean
  platforms: Platform[]
}>()
const emit = defineEmits<{ close: []; updated: [item: ReviewItem]; platformGenerated: []; conflict: [] }>()

const backdrop = ref<HTMLElement | null>(null)
const dialog = ref<HTMLElement | null>(null)
const title = ref<HTMLElement | null>(null)
const alert = ref("")
const notice = ref("")
const busy = ref(false)
const editing = ref(false)
const rejecting = ref(false)
const rejectionReason = ref("")
const audit = ref<AIRun | null>(null)
const auditOpen = ref(false)
const platformPicker = ref(false)
const packagePrepared = ref(props.kind === "platform"
  && Boolean((props.item as PlatformContent).publish_package_id))
const selectedBriefPlatformIds = ref<string[]>([])
const form = reactive({
  title: props.item.payload.title,
  body: props.item.payload.body,
  cta: props.item.payload.cta,
  concept_codes: props.item.payload.concept_codes.join(", "),
  platform_code: "platform_code" in props.item.payload ? props.item.payload.platform_code : "",
})

useModalFocus({ backdrop, dialog, initialFocus: title, close: () => emit("close") })
const has = (permission: string) => props.permissions.includes(permission)
const canRevise = computed(() => has("content.manage") && props.currentHead && props.item.status !== "ARCHIVED")
const canSubmit = computed(() => has("content.manage") && props.currentHead && props.item.status === "DRAFT")
const canReview = computed(() => has("content.review") && props.currentHead && props.item.status === "IN_REVIEW")
const canArchive = computed(() => has("content.review") && props.currentHead && props.item.status !== "ARCHIVED")
const canGeneratePlatform = computed(() => props.kind === "master" && has("content.manage")
  && props.currentHead && props.item.status === "APPROVED")
const canPreparePublishing = computed(() => props.kind === "platform" && has("publishing.manage")
  && props.currentHead && props.item.status === "APPROVED"
  && new Set(["LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"])
    .has((props.item as PlatformContent).payload.platform_code))
const selectedPlatforms = computed(() => props.platforms.filter((platform) =>
  selectedBriefPlatformIds.value.includes(platform.id)))
const auditOntologyCodes = computed(() => {
  const ontology = audit.value?.input_snapshot.ontology_snapshot
  if (!ontology || typeof ontology !== "object" || Array.isArray(ontology)) return []
  const versions = (ontology as Record<string, unknown>).concept_versions
  if (!Array.isArray(versions)) return []
  return versions.flatMap((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return []
    const code = (entry as Record<string, unknown>).code
    return typeof code === "string" && /^[A-Z0-9_]{1,64}$/.test(code) ? [code] : []
  })
})
type AuditVerifiedFact = {
  id: string
  fieldName: string
  value: string
  sourceFilename: string
  sourcePage: number | null
  sourceExcerpt: string
  isDemo: boolean
}
const safeAuditText = (value: unknown, maxLength: number): string =>
  typeof value === "string" ? value.trim().slice(0, maxLength) : ""
const auditVerifiedFacts = computed<AuditVerifiedFact[]>(() => {
  const facts = audit.value?.input_snapshot.verified_product_facts
  if (!Array.isArray(facts)) return []
  return facts.slice(0, 50).flatMap((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return []
    const fact = entry as Record<string, unknown>
    const id = safeAuditText(fact.fact_id, 36)
    const fieldName = safeAuditText(fact.field_name, 100)
    const value = safeAuditText(fact.value, 500)
    const sourceFilename = safeAuditText(fact.source_filename, 255)
    const sourceExcerpt = safeAuditText(fact.source_excerpt, 500)
    const sourcePage = typeof fact.source_page === "number" && Number.isSafeInteger(fact.source_page)
      && fact.source_page > 0 ? fact.source_page : null
    if (!/^[0-9a-f-]{36}$/i.test(id) || !fieldName || !value || !sourceFilename || !sourceExcerpt) return []
    return [{ id, fieldName, value, sourceFilename, sourcePage, sourceExcerpt, isDemo: fact.is_demo === true }]
  })
})

function codes(): string[] {
  return [...new Set(form.concept_codes.split(/[,，\n]/).map((value) => value.trim()).filter(Boolean))]
}

function safeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) return "内容状态已经变化，请刷新后再试。"
  return error instanceof ApiError ? error.userMessage : "操作没有完成，请稍后重试。"
}

async function saveRevision(): Promise<void> {
  if (!canRevise.value || busy.value) return
  alert.value = ""
  if (!form.title.trim() || !form.body.trim() || !form.cta.trim()) {
    alert.value = "请填写标题、正文和行动号召。"
    await nextTick()
    dialog.value?.querySelector<HTMLInputElement>("[data-review-field]:invalid, [data-review-field]")?.focus()
    return
  }
  const base = { title: form.title.trim(), body: form.body.trim(), cta: form.cta.trim(), concept_codes: codes() }
  const comparable = props.kind === "master" ? base : { ...base, platform_code: form.platform_code }
  if (JSON.stringify(comparable) === JSON.stringify(props.item.payload)) {
    alert.value = "请先修改至少一项内容。"
    return
  }
  busy.value = true
  try {
    const updated = props.kind === "master"
      ? await reviseMasterContent(props.item.id, base)
      : await revisePlatformContent(props.item.id, { ...base, platform_code: form.platform_code })
    notice.value = `已创建第 ${updated.version} 版。`
    editing.value = false
    emit("updated", updated)
  } catch (error) {
    alert.value = safeError(error)
    if (error instanceof ApiError && error.status === 409) emit("conflict")
  } finally { busy.value = false }
}

async function act(action: "submit-review" | "approve" | "reject" | "archive"): Promise<void> {
  const legal = action === "submit-review" ? canSubmit.value
    : action === "archive" ? canArchive.value : canReview.value
  if (!legal || busy.value) return
  if (action === "reject" && !rejectionReason.value.trim()) {
    alert.value = "请填写驳回原因。"
    return
  }
  busy.value = true
  alert.value = ""
  try {
    const updated = await contentAction<ReviewItem>(
      props.kind, props.item.id, action, action === "reject" ? rejectionReason.value.trim() : "",
    )
    emit("updated", updated)
    rejecting.value = false
    notice.value = action === "approve" ? "内容已通过。" : action === "reject" ? "内容已驳回。" : action === "archive" ? "内容已归档。" : "内容已提交审核。"
  } catch (error) {
    alert.value = safeError(error)
    if (error instanceof ApiError && error.status === 409) emit("conflict")
  } finally { busy.value = false }
}

async function loadAudit(): Promise<void> {
  if (props.kind !== "master") return
  auditOpen.value = true
  if (audit.value) return
  try { audit.value = await getAIRun((props.item as MasterContent).ai_run_id) }
  catch (error) { alert.value = safeError(error) }
}

function safeFieldNames(value: Record<string, unknown> | null): string {
  if (!value) return "无"
  return Object.keys(value).filter((key) => !/(authorization|token|password|api.?key|secret|cookie|credential)/i.test(key)).join("、") || "无可展示字段"
}

async function choosePlatform(): Promise<void> {
  if (!canGeneratePlatform.value) return
  try {
    selectedBriefPlatformIds.value = (await getBrief((props.item as MasterContent).brief_id)).platform_ids
    platformPicker.value = true
  } catch (error) { alert.value = safeError(error) }
}

async function generate(platform: Platform): Promise<void> {
  if (!canGeneratePlatform.value || !selectedBriefPlatformIds.value.includes(platform.id)) return
  busy.value = true
  try {
    await generatePlatformContent(props.item.id, platform.id)
    notice.value = `已为 ${platform.name} 准备平台版本。`
    emit("platformGenerated")
  } catch (error) {
    alert.value = safeError(error)
    if (error instanceof ApiError && error.status === 409) emit("conflict")
  } finally { busy.value = false }
}

async function preparePublishing(): Promise<void> {
  if (!canPreparePublishing.value || busy.value || packagePrepared.value) return
  busy.value = true
  alert.value = ""
  try {
    await prepareChannelPackage(props.item.id)
    packagePrepared.value = true
    notice.value = "已加入推广页的一键发布准备，仍需逐渠道审核。"
  } catch (error) {
    alert.value = safeError(error)
  } finally { busy.value = false }
}
</script>

<template>
  <Teleport to="body">
    <div ref="backdrop" class="dialog-backdrop" @click.self="emit('close')">
      <section ref="dialog" class="review-dialog" role="dialog" aria-modal="true" aria-labelledby="review-title">
        <header><div><p class="eyebrow">第 {{ item.version }} 版 · {{ item.status }}</p><h2 id="review-title" ref="title" tabindex="-1">{{ item.payload.title }}</h2></div><button type="button" aria-label="关闭" @click="emit('close')">×</button></header>
        <p v-if="notice" role="status" class="notice">{{ notice }}</p><p v-if="alert" role="alert" class="form-alert">{{ alert }}</p>

        <form v-if="editing" class="edit-form" @submit.prevent="saveRevision">
          <label>标题（必填）<input v-model="form.title" aria-label="标题（必填）" data-review-field required></label>
          <label>正文（必填）<textarea v-model="form.body" aria-label="正文（必填）" data-review-field required rows="8" /></label>
          <label>行动号召（必填）<input v-model="form.cta" aria-label="行动号召（必填）" data-review-field required></label>
          <label>知识代码（逗号分隔）<input v-model="form.concept_codes" aria-label="知识代码（逗号分隔）"></label>
          <label v-if="kind === 'platform'">平台代码<input v-model="form.platform_code" disabled></label>
          <div class="dialog-actions"><button type="button" @click="editing = false">取消修改</button><button class="primary-action" type="submit" :disabled="busy">保存修改版</button></div>
        </form>
        <template v-else>
          <section class="content-fields" aria-label="内容详情"><div><h3>正文</h3><p class="body-copy">{{ item.payload.body }}</p></div><div><h3>行动号召</h3><p>{{ item.payload.cta }}</p></div><div><h3>知识代码</h3><div class="chips"><span v-for="code in item.payload.concept_codes" :key="code">{{ code }}</span></div></div><div v-if="'platform_code' in item.payload"><h3>平台代码</h3><p>{{ item.payload.platform_code }}</p></div></section>
          <details><summary>来源可追溯</summary><p>来源需求 {{ kind === 'master' ? (item as MasterContent).brief_id : '由主内容生成' }}，任务与版本信息已保留供审计。</p></details>
          <section v-if="kind === 'master'" class="audit-panel"><button type="button" @click="loadAudit">查看AI生成记录</button><div v-if="auditOpen && audit"><p>状态 <strong>{{ audit.status }}</strong></p><p><strong>{{ audit.model }}</strong> · {{ audit.provider }}</p><p>{{ audit.prompt.code }} · v{{ audit.prompt.version }}</p><p>置信度 {{ audit.confidence ?? '未提供' }} · {{ audit.started_at }} 至 {{ audit.finished_at || '进行中' }}</p><p>人工修订：{{ audit.human_correction ? '有' : '无' }}</p><p v-if="auditOntologyCodes.length">已锁定知识：<span v-for="code in auditOntologyCodes" :key="code" class="audit-code">{{ code }}</span></p><section v-if="auditVerifiedFacts.length" class="fact-evidence" aria-label="本次使用的已验证事实"><h3>本次使用的已验证事实</h3><article v-for="fact in auditVerifiedFacts" :key="fact.id"><strong>{{ fact.fieldName }}：{{ fact.value }}</strong><p>{{ fact.sourceFilename }}<template v-if="fact.sourcePage"> · 第 {{ fact.sourcePage }} 页</template><template v-if="fact.isDemo"> · Demo/Fake</template></p><blockquote>{{ fact.sourceExcerpt }}</blockquote></article></section><p v-else class="muted">本次生成未使用已验证的资料事实。</p><details><summary>安全字段摘要</summary><p>输入字段：{{ safeFieldNames(audit.input_snapshot) }}</p><p>输出字段：{{ safeFieldNames(audit.output_json) }}</p></details></div></section>

          <form v-if="rejecting" class="reject-form" @submit.prevent="act('reject')"><label>驳回原因（必填）<textarea v-model="rejectionReason" aria-label="驳回原因（必填）" rows="3" /></label><div class="dialog-actions"><button type="button" @click="rejecting = false">取消</button><button type="submit">确认驳回</button></div></form>
          <section v-if="platformPicker" class="platform-picker"><h3>为已选平台生成版本</h3><p v-if="!selectedPlatforms.length">源需求没有可用平台。</p><button v-for="platform in selectedPlatforms" :key="platform.id" type="button" :disabled="busy" @click="generate(platform)">为 {{ platform.name }} 生成</button></section>
          <footer class="dialog-actions"><button v-if="canRevise" type="button" @click="editing = true">创建修改版</button><button v-if="canSubmit" type="button" @click="act('submit-review')">提交审核</button><button v-if="canReview" class="primary-action" type="button" @click="act('approve')">通过</button><button v-if="canReview" type="button" @click="rejecting = true; alert = ''">驳回</button><button v-if="canArchive" type="button" @click="act('archive')">归档</button><button v-if="canGeneratePlatform" type="button" @click="choosePlatform">生成平台版本</button><button v-if="canPreparePublishing" class="primary-action" type="button" :disabled="busy || packagePrepared" @click="preparePublishing">{{ packagePrepared ? '已加入发布准备' : '加入一键发布' }}</button><a v-if="packagePrepared" href="/promotion">前往推广页</a></footer>
        </template>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop{position:fixed;inset:0;z-index:40;display:grid;place-items:center;padding:1rem;background:rgba(20,31,45,.55)}.review-dialog{width:min(860px,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.5rem;border-radius:1rem;background:#fff}.review-dialog header,.dialog-actions{display:flex;justify-content:space-between;gap:1rem}.content-fields,.edit-form,.reject-form,.audit-panel,.platform-picker{display:grid;gap:1rem}.body-copy{white-space:pre-wrap}.chips{display:flex;flex-wrap:wrap;gap:.5rem}.chips span{padding:.25rem .55rem;border-radius:999px;background:#edf4f1}.fact-evidence{display:grid;gap:.65rem;padding:1rem;border:1px solid #dce8f4;border-radius:.8rem;background:#f8fbff}.fact-evidence h3,.fact-evidence p{margin:0}.fact-evidence article{display:grid;gap:.35rem}.fact-evidence blockquote{margin:0;padding:.55rem .75rem;border-left:3px solid #8eb8e0;background:#fff;color:#41556a}.muted{color:#66788a}.dialog-actions{justify-content:flex-end;flex-wrap:wrap;margin-top:1rem}.notice,.form-alert{padding:.75rem;border-radius:.7rem}.notice{background:#edf8f2}.form-alert{background:#fff0ed;color:#79291d}.edit-form label,.reject-form label{display:grid;gap:.4rem}
</style>
