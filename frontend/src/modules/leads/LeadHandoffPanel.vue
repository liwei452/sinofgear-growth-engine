<script setup lang="ts">
import { ref } from "vue"

import type { LeadCandidateDetail } from "./api"
import { downloadLeadCsv, downloadLeadJson } from "./export"

const props = defineProps<{
  detail: LeadCandidateDetail
  canHandoff: boolean
  connectorConfigured: boolean
}>()
const emit = defineEmits<{
  close: []
  handoff: [detail: LeadCandidateDetail]
}>()
const notice = ref(props.connectorConfigured ? "" : "CRM 尚未配置，当前不会发送客户资料。")

function requestHandoff(): void {
  if (!props.canHandoff) return
  if (!props.connectorConfigured) {
    notice.value = "CRM 尚未配置，当前不会发送客户资料。"
    return
  }
  emit("handoff", props.detail)
}
</script>

<template>
  <section class="handoff-panel" aria-labelledby="lead-handoff-title">
    <h2 id="lead-handoff-title" tabindex="-1">CRM 与导出</h2>
    <p>导出内容包含当前判断及其公开来源证据，便于人工核对后再录入客户系统。</p>
    <p v-if="notice" role="status" class="connector-notice">{{ notice }}</p>
    <p v-if="!canHandoff" role="alert">当前账号没有交接客户资料的权限。</p>
    <div class="handoff-actions">
      <button class="primary-action" type="button" :disabled="!canHandoff" @click="requestHandoff">交给 CRM</button>
      <button type="button" :disabled="!canHandoff" @click="downloadLeadJson(detail)">下载 JSON</button>
      <button type="button" :disabled="!canHandoff" @click="downloadLeadCsv(detail)">下载 CSV</button>
    </div>
    <a href="#crm-connector-help">前往高级设置了解接入方式</a>
    <section id="crm-connector-help" class="connector-help" aria-labelledby="connector-help-title">
      <h3 id="connector-help-title">高级设置说明</h3>
      <p>当前版本没有可用的 CRM 连接器设置。后端连接器能力验证通过前，只能下载本地文件，再由有权限的同事人工录入。</p>
    </section>
    <button type="button" class="close-action" @click="emit('close')">关闭</button>
  </section>
</template>

<style scoped>
.handoff-panel{display:grid;gap:1rem}.handoff-panel p,.connector-help h3{margin:0}.connector-notice,.connector-help{padding:.8rem;border-radius:.7rem;background:#fff7df;color:#704d00}.connector-help{display:grid;gap:.5rem;background:var(--sg-canvas,#f6f8fa);color:inherit}.handoff-actions{display:flex;flex-wrap:wrap;gap:.7rem}.primary-action{border-color:var(--sg-brand,#005ba8);background:var(--sg-brand,#005ba8);color:#fff}.close-action{justify-self:end}@media(max-width:600px){.handoff-actions{display:grid}.handoff-actions button,.close-action{width:100%}}
</style>
