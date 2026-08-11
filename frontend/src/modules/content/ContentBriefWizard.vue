<script setup lang="ts">
import { computed, nextTick, reactive, ref } from "vue"

import { ApiError } from "../../api/client"
import { useModalFocus } from "../../shared/composables/useModalFocus"
import { formatOrdinaryError } from "../../shared/presentation/ordinary"
import type { Product } from "../products/api"
import {
  createBrief, createCampaign, patchBrief, type Asset, type BriefConcept, type Campaign, type ContentBrief, type Platform,
} from "./api"

const props = withDefaults(defineProps<{
  campaigns: Campaign[]
  products: Product[]
  platforms: Platform[]
  assets: Asset[]
  concepts?: BriefConcept[]
  brief?: ContentBrief | null
  experience?: "ordinary" | "advanced"
  more: Record<"campaigns" | "products" | "platforms" | "assets" | "concepts", boolean>
  pageErrors: Record<"campaigns" | "products" | "platforms" | "assets" | "concepts", string>
}>(), { concepts: () => [], brief: null, experience: "advanced" })
const emit = defineEmits<{
  close: []
  saved: [brief: ContentBrief]
  loadMore: [kind: "campaigns" | "products" | "platforms" | "assets" | "concepts"]
}>()

const step = ref(1)
const ordinaryExperience = computed(() => props.experience === "ordinary")
const busy = ref(false)
const alert = ref("")
const fieldErrors = reactive<Record<string, string>>({})
const quickCampaign = ref(false)
const campaignId = ref(props.brief?.campaign_id ?? (props.experience === "ordinary" ? "" : props.campaigns[0]?.id ?? ""))
const newCampaign = reactive({ name: "", description: "" })
const productIds = ref<string[]>([...(props.brief?.product_ids ?? [])])
const platformIds = ref<string[]>([...(props.brief?.platform_ids ?? [])])
const assetIds = ref<string[]>([...(props.brief?.asset_ids ?? [])])
const conceptIds = ref<string[]>(props.brief?.concept_links.map((link) => link.concept_id) ?? [])
const conceptRoles: Partial<Record<BriefConcept["concept_type"], string>> = {
  PRODUCT_TYPE: "PRODUCT_TYPE",
  PROCESS: "MANUFACTURING_PROCESS",
  INDUSTRY: "TARGET_INDUSTRY",
  CUSTOMER_TYPE: "TARGET_CUSTOMER_TYPE",
  PURCHASE_INTENT: "PURCHASE_INTENT",
  STANDARD: "STANDARD",
  APPLICATION: "APPLICATION",
}
const originalProductIds = new Set(props.brief?.product_ids ?? [])
const originalAssetIds = new Set(props.brief?.asset_ids ?? [])
const originalConceptIds = new Set(props.brief?.concept_links.map((link) => link.concept_id) ?? [])
const availableProducts = computed(() => props.products.filter((product) => product.status === "ACTIVE"))
const unavailableProducts = computed(() => props.products.filter((product) =>
  product.status !== "ACTIVE" && originalProductIds.has(product.id) && productIds.value.includes(product.id),
))
const missingProductIds = computed(() => [...originalProductIds].filter((id) =>
  productIds.value.includes(id) && !props.products.some((product) => product.id === id),
))
const availableAssets = computed(() => props.assets.filter((asset) => asset.status === "ACTIVE"))
const unavailableAssets = computed(() => props.assets.filter((asset) =>
  asset.status !== "ACTIVE" && originalAssetIds.has(asset.id) && assetIds.value.includes(asset.id),
))
const missingAssetIds = computed(() => [...originalAssetIds].filter((id) =>
  assetIds.value.includes(id) && !props.assets.some((asset) => asset.id === id),
))
const isSelectableConcept = (concept: BriefConcept) => concept.status === "APPROVED" && Boolean(conceptRoles[concept.concept_type])
const availableConcepts = computed(() => props.concepts.filter(isSelectableConcept))
const unavailableConcepts = computed(() => props.concepts.filter((concept) =>
  !isSelectableConcept(concept) && originalConceptIds.has(concept.id) && conceptIds.value.includes(concept.id),
))
const missingConceptIds = computed(() => [...originalConceptIds].filter((id) =>
  conceptIds.value.includes(id) && !props.concepts.some((concept) => concept.id === id),
))
const missingProductLabels = new Map<string, string>()
const missingAssetLabels = new Map<string, string>()
const missingConceptLabels = new Map<string, string>()
function stableMissingLabel(labels: Map<string, string>, id: string, kind: string): string {
  const existing = labels.get(id)
  if (existing) return existing
  const label = `${kind} ${labels.size + 1}（名称暂不可用）`
  labels.set(id, label)
  return label
}
const missingProducts = computed(() => missingProductIds.value.map((id) => ({
  id, label: stableMissingLabel(missingProductLabels, id, "历史产品"),
})))
const missingAssets = computed(() => missingAssetIds.value.map((id) => ({
  id, label: stableMissingLabel(missingAssetLabels, id, "历史素材"),
})))
const missingConcepts = computed(() => missingConceptIds.value.map((id) => ({
  id, label: stableMissingLabel(missingConceptLabels, id, "历史知识"),
})))
function productLabel(id: string): string {
  const product = props.products.find((item) => item.id === id)
  return product?.name_zh || product?.name_en || stableMissingLabel(missingProductLabels, id, "历史产品")
}
const existingConceptRoles = new Map(
  props.brief?.concept_links.map((link) => [link.concept_id, link.role]) ?? [],
)
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
  concept_ids: "concepts", concept_links: "concepts", concepts: "concepts",
}
const fieldSteps = computed<Record<string, number>>(() => ordinaryExperience.value
  ? {
      products: 1,
      platforms: 2, target_country: 2, customer_type: 2, content_objective: 2,
      cta: 2, landing_page_url: 2, language: 2,
      assets: 3, concepts: 3, selling_points: 3, advantages: 3,
      keywords: 3, prohibited_claims: 3,
    }
  : {
      campaign: 1, campaign_name: 1,
      products: 2, platforms: 2, assets: 2, concepts: 2,
      target_country: 3, customer_type: 3, content_objective: 3, cta: 3,
      landing_page_url: 3, language: 3, selling_points: 3, advantages: 3,
      keywords: 3, prohibited_claims: 3,
    })
const nextActionLabel = computed(() => {
  if (!ordinaryExperience.value) return "下一步"
  return step.value === 1
    ? "保存产品并继续"
    : step.value === 2
      ? "保存目标并查看素材"
      : "查看并确认方案"
})

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
    const message = ordinaryExperience.value ? "该项内容未通过检查，请修改后重试。" : messages.join(" ")
    if (fieldSteps.value[field]) {
      fieldErrors[field] = fieldErrors[field] ? `${fieldErrors[field]} ${message}` : message
      if (!knownFields.includes(field)) knownFields.push(field)
    } else {
      summaryMessages.push(message)
    }
  }
  if (knownFields.length) {
    const targetStep = Math.min(...knownFields.map((field) => fieldSteps.value[field]))
    step.value = targetStep
    const targetField = knownFields.find((field) => fieldSteps.value[field] === targetStep)
    alert.value = summaryMessages.length
      ? ordinaryExperience.value ? "部分内容未通过检查，请修改后重试。" : `请检查以下问题：${summaryMessages.join(" ")}`
      : "请检查标出的字段后重试。"
    await focusFirstError(targetField)
  } else {
    alert.value = ordinaryExperience.value
      ? formatOrdinaryError(error)
      : summaryMessages.join(" ") || error.userMessage
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

function removeProduct(id: string): void {
  productIds.value = productIds.value.filter((selected) => selected !== id)
}

function removeAsset(id: string): void {
  assetIds.value = assetIds.value.filter((selected) => selected !== id)
}

function removeConcept(id: string): void {
  conceptIds.value = conceptIds.value.filter((selected) => selected !== id)
}

function usePreset(field: "selling_points" | "advantages", value: string): void {
  const values = list(form[field])
  form[field] = values.includes(value) ? values.filter((item) => item !== value).join("，") : [...values, value].join("，")
}

async function validateOrdinaryStep(): Promise<boolean> {
  if (step.value === 1) {
    if (!productIds.value.length) {
      fieldErrors.products = "请至少选择一个产品。"
      alert.value = "请先选择这次要推广的产品。"
      await focusFirstError("products")
      return false
    }
    const selected = props.products.find((item) => item.id === productIds.value[0])
    if (!form.keywords.trim()) form.keywords = selected?.name_zh || selected?.name_en || "产品"
    if (!form.landing_page_url.trim()) form.landing_page_url = selected?.landing_page_url ?? ""
  }
  if (step.value === 2) {
    for (const key of ["target_country", "customer_type", "content_objective", "cta", "language"] as const) {
      if (!form[key].trim()) fieldErrors[key] = "请选择一项。"
    }
    if (!platformIds.value.length) fieldErrors.platforms = "请选择至少一个推广渠道。"
    if (form.landing_page_url) {
      try {
        const url = new URL(form.landing_page_url)
        if (!(url.protocol === "http:" || url.protocol === "https:")) throw new Error()
      } catch { fieldErrors.landing_page_url = "请输入 http 或 https 开头的网址。" }
    }
    if (Object.keys(fieldErrors).length) {
      alert.value = "请完成推广目标和渠道选择。"
      await focusFirstError()
      return false
    }
  }
  if (step.value === 3) {
    if (!list(form.selling_points).length) fieldErrors.selling_points = "请选择或填写至少一个卖点。"
    if (!list(form.advantages).length) fieldErrors.advantages = "请选择或填写至少一个优势。"
    if (!list(form.keywords).length) fieldErrors.keywords = "请填写至少一个关键词。"
    if (Object.keys(fieldErrors).length) {
      alert.value = "请补全用于生成方案的必要信息。"
      await focusFirstError()
      return false
    }
  }
  return true
}

async function next(): Promise<void> {
  clearErrors()
  if (ordinaryExperience.value) {
    if (!(await validateOrdinaryStep())) return
    step.value += 1
    return
  }
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
    const conceptLinks = conceptIds.value.map((conceptId) => {
      const concept = props.concepts.find((item) => item.id === conceptId)
      const role = concept
        ? conceptRoles[concept.concept_type] ?? existingConceptRoles.get(conceptId)
        : existingConceptRoles.get(conceptId)
      return role ? { role, concept_id: conceptId } : null
    })
    if (conceptLinks.some((link) => link === null)) {
      step.value = ordinaryExperience.value ? 3 : 2
      alert.value = "所选知识类型不支持内容需求，请取消选择后重试。"
      await focusFirstError("concepts")
      return
    }
    const validConceptLinks = conceptLinks.filter((link): link is { role: string; concept_id: string } => link !== null)
    const input = {
      target_country: form.target_country.trim(), customer_type: form.customer_type.trim(),
      content_objective: form.content_objective.trim(), cta: form.cta.trim(),
      landing_page_url: form.landing_page_url.trim(), language: form.language.trim().toLowerCase(),
      prohibited_claims: list(form.prohibited_claims), selling_points: list(form.selling_points),
      advantages: list(form.advantages), keywords: list(form.keywords),
      product_ids: productIds.value, asset_ids: assetIds.value, platform_ids: platformIds.value,
      concept_links: validConceptLinks,
    }
    if (!props.brief && ordinaryExperience.value && !campaignId.value) {
      const selectedProduct = props.products.find((item) => item.id === productIds.value[0])
      campaignId.value = (await createCampaign({
        name: `${selectedProduct?.name_zh || selectedProduct?.name_en || "产品"}推广`,
        description: `${form.target_country} · ${form.content_objective}`,
      })).id
    }
    const brief = props.brief
      ? await patchBrief(props.brief.id, input)
      : await createBrief({ campaign_id: campaignId.value, ...input })
    emit("saved", brief)
  } catch (error) {
    if (!(error instanceof ApiError) || !(await applyServerFieldErrors(error))) {
      alert.value = ordinaryExperience.value
        ? formatOrdinaryError(error)
        : error instanceof ApiError ? error.userMessage : "需求草稿没有创建成功，请重试。"
    }
  } finally { busy.value = false }
}
</script>

<template>
  <Teleport to="body">
    <div ref="backdrop" class="dialog-backdrop" @click.self="emit('close')">
      <section ref="dialog" class="wizard-dialog" role="dialog" aria-modal="true" aria-labelledby="wizard-title">
        <header>
          <div><p class="eyebrow">第 {{ step }} 步，共 4 步</p><h2 id="wizard-title" ref="title" tabindex="-1">{{ ordinaryExperience ? (brief ? '修改推广方案' : '制定推广方案') : (brief ? '编辑需求草稿' : '创建内容任务') }}</h2></div>
          <button type="button" aria-label="关闭" @click="emit('close')">×</button>
        </header>
        <p v-if="alert" ref="alertElement" role="alert" class="form-alert" tabindex="-1">{{ alert }}</p>

        <template v-if="ordinaryExperience">
          <ol class="wizard-progress" aria-label="方案准备进度">
            <li :aria-current="step === 1 ? 'step' : undefined">选择产品</li><li :aria-current="step === 2 ? 'step' : undefined">告诉 AI 目标</li><li :aria-current="step === 3 ? 'step' : undefined">查看可用素材</li><li :aria-current="step === 4 ? 'step' : undefined">确认方案</li>
          </ol>
          <section v-if="step === 1" aria-labelledby="ordinary-product-step">
            <h3 id="ordinary-product-step">选择产品</h3><p>从当前组织的可用产品中选择，后续方案只使用真实产品资料。</p>
            <fieldset data-field="products"><legend>这次推广什么？</legend><span v-if="fieldErrors.products" class="field-error">{{ fieldErrors.products }}</span><label v-for="item in availableProducts" :key="item.id"><input v-model="productIds" type="checkbox" :value="item.id" :aria-label="item.name_zh || item.name_en"> {{ item.name_zh || item.name_en }}</label><label v-for="item in unavailableProducts" :key="`unavailable-${item.id}`"><input type="checkbox" checked :aria-label="`${item.name_zh || item.name_en}（不可用，仅可移除）`" @change="removeProduct(item.id)"> {{ item.name_zh || item.name_en }} <small>不可用，仅可移除</small></label><label v-for="item in missingProducts" :key="`missing-${item.id}`"><input type="checkbox" checked :aria-label="`${item.label}（不可用，仅可移除）`" @change="removeProduct(item.id)"> {{ item.label }} <small>不可用，仅可移除</small></label><button v-if="more.products" type="button" @click="emit('loadMore', 'products')">加载更多产品</button><span v-if="pageErrors.products" role="alert">{{ pageErrors.products }} <button type="button" @click="emit('loadMore', 'products')">重试</button></span></fieldset>
          </section>
          <section v-else-if="step === 2" aria-labelledby="ordinary-goal-step">
            <h3 id="ordinary-goal-step">告诉 AI 目标</h3><p>使用明确选项约束方案，不会模拟自由聊天。</p>
            <div class="form-grid">
              <label>目标市场（必选）<select v-model="form.target_country" data-field="target_country"><option value="">请选择</option><option>中国</option><option>德国</option><option>美国</option><option>日本</option></select><span v-if="fieldErrors.target_country" class="field-error">{{ fieldErrors.target_country }}</span></label>
              <label>目标客户（必选）<select v-model="form.customer_type" data-field="customer_type"><option value="">请选择</option><option>工业采购</option><option>工程师</option><option>渠道伙伴</option></select><span v-if="fieldErrors.customer_type" class="field-error">{{ fieldErrors.customer_type }}</span></label>
              <label>推广目标（必选）<select v-model="form.content_objective" data-field="content_objective"><option value="">请选择</option><option>获取询盘</option><option>介绍产品</option><option>建立品牌认知</option></select><span v-if="fieldErrors.content_objective" class="field-error">{{ fieldErrors.content_objective }}</span></label>
              <label>希望客户下一步（必选）<select v-model="form.cta" data-field="cta"><option value="">请选择</option><option>立即询价</option><option>获取样品</option><option>查看产品详情</option></select><span v-if="fieldErrors.cta" class="field-error">{{ fieldErrors.cta }}</span></label>
              <label>内容语言（必选）<select v-model="form.language" data-field="language"><option value="">请选择</option><option value="zh">中文</option><option value="en">英文</option><option value="de">德文</option><option value="ja">日文</option></select><span v-if="fieldErrors.language" class="field-error">{{ fieldErrors.language }}</span></label>
              <label>落地页（可选）<input v-model="form.landing_page_url" aria-label="落地页（可选）" data-field="landing_page_url" placeholder="https://"><span v-if="fieldErrors.landing_page_url" class="field-error">{{ fieldErrors.landing_page_url }}</span></label>
            </div>
            <fieldset data-field="platforms"><legend>推广渠道（至少一个）</legend><span v-if="fieldErrors.platforms" class="field-error">{{ fieldErrors.platforms }}</span><label v-for="item in platforms" :key="item.id"><input v-model="platformIds" type="checkbox" :value="item.id" :aria-label="item.name"> {{ item.name }}</label><button v-if="more.platforms" type="button" @click="emit('loadMore', 'platforms')">加载更多推广渠道</button><span v-if="pageErrors.platforms" role="alert">{{ pageErrors.platforms }} <button type="button" @click="emit('loadMore', 'platforms')">重试</button></span></fieldset>
          </section>
          <section v-else-if="step === 3" aria-labelledby="ordinary-material-step">
            <h3 id="ordinary-material-step">查看可用素材</h3><p>素材和知识均来自已加载的真实资料；不选择也不会虚构来源。</p>
            <fieldset v-if="availableAssets.length || unavailableAssets.length || missingAssetIds.length || more.assets || fieldErrors.assets" data-field="assets"><legend>可选素材</legend><span v-if="fieldErrors.assets" class="field-error">{{ fieldErrors.assets }}</span><label v-for="item in availableAssets" :key="item.id"><input v-model="assetIds" type="checkbox" :value="item.id"> {{ item.original_filename }}</label><label v-for="item in unavailableAssets" :key="`unavailable-${item.id}`"><input type="checkbox" checked :aria-label="`${item.original_filename}（不可用，仅可移除）`" @change="removeAsset(item.id)"> {{ item.original_filename }} <small>不可用，仅可移除</small></label><label v-for="item in missingAssets" :key="`missing-${item.id}`"><input type="checkbox" checked :aria-label="`${item.label}（不可用，仅可移除）`" @change="removeAsset(item.id)"> {{ item.label }} <small>不可用，仅可移除</small></label><button v-if="more.assets" type="button" @click="emit('loadMore', 'assets')">加载更多素材</button><span v-if="pageErrors.assets" role="alert">{{ pageErrors.assets }} <button type="button" @click="emit('loadMore', 'assets')">重试</button></span></fieldset>
            <fieldset v-if="availableConcepts.length || unavailableConcepts.length || missingConceptIds.length || more.concepts || fieldErrors.concepts" data-field="concepts"><legend>已批准知识（可选）</legend><span v-if="fieldErrors.concepts" class="field-error">{{ fieldErrors.concepts }}</span><label v-for="item in availableConcepts" :key="item.id"><input v-model="conceptIds" type="checkbox" :value="item.id" :aria-label="`${item.label_en || item.label_zh} (${item.concept_type})`"> {{ item.label_zh || item.label_en }}</label><label v-for="item in unavailableConcepts" :key="`unavailable-${item.id}`"><input type="checkbox" checked :aria-label="`${item.label_en || item.label_zh} (${item.concept_type})（不可用，仅可移除）`" @change="removeConcept(item.id)"> {{ item.label_zh || item.label_en }} <small>不可用，仅可移除</small></label><label v-for="item in missingConcepts" :key="`missing-${item.id}`"><input type="checkbox" checked :aria-label="`${item.label}（不可用，仅可移除）`" @change="removeConcept(item.id)"> {{ item.label }} <small>不可用，仅可移除</small></label><button v-if="more.concepts" type="button" @click="emit('loadMore', 'concepts')">加载更多知识</button><span v-if="pageErrors.concepts" role="alert">{{ pageErrors.concepts }} <button type="button" @click="emit('loadMore', 'concepts')">重试</button></span></fieldset>
            <fieldset><legend>方案重点</legend><div class="preset-row"><button v-for="value in ['精密制造','稳定交付','支持定制']" :key="value" type="button" :aria-pressed="list(form.selling_points).includes(value)" @click="usePreset('selling_points', value)">{{ value }}</button></div><label>补充卖点（简短填写）<input v-model="form.selling_points" data-field="selling_points"><span v-if="fieldErrors.selling_points" class="field-error">{{ fieldErrors.selling_points }}</span></label><div class="preset-row"><button v-for="value in ['质量可追溯','交付周期清晰','工程支持']" :key="value" type="button" :aria-pressed="list(form.advantages).includes(value)" @click="usePreset('advantages', value)">{{ value }}</button></div><label>补充优势（简短填写）<input v-model="form.advantages" data-field="advantages"><span v-if="fieldErrors.advantages" class="field-error">{{ fieldErrors.advantages }}</span></label><label>关键词（逗号分隔）<input v-model="form.keywords" data-field="keywords"><span v-if="fieldErrors.keywords" class="field-error">{{ fieldErrors.keywords }}</span></label><label>不能使用的说法（可选）<input v-model="form.prohibited_claims" data-field="prohibited_claims"></label></fieldset>
          </section>
          <section v-else aria-labelledby="ordinary-confirm-step"><h3 id="ordinary-confirm-step">确认方案</h3><dl><div><dt>产品</dt><dd>{{ productIds.map(productLabel).join('、') }}</dd></div><div><dt>目标</dt><dd>{{ form.target_country }} · {{ form.customer_type }} · {{ form.content_objective }}</dd></div><div><dt>渠道与素材</dt><dd>{{ platformIds.length }} 个渠道 · {{ assetIds.length }} 份素材</dd></div><div><dt>方案重点</dt><dd>{{ form.selling_points }}；{{ form.advantages }}</dd></div></dl><p>确认后会保存真实推广方案，等待有权限的同事审核；此处不会假装已经调用 AI 模型。</p></section>
        </template>

        <section v-else-if="step === 1" aria-labelledby="campaign-step">
          <h3 id="campaign-step">准备活动</h3>
          <p v-if="brief">活动保持不变：{{ campaigns.find(item => item.id === campaignId)?.name || '历史活动（名称暂不可用）' }}</p>
          <details v-if="brief && !campaigns.some(item => item.id === campaignId)"><summary>内部ID</summary><code>{{ campaignId }}</code></details>
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

        <section v-if="!ordinaryExperience && step === 2" aria-labelledby="selection-step">
          <h3 id="selection-step">选择产品和平台</h3>
          <fieldset data-field="products"><legend>产品（至少一个）</legend><span v-if="fieldErrors.products" class="field-error">{{ fieldErrors.products }}</span><label v-for="item in availableProducts" :key="item.id"><input v-model="productIds" type="checkbox" :value="item.id" :aria-label="item.name_zh || item.name_en"> {{ item.name_zh || item.name_en }}</label><label v-for="item in unavailableProducts" :key="`unavailable-${item.id}`"><input type="checkbox" checked :aria-label="`${item.name_zh || item.name_en}（不可用，仅可移除）`" @change="removeProduct(item.id)"> {{ item.name_zh || item.name_en }} <small>不可用，仅可移除</small></label><div v-for="item in missingProducts" :key="`missing-${item.id}`" class="missing-link"><label><input type="checkbox" checked :aria-label="`${item.label}（不可用，仅可移除）`" @change="removeProduct(item.id)"> {{ item.label }} <small>不可用，仅可移除</small></label><details><summary>内部ID</summary><code>{{ item.id }}</code></details></div><button v-if="more.products" type="button" @click="emit('loadMore', 'products')">加载更多产品</button><span v-if="pageErrors.products" role="alert">{{ pageErrors.products }} <button type="button" @click="emit('loadMore', 'products')">重试</button></span></fieldset>
          <fieldset data-field="platforms"><legend>平台（至少一个）</legend><span v-if="fieldErrors.platforms" class="field-error">{{ fieldErrors.platforms }}</span><label v-for="item in platforms" :key="item.id"><input v-model="platformIds" type="checkbox" :value="item.id" :aria-label="item.name"> {{ item.name }} <small>{{ item.capabilities.join('、') || '基础内容' }}</small></label><button v-if="more.platforms" type="button" @click="emit('loadMore', 'platforms')">加载更多平台</button><span v-if="pageErrors.platforms" role="alert">{{ pageErrors.platforms }} <button type="button" @click="emit('loadMore', 'platforms')">重试</button></span></fieldset>
          <fieldset v-if="availableAssets.length || unavailableAssets.length || missingAssetIds.length || more.assets || fieldErrors.assets" data-field="assets"><legend>可选素材</legend><span v-if="fieldErrors.assets" class="field-error">{{ fieldErrors.assets }}</span><label v-for="item in availableAssets" :key="item.id"><input v-model="assetIds" type="checkbox" :value="item.id"> {{ item.original_filename }}</label><label v-for="item in unavailableAssets" :key="`unavailable-${item.id}`"><input type="checkbox" checked :aria-label="`${item.original_filename}（不可用，仅可移除）`" @change="removeAsset(item.id)"> {{ item.original_filename }} <small>不可用，仅可移除</small></label><div v-for="item in missingAssets" :key="`missing-${item.id}`" class="missing-link"><label><input type="checkbox" checked :aria-label="`${item.label}（不可用，仅可移除）`" @change="removeAsset(item.id)"> {{ item.label }} <small>不可用，仅可移除</small></label><details><summary>内部ID</summary><code>{{ item.id }}</code></details></div><button v-if="more.assets" type="button" @click="emit('loadMore', 'assets')">加载更多素材</button><span v-if="pageErrors.assets" role="alert">{{ pageErrors.assets }} <button type="button" @click="emit('loadMore', 'assets')">重试</button></span></fieldset>
          <fieldset v-if="availableConcepts.length || unavailableConcepts.length || missingConceptIds.length || more.concepts" data-field="concepts"><legend>已批准知识（可选）</legend><label v-for="item in availableConcepts" :key="item.id"><input v-model="conceptIds" type="checkbox" :value="item.id" :aria-label="`${item.label_en || item.label_zh} (${item.concept_type})`"> {{ item.label_zh || item.label_en }} <small>{{ item.code }}</small></label><label v-for="item in unavailableConcepts" :key="`unavailable-${item.id}`"><input type="checkbox" checked :aria-label="`${item.label_en || item.label_zh} (${item.concept_type})（不可用，仅可移除）`" @change="removeConcept(item.id)"> {{ item.label_zh || item.label_en }} <small>不可用，仅可移除</small></label><div v-for="item in missingConcepts" :key="`missing-${item.id}`" class="missing-link"><label><input type="checkbox" checked :aria-label="`${item.label}（不可用，仅可移除）`" @change="removeConcept(item.id)"> {{ item.label }} <small>不可用，仅可移除</small></label><details><summary>内部ID</summary><code>{{ item.id }}</code></details></div><button v-if="more.concepts" type="button" @click="emit('loadMore', 'concepts')">加载更多知识</button><span v-if="pageErrors.concepts" role="alert">{{ pageErrors.concepts }} <button type="button" @click="emit('loadMore', 'concepts')">重试</button></span></fieldset>
        </section>

        <section v-else-if="!ordinaryExperience && step === 3" aria-labelledby="details-step">
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

        <section v-else-if="!ordinaryExperience" aria-labelledby="confirm-step">
          <h3 id="confirm-step">确认需求摘要</h3>
          <dl><div><dt>目标</dt><dd>{{ form.target_country }} · {{ form.customer_type }}</dd></div><div><dt>目的</dt><dd>{{ form.content_objective }}</dd></div><div><dt>选择</dt><dd>{{ productIds.length }} 个产品 · {{ platformIds.length }} 个平台</dd></div></dl>
          <p>创建后先由审核人员确认需求，再开始 AI 生成。</p>
        </section>

        <footer>
          <button v-if="step > 1" type="button" :disabled="busy" @click="step -= 1">上一步</button>
          <button v-if="step < 4" class="primary-action" type="button" :disabled="busy" @click="next">{{ busy ? "正在处理…" : nextActionLabel }}</button>
          <button v-else class="primary-action" type="button" :disabled="busy" @click="submit">{{ busy ? "正在保存…" : ordinaryExperience ? (brief ? "保存修改方案" : "保存推广方案") : brief ? "保存需求草稿" : "创建需求草稿" }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop{position:fixed;inset:0;z-index:40;display:grid;place-items:center;padding:1rem;background:rgba(20,31,45,.55)}.wizard-dialog{width:min(820px,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.5rem;border-radius:1rem;background:var(--sg-surface)}.wizard-dialog header,.wizard-dialog footer{display:flex;justify-content:space-between;gap:1rem}.wizard-dialog section,.wizard-dialog label{display:grid;gap:.45rem}.wizard-dialog section{gap:1rem}.wizard-progress{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem;padding:0;list-style:none}.wizard-progress li{padding:.55rem;border-radius:.6rem;background:var(--sg-status-neutral-tint);color:var(--sg-muted);text-align:center}.wizard-progress li[aria-current=step]{background:var(--sg-brand-tint);color:var(--sg-brand);font-weight:800}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.preset-row{display:flex;flex-wrap:wrap;gap:.5rem}.preset-row button[aria-pressed=true]{border-color:var(--sg-brand);background:var(--sg-brand-tint);color:var(--sg-brand)}.wizard-dialog footer{justify-content:flex-end;position:sticky;bottom:-1.5rem;padding:1rem 0 0;background:var(--sg-surface)}.form-alert{padding:.75rem;border-radius:.7rem;background:var(--sg-status-danger-tint);color:var(--sg-status-danger)}.field-error{color:var(--sg-status-danger);font-size:.9rem}fieldset{display:grid;gap:.5rem;border:1px solid var(--sg-line);border-radius:.75rem}@media(max-width:650px){.form-grid,.wizard-progress{grid-template-columns:1fr}.wizard-progress li:not([aria-current=step]){display:none}}@media(prefers-reduced-motion:reduce){.wizard-dialog{scroll-behavior:auto}}
.wizard-progress li[aria-current=step]{background-color:var(--sg-brand-tint)}
</style>
