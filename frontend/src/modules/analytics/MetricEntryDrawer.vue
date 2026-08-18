<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query"
import { nextTick, ref, watch } from "vue"

import { createMetricReceipt, growthQueryKeys } from "../growth/api"

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const queryClient = useQueryClient()
const channel = ref("TIKTOK")
const views = ref(0)
const clicks = ref(0)
const replies = ref(0)
const inquiries = ref(0)
const sourceNote = ref("")
const observedAt = ref("")
const message = ref("")
const closeButton = ref<HTMLButtonElement | null>(null)
const dialog = ref<HTMLElement | null>(null)
let returnFocus: HTMLElement | null = null

watch(() => props.open, async (open) => {
  if (open) {
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    closeButton.value?.focus()
  } else {
    returnFocus?.focus()
    returnFocus = null
  }
})

function onDialogKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault()
    emit("close")
    return
  }
  if (event.key !== "Tab" || !dialog.value) return
  const controls = [...dialog.value.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled])")]
  const first = controls[0]
  const last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

const mutation = useMutation({
  mutationFn: createMetricReceipt,
  onSuccess: async () => {
    message.value = "指标已保存。"
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
    emit("saved")
  },
  onError: () => { message.value = "指标暂时无法保存，请稍后重试。" },
})

function save(): void {
  message.value = ""
  mutation.mutate({
    channel: channel.value,
    is_demo: false,
    payload: {
      views: Number(views.value),
      clicks: Number(clicks.value),
      replies: Number(replies.value),
      inquiries: Number(inquiries.value),
      source_note: sourceNote.value.trim() || "人工回填",
      observed_at: observedAt.value || new Date().toISOString(),
    },
  })
}
</script>

<template>
  <div v-if="open" class="drawer-backdrop" role="presentation" @click.self="emit('close')">
    <aside ref="dialog" class="metric-drawer" role="dialog" aria-modal="true" aria-labelledby="metric-drawer-title" @keydown="onDialogKeydown">
      <header><div><p>VERIFIED ENTRY</p><h2 id="metric-drawer-title">录入渠道结果</h2></div><button ref="closeButton" type="button" aria-label="关闭录入数据" @click="emit('close')">关闭</button></header>
      <p>只录入你已从平台后台核实的结果；系统不会连接真实邮箱或推算缺失数据。</p>
      <form aria-label="手工回填渠道结果" @submit.prevent="save">
        <label>渠道<select v-model="channel"><option value="TIKTOK">TikTok</option><option value="LINKEDIN">LinkedIn</option><option value="INSTAGRAM">Instagram</option><option value="FACEBOOK">Facebook</option><option value="YOUTUBE">YouTube</option></select></label>
        <label>播放或访问<input v-model.number="views" type="number" min="0"></label>
        <label>点击<input v-model.number="clicks" type="number" min="0"></label>
        <label>回复<input v-model.number="replies" type="number" min="0"></label>
        <label>询盘<input v-model.number="inquiries" type="number" min="0"></label>
        <label>数据来源说明<input v-model="sourceNote" maxlength="500" placeholder="例如：平台后台截图，由负责人核对"></label>
        <label>观察时间<input v-model="observedAt" type="datetime-local"></label>
        <button class="button button-primary" type="submit" :disabled="mutation.isPending.value">{{ mutation.isPending.value ? "正在保存…" : "保存回填" }}</button>
        <p v-if="message" role="status">{{ message }}</p>
      </form>
    </aside>
  </div>
</template>

<style scoped>
.drawer-backdrop { position: fixed; z-index: 60; inset: 0; display: flex; justify-content: flex-end; background: rgb(16 42 86 / 30%); }
.metric-drawer { width: min(430px, 100%); overflow: auto; background: #fff; padding: 25px; box-shadow: -18px 0 50px rgb(16 42 86 / 18%); }
.metric-drawer header { display: flex; justify-content: space-between; gap: 12px; }.metric-drawer header p, .metric-drawer h2 { margin: 0; }.metric-drawer header p { color: var(--sg-brand); font-size: .62rem; font-weight: 900; letter-spacing: .1em; }.metric-drawer h2 { margin-top: 4px; }.metric-drawer header button { border: 0; background: transparent; color: var(--sg-muted); cursor: pointer; }.metric-drawer > p { color: var(--sg-muted); font-size: .76rem; line-height: 1.55; }
form { display: grid; gap: 13px; margin-top: 20px; }label { display: grid; gap: 6px; color: var(--sg-ink); font-size: .74rem; font-weight: 800; }input, select { border: 1px solid var(--sg-line); border-radius: 9px; background: #fbfdff; padding: 10px; color: var(--sg-ink); }form p { margin: 0; color: var(--sg-success); font-size: .74rem; }
</style>
