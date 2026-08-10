<script setup lang="ts">
import { nextTick, reactive, ref } from "vue"

import { ApiError } from "../../api/client"
import { useModalFocus } from "../../shared/composables/useModalFocus"
import { createConcept, type ConceptInput, type ConceptType, type KnowledgeConcept } from "./api"

const emit = defineEmits<{ close: []; saved: [concept: KnowledgeConcept] }>()
const form = reactive({ concept_type: "" as "" | ConceptType, code: "", label_zh: "", label_en: "", description: "" })
const errors = reactive<Record<string, string>>({})
const alert = ref("")
const submitting = ref(false)
const backdropElement = ref<HTMLElement | null>(null)
const dialogElement = ref<HTMLElement | null>(null)
const titleElement = ref<HTMLElement | null>(null)

useModalFocus({
  backdrop: backdropElement,
  dialog: dialogElement,
  initialFocus: titleElement,
  close: () => emit("close"),
})

const types: Array<[ConceptType, string]> = [
  ["CAPABILITY", "能力"], ["REQUIREMENT", "需求"],
  ["PRODUCT_TYPE", "产品类型"], ["PARAMETER", "参数"], ["MATERIAL", "材料"],
  ["PROCESS", "工艺"], ["STANDARD", "标准"], ["APPLICATION", "应用"], ["INDUSTRY", "行业"],
  ["CUSTOMER_TYPE", "客户类型"], ["PURCHASE_INTENT", "采购意图"],
]

function clearErrors(): void { for (const field of Object.keys(errors)) delete errors[field] }
async function focusFirst(): Promise<void> {
  await nextTick()
  dialogElement.value?.querySelector<HTMLElement>(`[data-field="${Object.keys(errors)[0]}"]`)?.focus()
}
function validate(): boolean {
  clearErrors(); alert.value = ""
  if (!form.concept_type) errors.concept_type = "请选择知识类型。"
  if (!form.code.trim()) errors.code = "请填写编码。"
  if (!form.label_zh.trim()) errors.label_zh = "请填写中文名称。"
  if (!form.label_en.trim()) errors.label_en = "请填写英文名称。"
  if (Object.keys(errors).length) { alert.value = "请检查表单中的问题。"; void focusFirst(); return false }
  return true
}

async function submit(): Promise<void> {
  if (!validate()) return
  submitting.value = true
  try {
    const input: ConceptInput = {
      scope: "ORGANIZATION", concept_type: form.concept_type as ConceptType,
      code: form.code.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_"),
      label_zh: form.label_zh.trim(), label_en: form.label_en.trim(), description: form.description.trim(),
    }
    emit("saved", await createConcept(input))
  } catch (error) {
    if (error instanceof ApiError && error.fieldErrors) {
      clearErrors()
      for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages.join(" ")
      alert.value = "请检查表单中的问题。"
      submitting.value = false
      await focusFirst()
    } else alert.value = error instanceof ApiError ? error.userMessage : "提交没有完成，请稍后重试。"
  } finally { submitting.value = false }
}
</script>

<template>
  <Teleport to="body">
    <div ref="backdropElement" class="dialog-backdrop" @click.self="emit('close')">
      <section ref="dialogElement" class="concept-dialog" role="dialog" aria-modal="true" aria-labelledby="concept-dialog-title">
        <header><div><p class="eyebrow">组织知识建议</p><h2 id="concept-dialog-title" ref="titleElement" tabindex="-1">新增知识建议</h2></div><button type="button" aria-label="关闭" @click="emit('close')">×</button></header>
        <p>建议会先进入待审核状态，不会直接改变系统知识。</p>
        <form novalidate @submit.prevent="submit">
          <p v-if="alert" role="alert" class="form-alert">{{ alert }}</p>
          <label>知识类型（必填）
            <select v-model="form.concept_type" aria-label="知识类型（必填）" data-field="concept_type"><option value="">请选择</option><option v-for="[value,label] in types" :key="value" :value="value">{{ label }}</option></select>
            <span v-if="errors.concept_type" class="field-error">{{ errors.concept_type }}</span>
          </label>
          <label>编码（必填）<input v-model="form.code" aria-label="编码（必填）" data-field="code"><span v-if="errors.code" class="field-error">{{ errors.code }}</span></label>
          <div class="name-grid">
            <label>中文名称（必填）<input v-model="form.label_zh" aria-label="中文名称（必填）" data-field="label_zh"><span v-if="errors.label_zh" class="field-error">{{ errors.label_zh }}</span></label>
            <label>英文名称（必填）<input v-model="form.label_en" aria-label="英文名称（必填）" data-field="label_en"><span v-if="errors.label_en" class="field-error">{{ errors.label_en }}</span></label>
          </div>
          <label>说明<textarea v-model="form.description" rows="4" /></label>
          <footer><button type="button" @click="emit('close')">取消</button><button class="primary-action" type="submit" :disabled="submitting">{{ submitting ? "正在提交…" : "提交知识建议" }}</button></footer>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop{position:fixed;inset:0;z-index:30;display:grid;place-items:center;padding:1rem;background:rgba(20,31,45,.52)}.concept-dialog{width:min(680px,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.5rem;border-radius:1rem;background:#fff}.concept-dialog header,.concept-dialog footer{display:flex;justify-content:space-between;gap:1rem}.concept-dialog form,.concept-dialog label{display:grid;gap:.45rem}.concept-dialog form{gap:1rem}.name-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.concept-dialog footer{justify-content:flex-end}.field-error{color:#a3261a;font-size:.875rem}.form-alert{padding:.75rem 1rem;border-radius:.75rem;background:#fff0ed;color:#79291d}@media(max-width:600px){.name-grid{grid-template-columns:1fr}}
</style>
