<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from "vue"
import { useQuery } from "@tanstack/vue-query"

import { ApiError } from "../../api/client"
import type { KnowledgeConcept } from "../knowledge/api"
import {
  createProduct,
  getProduct,
  patchProduct,
  productQueryKeys,
  type Product,
  type ProductConceptRole,
  type ProductInput,
  type ProductStatus,
} from "./api"

const props = defineProps<{ productId?: string; concepts: KnowledgeConcept[]; readOnly?: boolean }>()
const emit = defineEmits<{ close: []; saved: [product: Product] }>()

type FieldName = keyof ProductInput | "module_min" | "module_max" | "tooth_count_min" | "tooth_count_max" | "pressure_angle" | "moq"
type FormState = {
  name_zh: string
  name_en: string
  module_min: string
  module_max: string
  tooth_count_min: string
  tooth_count_max: string
  pressure_angle: string
  accuracy_grade: string
  heat_treatment: string
  surface_treatment: string
  manufacturing_capabilities: string
  inspection_capabilities: string
  moq: string
  lead_time: string
  landing_page_url: string
  status: ProductStatus
  internal_notes: string
  conceptSelections: Record<ProductConceptRole, string>
}

const emptySelections = (): Record<ProductConceptRole, string> => ({
  TYPE: "", MATERIAL: "", PROCESS: "", STANDARD: "", APPLICATION: "", PARAMETER: "",
})
const form = reactive<FormState>({
  name_zh: "", name_en: "", module_min: "", module_max: "", tooth_count_min: "",
  tooth_count_max: "", pressure_angle: "", accuracy_grade: "", heat_treatment: "",
  surface_treatment: "", manufacturing_capabilities: "", inspection_capabilities: "",
  moq: "", lead_time: "", landing_page_url: "", status: "DRAFT", internal_notes: "",
  conceptSelections: emptySelections(),
})
const errors = reactive<Record<string, string>>({})
const formAlert = ref("")
const saving = ref(false)
const forbidden = ref(false)
const conflict = ref(false)
const currentEtag = ref("")

const isEditing = computed(() => Boolean(props.productId))
const isReadOnly = computed(() => Boolean(props.readOnly) || forbidden.value)
const detailQuery = useQuery({
  queryKey: computed(() => productQueryKeys.detail(props.productId ?? "new")),
  queryFn: () => getProduct(props.productId!),
  enabled: computed(() => Boolean(props.productId)),
})

function hydrate(product: Product, etag: string): void {
  Object.assign(form, {
    name_zh: product.name_zh,
    name_en: product.name_en,
    module_min: product.module_min,
    module_max: product.module_max,
    tooth_count_min: String(product.tooth_count_min),
    tooth_count_max: String(product.tooth_count_max),
    pressure_angle: product.pressure_angle,
    accuracy_grade: product.accuracy_grade,
    heat_treatment: product.heat_treatment,
    surface_treatment: product.surface_treatment,
    manufacturing_capabilities: product.manufacturing_capabilities.join(", "),
    inspection_capabilities: product.inspection_capabilities.join(", "),
    moq: String(product.moq),
    lead_time: product.lead_time,
    landing_page_url: product.landing_page_url,
    status: product.status,
    internal_notes: product.internal_notes,
  })
  form.conceptSelections = emptySelections()
  for (const link of product.concept_links) form.conceptSelections[link.role] = link.concept.id
  currentEtag.value = etag
  conflict.value = false
  formAlert.value = ""
  clearErrors()
}

watch(() => detailQuery.data.value, (detail) => {
  if (detail) hydrate(detail.product, detail.etag)
}, { immediate: true })

function clearErrors(): void {
  for (const field of Object.keys(errors)) delete errors[field]
}

function addError(field: FieldName, message: string): void {
  errors[field] = message
}

function positive(value: string): boolean {
  return value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) > 0
}

function validate(): boolean {
  clearErrors()
  formAlert.value = ""
  if (!form.name_en.trim()) addError("name_en", "请填写英文名称。")
  if (!positive(form.module_min)) addError("module_min", "请输入大于 0 的最小模数。")
  if (!positive(form.module_max)) addError("module_max", "请输入大于 0 的最大模数。")
  if (positive(form.module_min) && positive(form.module_max) && Number(form.module_max) < Number(form.module_min)) {
    addError("module_max", "最大模数不能小于最小模数。")
  }
  if (!positive(form.tooth_count_min) || !Number.isInteger(Number(form.tooth_count_min))) {
    addError("tooth_count_min", "请输入大于 0 的整数。")
  }
  if (!positive(form.tooth_count_max) || !Number.isInteger(Number(form.tooth_count_max))) {
    addError("tooth_count_max", "请输入大于 0 的整数。")
  }
  if (positive(form.tooth_count_min) && positive(form.tooth_count_max)
    && Number(form.tooth_count_max) < Number(form.tooth_count_min)) {
    addError("tooth_count_max", "最多齿数不能小于最少齿数。")
  }
  if (!positive(form.pressure_angle) || Number(form.pressure_angle) > 90) {
    addError("pressure_angle", "请输入大于 0 且不超过 90 的压力角。")
  }
  if (!positive(form.moq) || !Number.isInteger(Number(form.moq))) addError("moq", "请输入大于 0 的整数。")
  if (form.landing_page_url.trim()) {
    try {
      const url = new URL(form.landing_page_url)
      if (!(["http:", "https:"] as string[]).includes(url.protocol)) throw new Error()
    } catch {
      addError("landing_page_url", "请输入 http 或 https 开头的网址。")
    }
  }
  if (Object.keys(errors).length) {
    formAlert.value = "请检查表单中的问题。"
    void focusFirstError()
    return false
  }
  return true
}

async function focusFirstError(): Promise<void> {
  await nextTick()
  const first = Object.keys(errors)[0]
  document.querySelector<HTMLElement>(`[data-field="${first}"]`)?.focus()
}

const splitList = (value: string) => value.split(/[，,]/).map((item) => item.trim()).filter(Boolean)

function payload(): ProductInput {
  return {
    name_zh: form.name_zh.trim(),
    name_en: form.name_en.trim(),
    module_min: form.module_min,
    module_max: form.module_max,
    tooth_count_min: Number(form.tooth_count_min),
    tooth_count_max: Number(form.tooth_count_max),
    pressure_angle: form.pressure_angle,
    accuracy_grade: form.accuracy_grade.trim(),
    heat_treatment: form.heat_treatment.trim(),
    surface_treatment: form.surface_treatment.trim(),
    manufacturing_capabilities: splitList(form.manufacturing_capabilities),
    inspection_capabilities: splitList(form.inspection_capabilities),
    moq: Number(form.moq),
    lead_time: form.lead_time.trim(),
    landing_page_url: form.landing_page_url.trim(),
    status: form.status,
    internal_notes: form.internal_notes.trim(),
    concept_links: Object.entries(form.conceptSelections)
      .filter((entry): entry is [ProductConceptRole, string] => Boolean(entry[1]))
      .map(([role, concept_id]) => ({ role, concept_id })),
  }
}

async function submit(): Promise<void> {
  if (isReadOnly.value || !validate()) return
  saving.value = true
  conflict.value = false
  try {
    const result = props.productId
      ? await patchProduct(props.productId, payload(), currentEtag.value)
      : await createProduct(payload())
    currentEtag.value = result.etag
    emit("saved", result.product)
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      conflict.value = true
      formAlert.value = "数据已被其他人更新。请重新加载最新数据，再决定是否继续编辑。"
    } else if (error instanceof ApiError && error.status === 403) {
      forbidden.value = true
      formAlert.value = "你暂时没有权限修改这个产品，可以继续查看最新信息。"
    } else if (error instanceof ApiError && error.fieldErrors) {
      clearErrors()
      for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages.join(" ")
      formAlert.value = "请检查表单中的问题。"
      await focusFirstError()
    } else {
      formAlert.value = error instanceof ApiError ? error.userMessage : "保存没有完成，请稍后重试。"
    }
  } finally {
    saving.value = false
  }
}

async function reloadLatest(): Promise<void> {
  formAlert.value = ""
  conflict.value = false
  await detailQuery.refetch()
}

const roleForType: Partial<Record<KnowledgeConcept["concept_type"], ProductConceptRole>> = {
  PRODUCT_TYPE: "TYPE", MATERIAL: "MATERIAL", PROCESS: "PROCESS", STANDARD: "STANDARD",
  APPLICATION: "APPLICATION", PARAMETER: "PARAMETER",
}
const roleLabels: Record<ProductConceptRole, string> = {
  TYPE: "产品类型", MATERIAL: "材料", PROCESS: "工艺", STANDARD: "标准",
  APPLICATION: "应用", PARAMETER: "参数",
}
const groupedConcepts = computed(() => {
  const groups = new Map<ProductConceptRole, KnowledgeConcept[]>()
  for (const concept of props.concepts.filter((item) => item.status === "APPROVED")) {
    const role = roleForType[concept.concept_type]
    if (role) groups.set(role, [...(groups.get(role) ?? []), concept])
  }
  return [...groups.entries()]
})
</script>

<template>
  <div class="dialog-backdrop" @click.self="emit('close')">
    <section class="product-dialog" role="dialog" aria-modal="true" aria-labelledby="product-dialog-title">
      <header class="dialog-header">
        <div>
          <p class="eyebrow">{{ isEditing ? "产品详情" : "补充产品事实" }}</p>
          <h2 id="product-dialog-title">{{ isEditing ? "查看和编辑产品" : "新建产品" }}</h2>
        </div>
        <button type="button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <p v-if="detailQuery.isPending.value && isEditing" role="status">正在加载产品详情…</p>
      <div v-else-if="detailQuery.isError.value" role="alert" class="form-alert">
        产品详情没有加载成功，请关闭后重试。
      </div>
      <form v-else novalidate @submit.prevent="submit">
        <div v-if="formAlert" role="alert" class="form-alert">
          <p>{{ formAlert }}</p>
          <button v-if="conflict" type="button" @click="reloadLatest">重新加载最新数据</button>
        </div>

        <fieldset :disabled="isReadOnly">
          <legend>基本信息</legend>
          <div class="form-grid">
            <label>中文名称<input v-model="form.name_zh" data-field="name_zh"></label>
            <label>英文名称（必填）
              <input v-model="form.name_en" aria-label="英文名称（必填）" data-field="name_en" :aria-invalid="Boolean(errors.name_en)" :aria-describedby="errors.name_en ? 'error-name-en' : undefined">
              <span v-if="errors.name_en" id="error-name-en" class="field-error">{{ errors.name_en }}</span>
            </label>
            <label>产品状态
              <select v-model="form.status" data-field="status">
                <option value="DRAFT">草稿</option><option value="ACTIVE">已启用</option><option value="ARCHIVED">已归档</option>
              </select>
            </label>
            <label>最小起订量（必填）
              <input v-model="form.moq" aria-label="最小起订量（必填）" data-field="moq" inputmode="numeric"><span v-if="errors.moq" class="field-error">{{ errors.moq }}</span>
            </label>
            <label>交期<input v-model="form.lead_time" data-field="lead_time"></label>
            <label>落地页网址
              <input v-model="form.landing_page_url" aria-label="落地页网址" data-field="landing_page_url" inputmode="url"><span v-if="errors.landing_page_url" class="field-error">{{ errors.landing_page_url }}</span>
            </label>
          </div>
        </fieldset>

        <fieldset :disabled="isReadOnly">
          <legend>关键规格</legend>
          <div class="form-grid specs-grid">
            <label>最小模数（必填）<input v-model="form.module_min" aria-label="最小模数（必填）" data-field="module_min" inputmode="decimal"><span v-if="errors.module_min" class="field-error">{{ errors.module_min }}</span></label>
            <label>最大模数（必填）<input v-model="form.module_max" aria-label="最大模数（必填）" data-field="module_max" inputmode="decimal"><span v-if="errors.module_max" class="field-error">{{ errors.module_max }}</span></label>
            <label>最少齿数（必填）<input v-model="form.tooth_count_min" aria-label="最少齿数（必填）" data-field="tooth_count_min" inputmode="numeric"><span v-if="errors.tooth_count_min" class="field-error">{{ errors.tooth_count_min }}</span></label>
            <label>最多齿数（必填）<input v-model="form.tooth_count_max" aria-label="最多齿数（必填）" data-field="tooth_count_max" inputmode="numeric"><span v-if="errors.tooth_count_max" class="field-error">{{ errors.tooth_count_max }}</span></label>
            <label>压力角（必填）<input v-model="form.pressure_angle" aria-label="压力角（必填）" data-field="pressure_angle" inputmode="decimal"><span v-if="errors.pressure_angle" class="field-error">{{ errors.pressure_angle }}</span></label>
            <label>精度等级<input v-model="form.accuracy_grade" data-field="accuracy_grade"></label>
          </div>
        </fieldset>

        <details open>
          <summary>制造、检测与标签</summary>
          <div class="form-grid detail-content">
            <label>热处理<input v-model="form.heat_treatment" :disabled="isReadOnly" data-field="heat_treatment"></label>
            <label>表面处理<input v-model="form.surface_treatment" :disabled="isReadOnly" data-field="surface_treatment"></label>
            <label>制造能力（逗号分隔）<input v-model="form.manufacturing_capabilities" :disabled="isReadOnly" data-field="manufacturing_capabilities"></label>
            <label>检测能力（逗号分隔）<input v-model="form.inspection_capabilities" :disabled="isReadOnly" data-field="inspection_capabilities"></label>
            <label v-for="[role, choices] in groupedConcepts" :key="role">{{ roleLabels[role] }}标签
              <select v-model="form.conceptSelections[role]" :disabled="isReadOnly">
                <option value="">未选择</option>
                <option v-for="concept in choices" :key="concept.id" :value="concept.id">{{ concept.label_zh || concept.label_en }}</option>
              </select>
            </label>
          </div>
        </details>
        <details>
          <summary>内部备注</summary>
          <label class="detail-content">仅组织内部可见<textarea v-model="form.internal_notes" :disabled="isReadOnly" rows="3" data-field="internal_notes" /></label>
        </details>

        <footer class="dialog-actions">
          <button type="button" @click="emit('close')">取消</button>
          <button v-if="!isReadOnly" class="primary-action" type="submit" :disabled="saving">
            {{ saving ? "正在保存…" : isEditing ? "保存修改" : "保存产品" }}
          </button>
        </footer>
      </form>
    </section>
  </div>
</template>

<style scoped>
.dialog-backdrop{position:fixed;inset:0;z-index:30;display:grid;place-items:center;padding:1rem;background:rgba(20,31,45,.52)}.product-dialog{width:min(900px,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.5rem;border-radius:1rem;background:#fff;box-shadow:0 24px 64px rgba(15,30,45,.24)}.dialog-header,.dialog-actions{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem}.dialog-header h2{margin-top:0}.form-alert{padding:.75rem 1rem;margin-bottom:1rem;border-radius:.75rem;background:#fff0ed;color:#79291d}.form-alert p{margin-top:0}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.specs-grid{grid-template-columns:repeat(3,minmax(0,1fr))}fieldset{margin:0 0 1rem;padding:1rem;border:1px solid #d8dee8;border-radius:.75rem}label{display:grid;gap:.35rem}input,select,textarea{box-sizing:border-box;width:100%}.field-error{color:#a3261a;font-size:.875rem}.detail-content{margin-top:1rem}details{padding:.85rem 1rem;margin-bottom:1rem;border:1px solid #d8dee8;border-radius:.75rem}summary{font-weight:700;cursor:pointer}.dialog-actions{justify-content:flex-end;position:sticky;bottom:-1.5rem;padding:1rem 0 0;background:#fff}@media(max-width:700px){.form-grid,.specs-grid{grid-template-columns:1fr}.product-dialog{padding:1rem}.dialog-actions{bottom:-1rem}}
</style>
