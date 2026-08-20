<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, ref } from "vue"
import { useRouter } from "vue-router"

import { executeWorkItemAction, workItemsQueryOptions, type WorkItem } from "./api"
import WorkItemCard from "./WorkItemCard.vue"

const queryClient = useQueryClient()
const router = useRouter()
const itemsQuery = useQuery(workItemsQueryOptions())

const items = computed(() => itemsQuery.data.value ?? [])
const completionMessage = ref("")

const actionMutation = useMutation({
  mutationFn: (item: WorkItem) => executeWorkItemAction(item),
  onSuccess: async () => {
    completionMessage.value = "已完成；相关任务和机会状态已更新。"
    await nextTick()
    await queryClient.invalidateQueries({ queryKey: ["growth", "work-items"] })
    await queryClient.invalidateQueries({ queryKey: ["growth", "agent-runs"] })
    await queryClient.invalidateQueries({ queryKey: ["growth", "missions"] })
  },
})

function runAction(item: WorkItem): void {
  if (item.action_type === "OPEN_SETTINGS") {
    void router.push("/settings")
    return
  }
  if (item.action_type === "OPEN_CUSTOMER") {
    void router.push("/opportunities")
    return
  }
  actionMutation.mutate(item)
}
</script>

<template>
  <section class="inbox" aria-labelledby="today-inbox-title">
    <p v-if="completionMessage" class="sr-only" aria-live="polite">{{ completionMessage }}</p>
    <header>
      <h2 id="today-inbox-title">今日待办</h2>
      <span>{{ items.length }} 项</span>
    </header>
    <p v-if="itemsQuery.isLoading.value" class="empty">正在读取今日待办…</p>
    <p v-else-if="itemsQuery.isError.value" class="empty error" role="alert">今日待办暂时无法读取。</p>
    <div v-else-if="items.length" class="inbox-list">
      <WorkItemCard
        v-for="item in items"
        :key="item.id"
        :item="item"
        :busy="actionMutation.isPending.value"
        @action="runAction"
      />
    </div>
    <div v-else class="empty">
      <strong>今天没有需要人工处理的事项</strong>
      <RouterLink to="/missions">查看运行中的增长任务</RouterLink>
    </div>
  </section>
</template>

<style scoped>
.inbox { display: grid; gap: 12px; }
.inbox > header { display: flex; align-items: center; justify-content: space-between; }
.inbox > header h2 { margin: 0; font-size: 1.05rem; }
.inbox > header span { color: var(--sg-muted); font-size: .7rem; }
.inbox-list { display: grid; gap: 10px; }
.empty { display: grid; justify-items: start; gap: 8px; margin: 0; border: 1px dashed var(--sg-line); border-radius: 12px; padding: 18px; color: var(--sg-muted); }
.empty strong { color: var(--sg-ink); }
.empty a { color: var(--sg-brand); }
.error { color: var(--sg-danger); }
</style>
