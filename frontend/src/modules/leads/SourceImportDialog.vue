<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue"
import { useQueryClient } from "@tanstack/vue-query"

import { ApiError } from "../../api/client"
import OperationModal from "../../shared/components/OperationModal.vue"
import { uploadAsset } from "../assets/api"
import {
  createIngestionBatch,
  getJob,
  isActiveImportJob,
  leadKeys,
  previewImport,
  type ImportDraft,
  type Job,
} from "./api"

type ImportMode = ImportDraft["mode"]
type Progress = "idle" | "receiving" | "queued" | "running" | "completed"

const props = defineProps<{ organizationId: string; open: boolean }>()
const emit = defineEmits<{ close: []; completed: [result: { batchId: string; jobId: string }] }>()
const queryClient = useQueryClient()

const sourceUrl = ref("")
const originalText = ref("")
const pastedText = ref("")
const importText = ref("")
const mode = ref<ImportMode>("URL")
const moreWays = ref(false)
const screenshot = ref<File | null>(null)
const screenshotInput = ref<HTMLInputElement | null>(null)
const screenshotObjectUrl = ref("")
const importInput = ref<HTMLInputElement | null>(null)
const alert = ref("")
const recovery = ref<"check" | "screenshot" | "file" | "">("")
const progress = ref<Progress>("idle")
const submitting = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | undefined
let session = 0
let fileRead = 0
let idempotencySignature = ""
let idempotencyKey = ""

const preview = computed(() => {
  const key = "preview"
  if (mode.value === "URL") return previewImport({ mode: "URL", sourceUrl: sourceUrl.value.trim(), originalText: originalText.value.trim(), idempotencyKey: key })
  if (mode.value === "SCREENSHOT") return previewImport({
    mode: "SCREENSHOT", sourceUrl: sourceUrl.value.trim(), originalText: originalText.value.trim(),
    screenshotAssetId: "00000000-0000-0000-0000-000000000001", idempotencyKey: key,
  })
  if (mode.value === "PASTE") return previewImport({ mode: "PASTE", text: pastedText.value, idempotencyKey: key })
  return previewImport({ mode: mode.value, text: importText.value, idempotencyKey: key })
})

const canSubmit = computed(() => preview.value.validRows > 0 && preview.value.invalidRows === 0
  && (mode.value !== "SCREENSHOT" || Boolean(screenshot.value)))
const progressCopy = computed(() => ({
  receiving: "正在接收公开信息…",
  queued: "正在整理公开信息…",
  running: "正在处理公开信息…",
  completed: "已完成公开信息导入。",
}[progress.value] ?? ""))
const visibleModes = computed<ImportMode[]>(() => moreWays.value ? ["URL", "PASTE", "SCREENSHOT", "CSV", "JSON"] : ["URL", "PASTE"])
const tabId = (item: ImportMode) => `source-import-tab-${item.toLowerCase()}`
const isCurrent = (token: number) => props.open && token === session

function freshIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID()
  return `import-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function intent(): string {
  if (mode.value === "URL") return JSON.stringify([mode.value, sourceUrl.value.trim(), originalText.value.trim()])
  if (mode.value === "SCREENSHOT") return JSON.stringify([
    mode.value, sourceUrl.value.trim(), originalText.value.trim(), screenshot.value?.name ?? "",
    screenshot.value?.size ?? 0, screenshot.value?.lastModified ?? 0,
  ])
  return JSON.stringify([mode.value, mode.value === "PASTE" ? pastedText.value : importText.value])
}

function keyForCurrentIntent(): string {
  const current = intent()
  if (idempotencySignature !== current) {
    idempotencySignature = current
    idempotencyKey = freshIdempotencyKey()
  }
  return idempotencyKey
}

function clearPolling(): void {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = undefined
}

function revokeScreenshotUrl(): void {
  if (screenshotObjectUrl.value) URL.revokeObjectURL(screenshotObjectUrl.value)
  screenshotObjectUrl.value = ""
}

function resetTransientState(): void {
  session += 1
  fileRead += 1
  clearPolling()
  revokeScreenshotUrl()
  screenshot.value = null
  importText.value = ""
  if (screenshotInput.value) screenshotInput.value.value = ""
}

function closeDialog(): void {
  resetTransientState()
  emit("close")
}

function selectMode(next: ImportMode): void {
  fileRead += 1
  mode.value = next
  alert.value = ""
  recovery.value = ""
}

async function revealMoreWays(): Promise<void> {
  moreWays.value = true
  await nextTick()
  document.getElementById(tabId("SCREENSHOT"))?.focus()
}

async function onTabKeydown(event: KeyboardEvent, current: ImportMode): Promise<void> {
  const items = visibleModes.value
  const currentIndex = items.indexOf(current)
  let nextIndex = currentIndex
  if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % items.length
  else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + items.length) % items.length
  else if (event.key === "Home") nextIndex = 0
  else if (event.key === "End") nextIndex = items.length - 1
  else return
  event.preventDefault()
  const next = items[nextIndex]
  selectMode(next)
  await nextTick()
  document.getElementById(tabId(next))?.focus()
}

function chooseScreenshot(event: Event): void {
  revokeScreenshotUrl()
  const file = (event.target as HTMLInputElement).files?.[0] ?? null
  screenshot.value = file
  if (file) screenshotObjectUrl.value = URL.createObjectURL(file)
  alert.value = ""
  recovery.value = ""
}

async function chooseImportFile(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  const token = session
  const read = ++fileRead
  const importMode = mode.value
  importText.value = ""
  alert.value = ""
  recovery.value = ""
  if (!file) return
  try {
    const text = await file.text()
    if (!isCurrent(token) || read !== fileRead || mode.value !== importMode) return
    importText.value = text
  } catch {
    if (!isCurrent(token) || read !== fileRead || mode.value !== importMode) return
    alert.value = "文件没有读取成功，请重新选择文件。"
    recovery.value = "file"
  }
}

function clearError(): void {
  alert.value = ""
  recovery.value = ""
}

async function recover(): Promise<void> {
  const action = recovery.value
  clearError()
  await nextTick()
  if (action === "screenshot") screenshotInput.value?.focus()
  else if (action === "file") importInput.value?.focus()
  else document.querySelector<HTMLElement>(".source-import-dialog [aria-invalid='true'], .source-import-dialog input, .source-import-dialog textarea")?.focus()
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.userMessage : "导入没有完成，请检查公开内容后重试。"
}

async function screenshotAssetId(token: number): Promise<string | null> {
  if (!screenshot.value) return null
  try {
    const asset = await uploadAsset({ file: screenshot.value, asset_type: "IMAGE", language: "zh-CN", tags: ["public-signal-import"] })
    return isCurrent(token) ? asset.id : null
  } catch (error) {
    if (!isCurrent(token)) return null
    alert.value = errorMessage(error)
    recovery.value = "screenshot"
    return null
  }
}

async function draftForSubmission(token: number): Promise<ImportDraft | null> {
  const idempotency = keyForCurrentIntent()
  if (mode.value === "URL") return { mode: "URL", sourceUrl: sourceUrl.value.trim(), originalText: originalText.value.trim(), idempotencyKey: idempotency }
  if (mode.value === "PASTE") return { mode: "PASTE", text: pastedText.value, idempotencyKey: idempotency }
  if (mode.value === "CSV" || mode.value === "JSON") return { mode: mode.value, text: importText.value, idempotencyKey: idempotency }
  const assetId = await screenshotAssetId(token)
  if (!assetId || !isCurrent(token)) return null
  return { mode: "SCREENSHOT", sourceUrl: sourceUrl.value.trim(), originalText: originalText.value.trim(), screenshotAssetId: assetId, idempotencyKey: idempotency }
}

function finishJob(job: Job, batchId: string, token: number): void {
  if (!isCurrent(token)) return
  clearPolling()
  if (job.status === "SUCCEEDED") {
    progress.value = "completed"
    emit("completed", { batchId, jobId: job.job_id })
    return
  }
  alert.value = "导入没有完成，请检查公开内容后重试。"
  recovery.value = "check"
}

async function poll(jobId: string, batchId: string, token: number): Promise<void> {
  if (!isCurrent(token)) return
  try {
    const job = await queryClient.fetchQuery({
      queryKey: leadKeys.job(props.organizationId, jobId), queryFn: () => getJob(jobId), retry: false,
    })
    if (!isCurrent(token)) return
    if (job.status === "QUEUED" || job.status === "RETRY_QUEUED") progress.value = "queued"
    else if (job.status === "RUNNING") progress.value = "running"
    if (!isActiveImportJob(job.status)) {
      finishJob(job, batchId, token)
      return
    }
    if (isCurrent(token)) pollTimer = setTimeout(() => { void poll(jobId, batchId, token) }, 1_000)
  } catch (error) {
    if (!isCurrent(token)) return
    clearPolling()
    alert.value = errorMessage(error)
    recovery.value = "check"
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value || submitting.value) return
  const token = ++session
  clearPolling()
  clearError()
  submitting.value = true
  progress.value = "receiving"
  try {
    const draft = await draftForSubmission(token)
    if (!draft || !isCurrent(token)) return
    const accepted = await createIngestionBatch(draft)
    if (!isCurrent(token)) return
    await poll(accepted.job_id, accepted.ingestion_batch_id, token)
  } catch (error) {
    if (!isCurrent(token)) return
    clearPolling()
    alert.value = errorMessage(error)
    recovery.value = "check"
  } finally {
    if (isCurrent(token)) submitting.value = false
  }
}

watch(() => [props.open, props.organizationId] as const, (current, previous) => {
  if (!previous || current[0] !== previous[0] || current[1] !== previous[1]) resetTransientState()
})

onBeforeUnmount(resetTransientState)
</script>

<template>
  <OperationModal v-if="open" title="导入公开信号" title-id="source-import-title" @close="closeDialog">
    <section class="source-import-dialog">
      <header class="dialog-header"><p class="eyebrow">公开信号</p><button type="button" aria-label="关闭" @click="closeDialog">×</button></header>
      <p class="privacy-copy">系统只保存你提供范围内的公开信息，不会自动登录平台或发送消息。</p>
      <p v-if="progressCopy" class="progress" role="status" aria-live="polite">{{ progressCopy }}</p>
      <div v-if="alert" class="form-alert" role="alert"><p>{{ alert }}</p><button type="button" @click="recover">{{ recovery === "screenshot" ? "重新上传截图" : recovery === "file" ? "重新选择文件" : "检查内容后重试" }}</button></div>

      <form novalidate @submit.prevent="submit">
        <div class="mode-tabs" role="tablist" aria-label="导入方式">
          <button v-for="item in visibleModes" :id="tabId(item)" :key="item" role="tab" type="button" :tabindex="mode === item ? 0 : -1" :aria-selected="mode === item" aria-controls="source-import-panel" @click="selectMode(item)" @keydown="onTabKeydown($event, item)">{{ item === "URL" ? "帖子链接" : item === "PASTE" ? "批量粘贴" : item === "SCREENSHOT" ? "截图" : `${item} 文件` }}</button>
        </div>
        <button v-if="!moreWays" class="more-ways" type="button" @click="revealMoreWays">更多导入方式</button>

        <div id="source-import-panel" class="form-fields" role="tabpanel" :aria-labelledby="tabId(mode)">
          <template v-if="mode === 'URL' || mode === 'SCREENSHOT'">
            <label>公开链接<input v-model="sourceUrl" type="url" inputmode="url" autocomplete="url" :aria-invalid="Boolean(sourceUrl && !preview.validRows)" placeholder="https://example.com/post"></label>
            <label>公开原文<textarea v-model="originalText" rows="4" placeholder="仅粘贴公开可见的原文" /></label>
            <template v-if="mode === 'URL'"><p class="example">示例：粘贴一条公开帖子的链接和原文。</p></template>
            <template v-else><label>截图文件<input ref="screenshotInput" type="file" accept="image/*" @change="chooseScreenshot"></label><img v-if="screenshotObjectUrl" :src="screenshotObjectUrl" alt="待导入截图预览"><p class="example">截图会先作为私有素材上传，再与公开链接和原文关联。</p></template>
          </template>
          <template v-else-if="mode === 'PASTE'"><label>公开链接和原文<textarea v-model="pastedText" rows="8" placeholder="https://example.com/post[TAB]公开原文&#10;每行一条" /></label><p class="example">每行使用一个制表符分隔公开链接和原文。</p></template>
          <template v-else><label>{{ mode === 'CSV' ? 'CSV 文件' : 'JSON 文件' }}<input ref="importInput" type="file" :accept="mode === 'CSV' ? '.csv,text/csv' : '.json,application/json'" @change="chooseImportFile"></label><p class="example">文件会以 UTF-8 读取并在提交前校验。</p></template>
        </div>

        <section class="preview" aria-live="polite"><strong>本地预检</strong><span>有效 {{ preview.validRows }} 条</span><span v-if="preview.invalidRows">无效 {{ preview.invalidRows }} 条</span><ul v-if="preview.messages.length"><li v-for="message in preview.messages" :key="`${message.row}-${message.message}`">{{ message.row ? `第 ${message.row} 行：` : "" }}{{ message.message }}</li></ul></section>
        <footer class="dialog-actions"><button type="button" @click="closeDialog">取消</button><button class="primary-action" type="submit" :disabled="!canSubmit || submitting">{{ submitting ? "正在提交…" : "导入公开信号" }}</button></footer>
      </form>
    </section>
  </OperationModal>
</template>

<style scoped>
.source-import-dialog{display:grid;gap:.8rem}.dialog-header,.dialog-actions{display:flex;justify-content:space-between;gap:1rem}.dialog-header .eyebrow{margin:0}.privacy-copy,.example{color:#536273}.progress{padding:.7rem .85rem;border-radius:.7rem;background:#e8f2fb;color:var(--sg-brand,#005ba8);font-weight:700}.form-alert{padding:.85rem;border-radius:.7rem;background:#fff0ed;color:#79291d}.form-alert p{margin-top:0}.mode-tabs{display:flex;gap:.35rem;flex-wrap:wrap;border-bottom:1px solid #d8dee8}.mode-tabs button{padding:.65rem .8rem;border:0;border-bottom:3px solid transparent;background:transparent}.mode-tabs button[aria-selected=true]{border-color:var(--sg-brand,#005ba8);color:var(--sg-brand,#005ba8);font-weight:800}.more-ways{margin:.8rem 0}.form-fields{display:grid;gap:.85rem;margin:1rem 0}.form-fields label{display:grid;gap:.35rem}.form-fields input,.form-fields textarea{box-sizing:border-box;width:100%}.form-fields img{max-width:100%;max-height:16rem;border:1px solid #d8dee8;border-radius:.5rem}.preview{display:grid;gap:.35rem;padding:.85rem;border:1px solid #cdddeb;border-radius:.7rem;background:#f5f9fd}.preview ul{margin:.2rem 0 0;padding-left:1.25rem}.dialog-actions{justify-content:flex-end;flex-wrap:wrap;margin-top:1rem}@media(max-width:600px){.dialog-header{align-items:flex-start}.dialog-actions button{flex:1}.mode-tabs{display:grid;grid-template-columns:1fr 1fr}.mode-tabs button{min-height:2.75rem}}
</style>
