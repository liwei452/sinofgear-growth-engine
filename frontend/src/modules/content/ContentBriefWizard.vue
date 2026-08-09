<script setup lang="ts">
import { nextTick, reactive, ref } from "vue"

import { ApiError } from "../../api/client"
import { useModalFocus } from "../../shared/composables/useModalFocus"
import type { Product } from "../products/api"
import {
  createBrief, createCampaign, type Asset, type Campaign, type ContentBrief, type Platform,
} from "./api"

const props = defineProps<{
  campaigns: Campaign[]
  products: Product[]
  platforms: Platform[]
  assets: Asset[]
}>()
const emit = defineEmits<{ close: []; saved: [brief: ContentBrief] }>()

const step = ref(1)
const busy = ref(false)
const alert = ref("")
const fieldErrors = reactive<Record<string, string>>({})
const quickCampaign = ref(false)
const campaignId = ref(props.campaigns[0]?.id ?? "")
const newCampaign = reactive({ name: "", description: "" })
const productIds = ref<string[]>([])
const platformIds = ref<string[]>([])
const assetIds = ref<string[]>([])
const form = reactive({
  target_country: "", customer_type: "", content_objective: "", cta: "",
  landing_page_url: "", language: "", selling_points: "", advantages: "",
  keywords: "", prohibited_claims: "",
})
const backdrop = ref<HTMLElement | null>(null)
const dialog = ref<HTMLElement | null>(null)
const title = ref<HTMLElement | null>(null)

useModalFocus({ backdrop, dialog, initialFocus: title, close: () => emit("close") })

function clearErrors(): void {
  alert.value = ""
  for (const key of Object.keys(fieldErrors)) delete fieldErrors[key]
}

async function focusFirstError(): Promise<void> {
  await nextTick()
  const name = Object.keys(fieldErrors)[0]
  dialog.value?.querySelector<HTMLElement>(`[data-field="${name}"]`)?.focus()
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
    if (quickCampaign.value) {
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
  alert.value = ""
  try {
    const brief = await createBrief({
      campaign_id: campaignId.value,
      target_country: form.target_country.trim(), customer_type: form.customer_type.trim(),
      content_objective: form.content_objective.trim(), cta: form.cta.trim(),
      landing_page_url: form.landing_page_url.trim(), language: form.language.trim().toLowerCase(),
      prohibited_claims: list(form.prohibited_claims), selling_points: list(form.selling_points),
      advantages: list(form.advantages), keywords: list(form.keywords),
      product_ids: productIds.value, asset_ids: assetIds.value, platform_ids: platformIds.value,
      concept_links: [],
    })
    emit("saved", brief)
  } catch (error) {
    alert.value = error instanceof ApiError ? error.userMessage : "需求草稿没有创建成功，请重试。"
  } finally { busy.value = false }
}
</script>

<template>
  <Teleport to="body">
    <div ref="backdrop" class="dialog-backdrop" @click.self="emit('close')">
      <section ref="dialog" class="wizard-dialog" role="dialog" aria-modal="true" aria-labelledby="wizard-title">
        <header>
          <div><p class="eyebrow">第 {{ step }} 步，共 4 步</p><h2 id="wizard-title" ref="title" tabindex="-1">创建内容任务</h2></div>
          <button type="button" aria-label="关闭" @click="emit('close')">×</button>
        </header>
        <p v-if="alert" role="alert" class="form-alert">{{ alert }}</p>

        <section v-if="step === 1" aria-labelledby="campaign-step">
          <h3 id="campaign-step">准备活动</h3>
          <label><input v-model="quickCampaign" type="checkbox" aria-label="快速新建活动"> 快速新建活动</label>
          <template v-if="quickCampaign">
            <label>活动名称（必填）<input v-model="newCampaign.name" aria-label="活动名称（必填）" data-field="campaign_name"></label>
            <label>活动说明<textarea v-model="newCampaign.description" aria-label="活动说明" rows="3" /></label>
          </template>
          <label v-else>已有活动
            <select v-model="campaignId" data-field="campaign"><option value="">请选择</option><option v-for="item in campaigns" :key="item.id" :value="item.id">{{ item.name }}</option></select>
          </label>
        </section>

        <section v-else-if="step === 2" aria-labelledby="selection-step">
          <h3 id="selection-step">选择产品和平台</h3>
          <fieldset data-field="products"><legend>产品（至少一个）</legend><label v-for="item in products" :key="item.id"><input v-model="productIds" type="checkbox" :value="item.id" :aria-label="item.name_zh || item.name_en"> {{ item.name_zh || item.name_en }}</label></fieldset>
          <fieldset data-field="platforms"><legend>平台（至少一个）</legend><label v-for="item in platforms" :key="item.id"><input v-model="platformIds" type="checkbox" :value="item.id" :aria-label="item.name"> {{ item.name }} <small>{{ item.capabilities.join('、') || '基础内容' }}</small></label></fieldset>
          <fieldset v-if="assets.length"><legend>可选素材</legend><label v-for="item in assets" :key="item.id"><input v-model="assetIds" type="checkbox" :value="item.id"> {{ item.original_filename }}</label></fieldset>
        </section>

        <section v-else-if="step === 3" aria-labelledby="details-step">
          <h3 id="details-step">填写内容需求</h3>
          <div class="form-grid">
            <label>目标国家（必填）<input v-model="form.target_country" aria-label="目标国家（必填）" data-field="target_country"></label>
            <label>客户类型（必填）<input v-model="form.customer_type" aria-label="客户类型（必填）" data-field="customer_type"></label>
            <label>内容目标（必填）<input v-model="form.content_objective" aria-label="内容目标（必填）" data-field="content_objective"></label>
            <label>行动号召（必填）<input v-model="form.cta" aria-label="行动号召（必填）" data-field="cta"></label>
            <label>落地页（必填）<input v-model="form.landing_page_url" aria-label="落地页（必填）" data-field="landing_page_url"></label>
            <label>语言（必填）<input v-model="form.language" aria-label="语言（必填）" data-field="language"></label>
            <label>卖点<textarea v-model="form.selling_points" aria-label="卖点" rows="2" /></label>
            <label>优势<textarea v-model="form.advantages" aria-label="优势" rows="2" /></label>
            <label>关键词<textarea v-model="form.keywords" aria-label="关键词" rows="2" /></label>
            <label>禁用说法<textarea v-model="form.prohibited_claims" aria-label="禁用说法" rows="2" /></label>
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
          <button v-else class="primary-action" type="button" :disabled="busy" @click="submit">{{ busy ? "正在创建…" : "创建需求草稿" }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop{position:fixed;inset:0;z-index:40;display:grid;place-items:center;padding:1rem;background:rgba(20,31,45,.55)}.wizard-dialog{width:min(820px,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.5rem;border-radius:1rem;background:#fff}.wizard-dialog header,.wizard-dialog footer{display:flex;justify-content:space-between;gap:1rem}.wizard-dialog section,.wizard-dialog label{display:grid;gap:.45rem}.wizard-dialog section{gap:1rem}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.wizard-dialog footer{justify-content:flex-end;position:sticky;bottom:-1.5rem;padding:1rem 0 0;background:#fff}.form-alert{padding:.75rem;border-radius:.7rem;background:#fff0ed;color:#79291d}fieldset{display:grid;gap:.5rem;border:1px solid #d8dee8;border-radius:.75rem}@media(max-width:650px){.form-grid{grid-template-columns:1fr}}
</style>
