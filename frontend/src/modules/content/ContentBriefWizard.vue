<script setup lang="ts">
import { nextTick, reactive, ref } from "vue"

import { ApiError } from "../../api/client"
import { useModalFocus } from "../../shared/composables/useModalFocus"
import type { Product } from "../products/api"
import {
  createBrief, createCampaign, patchBrief, type Asset, type Campaign, type ContentBrief, type Platform,
} from "./api"

const props = defineProps<{
  campaigns: Campaign[]
  products: Product[]
  platforms: Platform[]
  assets: Asset[]
  brief?: ContentBrief | null
  more: Record<"campaigns" | "products" | "platforms" | "assets", boolean>
  pageErrors: Record<"campaigns" | "products" | "platforms" | "assets", string>
}>()
const emit = defineEmits<{
  close: []
  saved: [brief: ContentBrief]
  loadMore: [kind: "campaigns" | "products" | "platforms" | "assets"]
}>()

const step = ref(1)
const busy = ref(false)
const alert = ref("")
const fieldErrors = reactive<Record<string, string>>({})
const quickCampaign = ref(false)
const campaignId = ref(props.brief?.campaign_id ?? props.campaigns[0]?.id ?? "")
const newCampaign = reactive({ name: "", description: "" })
const productIds = ref<string[]>([...(props.brief?.product_ids ?? [])])
const platformIds = ref<string[]>([...(props.brief?.platform_ids ?? [])])
const assetIds = ref<string[]>([...(props.brief?.asset_ids ?? [])])
const form = reactive({
  target_country: props.brief?.target_country ?? "",
  customer_type: props.brief?.customer_type ?? "",
  content_objective: props.brief?.content_objective ?? "",
  cta: props.brief?.cta ?? "",
  landing_page_url: props.brief?.landing_page_url ?? "",
  language: props.brief?.language ?? "",
  selling_points: props.brief?.selling_points.join(", ") ?? "",
  advantages: props.brief?.advantages.join(", ") ?? "",
  keywords: props.brief?.keywords.join(", ") ?? "",
  prohibited_claims: props.brief?.prohibited_claims.join(", ") ?? "",
})
const backdrop = ref<HTMLElement | null>(null)
const dialog = ref<HTMLElement | null>(null)
const title = ref<HTMLElement | null>(null)
const alertElement = ref<HTMLElement | null>(null)

const fieldAliases: Record<string, string> = {
  campaign_id: "campaign", campaigns: "campaign",
  product_ids: "products", products: "products",
  platform_ids: "platforms", target_platforms: "platforms", platforms: "platforms",
  asset_ids: "assets", assets: "assets",
}
const fieldSteps: Record<string, number> = {
  campaign: 1, campaign_name: 1,
  products: 2, platforms: 2, assets: 2,
  target_country: 3, customer_type: 3, content_objective: 3, cta: 3,
  landing_page_url: 3, language: 3, selling_points: 3, advantages: 3,
  keywords: 3, prohibited_claims: 3,
}

useModalFocus({ backdrop, dialog, initialFocus: title, close: () => emit("close") })

function clearErrors(): void {
  alert.value = ""
  for (const key of Object.keys(fieldErrors)) delete fieldErrors[key]
}

async function focusFirstError(preferred?: string): Promise<void> {
  await nextTick()
  const name = preferred ?? Object.keys(fieldErrors)[0]
  const field = name
    ? dialog.value?.querySelector<HTMLElement>(`[data-field="${name}"]`)
    : undefined
  const target = field?.matches("input, select, textarea, button")
    ? field
    : field?.querySelector<HTMLElement>("input, select, textarea, button")
  if (target) target.focus()
  else alertElement.value?.focus()
}

async function applyServerFieldErrors(error: ApiError): Promise<boolean> {
  if (!error.fieldErrors || !Object.keys(error.fieldErrors).length) return false
  clearErrors()
  const summaryMessages: string[] = []
  const knownFields: string[] = []
  for (const [rawField, messages] of Object.entries(error.fieldErrors)) {
    const field = fieldAliases[rawField] ?? rawField
    const message = messages.join(" ")
    if (fieldSteps[field]) {
      fieldErrors[field] = fieldErrors[field] ? `${fieldErrors[field]} ${message}` : message
      if (!knownFields.includes(field)) knownFields.push(field)
    } else {
      summaryMessages.push(message)
    }
  }
  if (knownFields.length) {
    const targetStep = Math.min(...knownFields.map((field) => fieldSteps[field]))
    step.value = targetStep
    const targetField = knownFields.find((field) => fieldSteps[field] === targetStep)
    alert.value = summaryMessages.length
      ? `请检查以下问题：${summaryMessages.join(" ")}`
      : "请检查标出的字段后重试。"
    await focusFirstError(targetField)
  } else {
    alert.value = summaryMessages.join(" ") || error.userMessage
    await focusFirstError()
  }
  return true
}

function list(value: string): string[] {
  const found = new Map<string, string>()
  for (const item of value.split(/[,，\n]/).map((part) => part.trim()).filter(Boolean)) {
    const key = item.normalize("NFKC").toLocaleLowerCase()
    if (!found.has(key)) found.set(key, item)
  }
  return [...found.values()]
}

async function next(): Promise<void> {
  clearErrors()
  if (step.value === 1) {
    if (props.brief) {
      campaignId.value = props.brief.campaign_id
    } else if (quickCampaign.value) {
      if (!newCampaign.name.trim()) {
        fieldErrors.campaign_name = "请填写活动名称。"
        alert.value = "请先完成活动信息。"
        await focusFirstError()
        return
      }
      busy.value = true
      try {
        campaignId.value = (await createCampaign({
          name: newCampaign.name.trim(), description: newCampaign.description.trim(),
        })).id
      } catch (error) {
        alert.value = error instanceof ApiError ? error.userMessage : "活动没有创建成功，请重试。"
        return
      } finally { busy.value = false }
    } else if (!campaignId.value) {
      fieldErrors.campaign = "请选择一个活动，或快速新建活动。"
      alert.value = "请先选择活动。"
      await focusFirstError()
      return
    }
  }
  if (step.value === 2 && (!productIds.value.length || !platformIds.value.length)) {
    alert.value = "请至少选择一个产品和一个平台。"
    if (!productIds.value.length) fieldErrors.products = "请选择产品。"
    else fieldErrors.platforms = "请选择平台。"
    await focusFirstError()
    return
  }
  if (step.value === 3) {
    for (const key of ["target_country", "customer_type", "content_objective", "cta", "landing_page_url", "language"] as const) {
      if (!form[key].trim()) fieldErrors[key] = "此项为必填。"
    }
    if (form.landing_page_url) {
      try {
        const url = new URL(form.landing_page_url)
        if (!(["http:", "https:"] as string[]).includes(url.protocol)) throw new Error()
      } catch { fieldErrors.landing_page_url = "请输入 http 或 https 开头的网址。" }
    }
    if (!list(form.selling_points).length) fieldErrors.selling_points = "请至少填写一个卖点。"
    if (!list(form.advantages).length) fieldErrors.advantages = "请至少填写一个优势。"
    if (!list(form.keywords).length) fieldErrors.keywords = "请至少填写一个关键词。"
    if (Object.keys(fieldErrors).length) {
      alert.value = "请检查需求信息中的必填项。"
      await focusFirstError()
      return
    }
  }
  step.value += 1
}

async function submit(): Promise<void> {
  busy.value = true
  clearErrors()
  try {
    const input = {
      target_country: form.target_country.trim(), customer_type: form.customer_type.trim(),
      content_objective: form.content_objective.trim(), cta: form.cta.trim(),
      landing_page_url: form.landing_page_url.trim(), language: form.language.trim().toLowerCase(),
      prohibited_claims: list(form.prohibited_claims), selling_points: list(form.selling_points),
      advantages: list(form.advantages), keywords: list(form.keywords),
      product_ids: productIds.value, asset_ids: assetIds.value, platform_ids: platformIds.value,
      concept_links: props.brief?.concept_links ?? [],
    }
    const brief = props.brief
      ? await patchBrief(props.brief.id, input)
      : await createBrief({ campaign_id: campaignId.value, ...input })
    emit("saved", brief)
  } catch (error) {
    if (!(error instanceof ApiError) || !(await applyServerFieldErrors(error))) {
      alert.value = error instanceof ApiError ? error.userMessage : "需求草稿没有创建成功，请重试。"
    }
  } finally { busy.value = false }
}
</script>

<template>
  <Teleport to="body">
    <div ref="backdrop" class="dialog-backdrop" @click.self="emit('close')">
      <section ref="dialog" class="wizard-dialog" role="dialog" aria-modal="true" aria-labelledby="wizard-title">
        <header>
          <div><p class="eyebrow">第 {{ step }} 步，共 4 步</p><h2 id="wizard-title" ref="title" tabindex="-1">{{ brief ? '编辑需求草稿' : '创建内容任务' }}</h2></div>
          <button type="button" aria-label="关闭" @click="emit('close')">×</button>
        </header>
        <p v-if="alert" ref="alertElement" role="alert" class="form-alert" tabindex="-1">{{ alert }}</p>

        <section v-if="step === 1" aria-labelledby="campaign-step">
          <h3 id="campaign-step">准备活动</h3>
          <p v-if="brief">活动保持不变：{{ campaigns.find(item => item.id === campaignId)?.name || campaignId }}</p>
          <label v-else><input v-model="quickCampaign" type="checkbox" aria-label="快速新建活动"> 快速新建活动</label>
          <template v-if="!brief && quickCampaign">
            <label>活动名称（必填）<input v-model="newCampaign.name" aria-label="活动名称（必填）" data-field="campaign_name"></label>
            <label>活动说明<textarea v-model="newCampaign.description" aria-label="活动说明" rows="3" /></label>
          </template>
          <label v-else-if="!brief">已有活动
            <select v-model="campaignId" data-field="campaign"><option value="">请选择</option><option v-for="item in campaigns" :key="item.id" :value="item.id">{{ item.name }}</option></select>
            <button v-if="more.campaigns" type="button" @click="emit('loadMore', 'campaigns')">加载更多活动</button>
            <span v-if="pageErrors.campaigns" role="alert">{{ pageErrors.campaigns }} <button type="button" @click="emit('loadMore', 'campaigns')">重试</button></span>
          </label>
        </section>

        <section v-else-if="step === 2" aria-labelledby="selection-step">
          <h3 id="selection-step">选择产品和平台</h3>
          <fieldset data-field="products"><legend>产品（至少一个）</legend><span v-if="fieldErrors.products" class="field-error">{{ fieldErrors.products }}</span><label v-for="item in products" :key="item.id"><input v-model="productIds" type="checkbox" :value="item.id" :aria-label="item.name_zh || item.name_en"> {{ item.name_zh || item.name_en }}</label><button v-if="more.products" type="button" @click="emit('loadMore', 'products')">加载更多产品</button><span v-if="pageErrors.products" role="alert">{{ pageErrors.products }} <button type="button" @click="emit('loadMore', 'products')">重试</button></span></fieldset>
          <fieldset data-field="platforms"><legend>平台（至少一个）</legend><span v-if="fieldErrors.platforms" class="field-error">{{ fieldErrors.platforms }}</span><label v-for="item in platforms" :key="item.id"><input v-model="platformIds" type="checkbox" :value="item.id" :aria-label="item.name"> {{ item.name }} <small>{{ item.capabilities.join('、') || '基础内容' }}</small></label><button v-if="more.platforms" type="button" @click="emit('loadMore', 'platforms')">加载更多平台</button><span v-if="pageErrors.platforms" role="alert">{{ pageErrors.platforms }} <button type="button" @click="emit('loadMore', 'platforms')">重试</button></span></fieldset>
          <fieldset v-if="assets.length || more.assets || fieldErrors.assets" data-field="assets"><legend>可选素材</legend><span v-if="fieldErrors.assets" class="field-error">{{ fieldErrors.assets }}</span><label v-for="item in assets" :key="item.id"><input v-model="assetIds" type="checkbox" :value="item.id"> {{ item.original_filename }}</label><button v-if="more.assets" type="button" @click="emit('loadMore', 'assets')">加载更多素材</button><span v-if="pageErrors.assets" role="alert">{{ pageErrors.assets }} <button type="button" @click="emit('loadMore', 'assets')">重试</button></span></fieldset>
        </section>

        <section v-else-if="step === 3" aria-labelledby="details-step">
          <h3 id="details-step">填写内容需求</h3>
          <div class="form-grid">
            <label>目标国家（必填）<input v-model="form.target_country" aria-label="目标国家（必填）" data-field="target_country"><span v-if="fieldErrors.target_country" class="field-error">{{ fieldErrors.target_country }}</span></label>
            <label>客户类型（必填）<input v-model="form.customer_type" aria-label="客户类型（必填）" data-field="customer_type"><span v-if="fieldErrors.customer_type" class="field-error">{{ fieldErrors.customer_type }}</span></label>
            <label>内容目标（必填）<input v-model="form.content_objective" aria-label="内容目标（必填）" data-field="content_objective"><span v-if="fieldErrors.content_objective" class="field-error">{{ fieldErrors.content_objective }}</span></label>
            <label>行动号召（必填）<input v-model="form.cta" aria-label="行动号召（必填）" data-field="cta"><span v-if="fieldErrors.cta" class="field-error">{{ fieldErrors.cta }}</span></label>
            <label>落地页（必填）<input v-model="form.landing_page_url" aria-label="落地页（必填）" data-field="landing_page_url"><span v-if="fieldErrors.landing_page_url" class="field-error">{{ fieldErrors.landing_page_url }}</span></label>
            <label>语言（必填）<input v-model="form.language" aria-label="语言（必填）" data-field="language"><span v-if="fieldErrors.language" class="field-error">{{ fieldErrors.language }}</span></label>
            <label>卖点（至少一个）<textarea v-model="form.selling_points" aria-label="卖点" data-field="selling_points" rows="2" /><span v-if="fieldErrors.selling_points" class="field-error">{{ fieldErrors.selling_points }}</span></label>
            <label>优势（至少一个）<textarea v-model="form.advantages" aria-label="优势" data-field="advantages" rows="2" /><span v-if="fieldErrors.advantages" class="field-error">{{ fieldErrors.advantages }}</span></label>
            <label>关键词（至少一个）<textarea v-model="form.keywords" aria-label="关键词" data-field="keywords" rows="2" /><span v-if="fieldErrors.keywords" class="field-error">{{ fieldErrors.keywords }}</span></label>
            <label>禁用说法<textarea v-model="form.prohibited_claims" aria-label="禁用说法" data-field="prohibited_claims" rows="2" /><span v-if="fieldErrors.prohibited_claims" class="field-error">{{ fieldErrors.prohibited_claims }}</span></label>
          </div>
        </section>

        <section v-else aria-labelledby="confirm-step">
          <h3 id="confirm-step">确认需求摘要</h3>
          <dl><div><dt>目标</dt><dd>{{ form.target_country }} · {{ form.customer_type }}</dd></div><div><dt>目的</dt><dd>{{ form.content_objective }}</dd></div><div><dt>选择</dt><dd>{{ productIds.length }} 个产品 · {{ platformIds.length }} 个平台</dd></div></dl>
          <p>创建后先由审核人员确认需求，再开始 AI 生成。</p>
        </section>

        <footer>
          <button v-if="step > 1" type="button" :disabled="busy" @click="step -= 1">上一步</button>
          <button v-if="step < 4" class="primary-action" type="button" :disabled="busy" @click="next">{{ busy ? "正在处理…" : "下一步" }}</button>
          <button v-else class="primary-action" type="button" :disabled="busy" @click="submit">{{ busy ? "正在保存…" : brief ? "保存需求草稿" : "创建需求草稿" }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop{position:fixed;inset:0;z-index:40;display:grid;place-items:center;padding:1rem;background:rgba(20,31,45,.55)}.wizard-dialog{width:min(820px,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.5rem;border-radius:1rem;background:#fff}.wizard-dialog header,.wizard-dialog footer{display:flex;justify-content:space-between;gap:1rem}.wizard-dialog section,.wizard-dialog label{display:grid;gap:.45rem}.wizard-dialog section{gap:1rem}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.wizard-dialog footer{justify-content:flex-end;position:sticky;bottom:-1.5rem;padding:1rem 0 0;background:#fff}.form-alert{padding:.75rem;border-radius:.7rem;background:#fff0ed;color:#79291d}.field-error{color:#79291d;font-size:.9rem}fieldset{display:grid;gap:.5rem;border:1px solid #d8dee8;border-radius:.75rem}@media(max-width:650px){.form-grid{grid-template-columns:1fr}}
</style>
