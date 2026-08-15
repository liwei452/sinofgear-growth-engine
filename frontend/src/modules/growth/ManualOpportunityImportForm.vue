<script setup lang="ts">
import { reactive, ref } from "vue"

import { ApiError } from "../../api/client"
import { importManualOpportunity } from "./api"

const emit = defineEmits<{
  imported: [accountId: string]
  cancelled: []
}>()

const form = reactive({
  company_name: "",
  country: "",
  industry: "",
  source_label: "",
  source_url: "",
  evidence_text: "",
})
const pending = ref(false)
const errorMessage = ref("")
const fieldErrors = ref<Record<string, string[]>>({})

async function submit(): Promise<void> {
  pending.value = true
  errorMessage.value = ""
  fieldErrors.value = {}
  try {
    const result = await importManualOpportunity({ ...form })
    emit("imported", result.account.id)
  } catch (error) {
    if (error instanceof ApiError) {
      errorMessage.value = error.userMessage
      fieldErrors.value = error.fieldErrors ?? {}
    } else {
      errorMessage.value = "暂时无法保存，请稍后重试。"
    }
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <section class="growth-card manual-opportunity-import" aria-labelledby="manual-import-title">
    <div>
      <p class="eyebrow">用户提供的公开信息</p>
      <h2 id="manual-import-title">保存公开线索</h2>
      <p class="manual-import-safety">系统不会访问该网页，也不会自动联系客户；请只提交你有权使用的公开信息。</p>
    </div>
    <form novalidate @submit.prevent="submit">
      <label>
        公司名称
        <input v-model.trim="form.company_name" name="company_name" required maxlength="255">
        <small v-if="fieldErrors.company_name">{{ fieldErrors.company_name[0] }}</small>
      </label>
      <label>
        国家或地区
        <input v-model.trim="form.country" name="country" required maxlength="96">
        <small v-if="fieldErrors.country">{{ fieldErrors.country[0] }}</small>
      </label>
      <label>
        行业（选填）
        <input v-model.trim="form.industry" name="industry" maxlength="160">
        <small v-if="fieldErrors.industry">{{ fieldErrors.industry[0] }}</small>
      </label>
      <label>
        来源名称
        <input v-model.trim="form.source_label" name="source_label" required maxlength="255">
        <small v-if="fieldErrors.source_label">{{ fieldErrors.source_label[0] }}</small>
      </label>
      <label class="manual-import-wide">
        公开 HTTPS 链接
        <input v-model.trim="form.source_url" name="source_url" required inputmode="url" maxlength="200" placeholder="https://">
        <small v-if="fieldErrors.source_url">{{ fieldErrors.source_url[0] }}</small>
      </label>
      <label class="manual-import-wide">
        原始证据摘要
        <textarea v-model.trim="form.evidence_text" name="evidence_text" required minlength="10" rows="4" />
        <small v-if="fieldErrors.evidence_text">{{ fieldErrors.evidence_text[0] }}</small>
      </label>
      <p v-if="errorMessage" class="manual-import-error" role="alert">{{ errorMessage }}</p>
      <div class="page-actions manual-import-actions">
        <button class="button button-primary" type="submit" :disabled="pending">
          {{ pending ? "正在保存…" : "保存为待核实机会" }}
        </button>
        <button class="button button-secondary" type="button" :disabled="pending" @click="emit('cancelled')">取消</button>
      </div>
    </form>
  </section>
</template>
