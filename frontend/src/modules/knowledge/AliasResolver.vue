<script setup lang="ts">
import { ref } from "vue"

import { ApiError } from "../../api/client"
import { resolveAlias, type AliasResolution } from "./api"

const text = ref("")
const language = ref("zh")
const result = ref<AliasResolution>()
const message = ref("")
const checking = ref(false)

async function check(): Promise<void> {
  message.value = ""
  result.value = undefined
  if (!text.value.trim()) {
    message.value = "请输入要检查的名称。"
    return
  }
  checking.value = true
  try {
    result.value = await resolveAlias({ text: text.value.trim(), language: language.value })
  } catch (error) {
    message.value = error instanceof ApiError ? error.userMessage : "名称检查没有完成，请稍后重试。"
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <details class="resolver-panel">
    <summary>检查一个名称</summary>
    <p>输入客户或市场常用叫法，检查它是否对应现有的已通过知识。</p>
    <form class="resolver-form" @submit.prevent="check">
      <label>要检查的名称<input v-model="text"></label>
      <label>语言
        <select v-model="language"><option value="zh">中文</option><option value="en">English</option></select>
      </label>
      <button type="submit" :disabled="checking">{{ checking ? "正在检查…" : "检查名称" }}</button>
    </form>
    <div class="resolver-result" aria-live="polite">
      <p v-if="message">{{ message }}</p>
      <template v-else-if="result?.selected">
        <p>唯一匹配：{{ result.selected.label_zh || result.selected.label_en }}（{{ result.selected.code }}）</p>
      </template>
      <template v-else-if="result?.ambiguous">
        <p>找到多个可能匹配，请人工确认：</p>
        <ul><li v-for="candidate in result.candidates" :key="candidate.concept_id">{{ candidate.label_zh || candidate.label_en }}（{{ candidate.code }}）</li></ul>
      </template>
      <p v-else-if="result">暂时没有找到匹配的已通过知识。</p>
    </div>
  </details>
</template>

<style scoped>
.resolver-panel{padding:1rem;border:1px solid var(--border-color,#d8dee8);border-radius:1rem;background:#fff}.resolver-panel summary{font-weight:700;cursor:pointer}.resolver-form{display:grid;grid-template-columns:minmax(0,2fr) minmax(8rem,1fr) auto;align-items:end;gap:1rem}.resolver-form label{display:grid;gap:.4rem}.resolver-result{margin-top:1rem}@media(max-width:650px){.resolver-form{grid-template-columns:1fr}}
</style>
