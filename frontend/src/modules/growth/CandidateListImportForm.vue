<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query"
import { ref } from "vue"

import { growthQueryKeys, importCandidateList } from "./api"

const props = withDefaults(defineProps<{ open?: boolean; marketName?: string }>(), {
  open: false,
  marketName: "",
})

const queryClient = useQueryClient()
const content = ref("")
const importFormat = ref<"CSV" | "JSON">("CSV")
const sourceOwner = ref("")
const licenseContract = ref("")
const retentionDays = ref(90)
const redistributionAllowed = ref(false)
const fileName = ref("")
const status = ref("")
const error = ref("")

const mutation = useMutation({
  mutationFn: importCandidateList,
  onSuccess: async (result) => {
    status.value = `已加入 ${result.created_count} 家待核实候选；${result.duplicate_count} 条重复，${result.invalid_count} 条无效。`
    await queryClient.invalidateQueries({ queryKey: growthQueryKeys.workspace })
  },
  onError: () => {
    error.value = "名单暂时无法导入，请检查格式、许可信息和网址。"
  },
})

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.addEventListener("load", () => resolve(String(reader.result ?? "")))
    reader.addEventListener("error", () => reject(reader.error ?? new Error("File read failed")))
    reader.readAsText(file)
  })
}

async function selectFile(event: Event): Promise<void> {
  status.value = ""
  error.value = ""
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const lowerName = file.name.toLowerCase()
  if (!lowerName.endsWith(".csv") && !lowerName.endsWith(".json")) {
    error.value = "只支持 CSV 或 JSON 文件。"
    return
  }
  importFormat.value = lowerName.endsWith(".json") ? "JSON" : "CSV"
  fileName.value = file.name
  try {
    content.value = await readFile(file)
  } catch {
    error.value = "无法读取这个文件，请重新选择。"
  }
}

async function submit(): Promise<void> {
  status.value = ""
  error.value = ""
  if (!content.value) {
    error.value = "请先选择 CSV 或 JSON 文件。"
    return
  }
  await mutation.mutateAsync({
    format: importFormat.value,
    content: content.value,
    source_owner: sourceOwner.value,
    license_contract: licenseContract.value,
    retention_days: retentionDays.value,
    redistribution_allowed: redistributionAllowed.value,
  }).catch(() => undefined)
}
</script>

<template>
  <details class="growth-card candidate-list-import" :open="props.open">
    <summary>导入许可客户名单</summary>
    <p>CSV/JSON 最多 200 家。先进入候选区，核实公司与来源后才会成为客户机会。</p>
    <p v-if="props.marketName" class="market-import-context">正在准备 {{ props.marketName }} 市场候选公司；当前没有真实连接器时，请导入有许可的名单。</p>
    <form @submit.prevent="submit">
      <label>
        CSV 或 JSON 文件
        <input type="file" accept=".csv,.json,text/csv,application/json" @change="selectFile">
        <small v-if="fileName">已选择：{{ fileName }}</small>
      </label>
      <label>
        数据来源方
        <input v-model.trim="sourceOwner" required maxlength="255" placeholder="例如：已授权数据供应商">
      </label>
      <label>
        许可或合同名称
        <input v-model.trim="licenseContract" required maxlength="255" placeholder="例如：内部获客使用许可">
      </label>
      <label>
        保留天数
        <input v-model.number="retentionDays" type="number" min="1" max="3650" required>
      </label>
      <label class="candidate-redistribution">
        <input v-model="redistributionAllowed" type="checkbox">
        合同允许再次分发这些数据
      </label>
      <button class="button button-secondary" type="submit" :disabled="mutation.isPending.value">
        {{ mutation.isPending.value ? "正在导入…" : "导入为待核实候选" }}
      </button>
    </form>
    <p class="candidate-import-safety">不会自动生成联系草稿，也不会联系客户。</p>
    <p v-if="status" class="approval-status" role="status">{{ status }}</p>
    <p v-if="error" class="manual-import-error" role="alert">{{ error }}</p>
  </details>
</template>

<style scoped src="./growth-pages.css"></style>
<style scoped>.market-import-context { color: #24516f !important; font-weight: 700; }</style>
