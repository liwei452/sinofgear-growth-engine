<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import {
  growthQueryKeys,
  runAutomaticDiscovery,
  updateAutomaticDiscovery,
  type DiscoverySummary,
} from "./api"

const props = defineProps<{ discovery: DiscoverySummary }>()
const queryClient = useQueryClient()
const localSummary = ref<DiscoverySummary | null>(null)
const actionStatus = ref("")
const actionError = ref("")
const summary = computed(() => localSummary.value ?? props.discovery)

const runMutation = useMutation({
  mutationFn: runAutomaticDiscovery,
  onSuccess: async (result) => {
    actionStatus.value = result.message
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => {
    actionError.value = "自动查找暂时未完成，请稍后重试。"
  },
})

const scheduleMutation = useMutation({
  mutationFn: updateAutomaticDiscovery,
  onSuccess: async (result) => {
    localSummary.value = result
    actionStatus.value = result.schedule_label
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => {
    actionError.value = "自动查找设置暂时无法保存。"
  },
})

function runNow(): void {
  actionError.value = ""
  actionStatus.value = ""
  runMutation.mutate()
}

function changeSchedule(event: Event): void {
  actionError.value = ""
  actionStatus.value = ""
  scheduleMutation.mutate((event.target as HTMLInputElement).checked)
}
</script>

<template>
  <section class="growth-card automatic-discovery" aria-labelledby="automatic-discovery-title">
    <div class="automatic-discovery-main">
      <div class="discovery-icon" aria-hidden="true">AI</div>
      <div>
        <div class="discovery-title-row">
          <h2 id="automatic-discovery-title">自动发现客户</h2>
          <span class="official-source">{{ summary.source_label }}</span>
        </div>
        <p>按 {{ summary.product_scope_label }} 查找新的目标公司与公开采购需求。</p>
        <div class="discovery-sources">
          <span
            v-for="source in summary.available_sources"
            :key="source.code"
            :class="{ pending: source.status !== 'ACTIVE' }"
          >
            {{ source.label }}
            <small>{{ source.status === "ACTIVE" ? "已启用" : "接入密钥后可用" }}</small>
          </span>
        </div>
      </div>
    </div>
    <div class="discovery-controls">
      <label class="discovery-switch">
        <input
          type="checkbox"
          :checked="summary.enabled"
          :disabled="scheduleMutation.isPending.value"
          @change="changeSchedule"
        >
        <span>每天自动查找</span>
      </label>
      <button
        class="button button-primary"
        type="button"
        :disabled="runMutation.isPending.value"
        @click="runNow"
      >
        {{ runMutation.isPending.value ? "正在查找…" : "立即查找" }}
      </button>
    </div>
    <p v-if="summary.last_run && !actionStatus" class="discovery-last-run">
      {{ summary.last_run.message }}
    </p>
    <p v-if="actionStatus" class="approval-status" role="status">{{ actionStatus }}</p>
    <p v-if="actionError" class="manual-import-error" role="alert">{{ actionError }}</p>
    <p class="discovery-safety">
      地图只用于发现目标公司，不代表采购意向；系统不会自动联系客户，所有机会都要先查看证据。
    </p>
  </section>
</template>

<style scoped src="./growth-pages.css"></style>
