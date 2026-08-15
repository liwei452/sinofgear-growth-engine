<script setup lang="ts">
import { computed, ref } from "vue"
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { currentUserQueryOptions } from "../auth/auth"
import { useQuery as useUserQuery } from "@tanstack/vue-query"
import {
  contentQueryKeys, listBriefs, listMasterContents, restoreBrief, restoreMasterContent,
} from "./api"

const emit = defineEmits<{ restored: [] }>()
const client = useQueryClient()
const user = useUserQuery(currentUserQueryOptions())
const org = computed(() => user.data.value?.organization.id ?? "")
const permissions = computed(() => user.data.value?.membership.permissions ?? [])
const canRestoreBrief = computed(() => permissions.value.includes("campaigns.manage"))
const canRestoreMaster = computed(() => permissions.value.includes("content.review"))
const open = ref(false)
const busy = ref("")
const message = ref("")
const briefs = useQuery({
  queryKey: computed(() => [...contentQueryKeys.briefs(org.value), "trash"]),
  queryFn: () => listBriefs({ status: "ARCHIVED" }), enabled: computed(() => open.value && Boolean(org.value)),
})
const masters = useQuery({
  queryKey: computed(() => contentQueryKeys.masterContents(org.value, { status: "ARCHIVED" })),
  queryFn: () => listMasterContents({ status: "ARCHIVED" }), enabled: computed(() => open.value && Boolean(org.value)),
})
async function restore(kind: "brief" | "master", id: string) {
  busy.value = id
  message.value = ""
  try {
    if (kind === "brief") await restoreBrief(id)
    else await restoreMasterContent(id)
    await client.invalidateQueries({ queryKey: contentQueryKeys.all(org.value) })
    message.value = "已恢复，原始文件、事实和审核记录均保留。"
    emit("restored")
  } finally { busy.value = "" }
}
</script>

<template>
  <section class="trash-panel">
    <button type="button" @click="open = !open">{{ open ? "收起回收站" : "查看回收站" }}</button>
    <div v-if="open" class="trash-body">
      <h2>回收站</h2>
      <p>这里只做可恢复归档，不会删除素材、事实、AI 结果或审核历史。</p>
      <p v-if="message" role="status">{{ message }}</p>
      <p v-if="briefs.isPending.value || masters.isPending.value" role="status">正在加载回收站…</p>
      <div v-else-if="!(briefs.data.value?.results.length || masters.data.value?.results.length)" class="empty">回收站为空。</div>
      <article v-for="item in briefs.data.value?.results ?? []" :key="item.id">
        <div><strong>内容任务</strong><span>{{ item.target_country || "未填写市场" }} · {{ item.language || "未填写语言" }}</span></div>
        <button v-if="canRestoreBrief" type="button" :disabled="busy === item.id" @click="restore('brief', item.id)">恢复</button>
      </article>
      <article v-for="item in masters.data.value?.results ?? []" :key="item.id">
        <div><strong>{{ item.payload.title }}</strong><span>AI 生成内容 · 第 {{ item.version }} 版</span></div>
        <button v-if="canRestoreMaster" type="button" :disabled="busy === item.id" @click="restore('master', item.id)">恢复</button>
      </article>
    </div>
  </section>
</template>

<style scoped>
.trash-panel{display:grid;gap:.75rem}.trash-panel>button{justify-self:start}.trash-body{display:grid;gap:.75rem;padding:1rem;border:1px solid #d8dee8;border-radius:1rem;background:#fff}.trash-body article{display:flex;justify-content:space-between;gap:1rem;align-items:center;padding:.75rem;border-top:1px solid #e7ebf0}.trash-body article div{display:grid;gap:.25rem}.trash-body span,.empty{color:#667085}
</style>
