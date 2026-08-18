<script setup lang="ts">
import { useMutation, useQuery } from "@tanstack/vue-query"
import { computed, ref } from "vue"

import { apiRequest } from "../../api/client"
import { createMission, type MissionCreateInput } from "./api"

const emit = defineEmits<{ cancel: []; created: [] }>()

const title = ref("")
const objective = ref("")
const countries = ref("")
const industries = ref("")
const customerProfile = ref("")
const primaryProductId = ref("")
const startDate = ref("")
const endDate = ref("")
const accountTarget = ref(100)
const replyTarget = ref(20)
const rfqTarget = ref(5)
const budgetMicros = ref(0)
const channels = ref("LINKEDIN, EMAIL")
const errorMessage = ref("")

const productsQuery = useQuery({
  queryKey: ["products", "mission-select"],
  queryFn: async () => {
    const result = await apiRequest<{ results: Array<{ id: string; name_en: string }> }>(
      "/api/v1/products",
    )
    return result?.results ?? []
  },
  staleTime: 60_000,
})

const canSubmit = computed(() => (
  title.value.trim()
  && objective.value.trim()
  && countries.value.trim()
  && industries.value.trim()
  && primaryProductId.value
  && startDate.value
  && endDate.value
))

function splitList(value: string): string[] {
  return value.split(",").map(item => item.trim()).filter(Boolean)
}

const createMutation = useMutation({
  mutationFn: () => {
    const input: MissionCreateInput = {
      title: title.value.trim(),
      objective: objective.value.trim(),
      target_countries: splitList(countries.value),
      target_industries: splitList(industries.value),
      customer_profile: customerProfile.value.trim(),
      primary_product_id: primaryProductId.value,
      start_date: startDate.value,
      end_date: endDate.value,
      target_account_count: Number(accountTarget.value),
      target_reply_count: Number(replyTarget.value),
      target_rfq_count: Number(rfqTarget.value),
      budget_micros: Number(budgetMicros.value),
      allowed_channels: splitList(channels.value),
    }
    return createMission(input)
  },
  onSuccess: () => emit("created"),
  onError: (error) => {
    errorMessage.value = error instanceof Error ? error.message : "增长任务创建失败。"
  },
})
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @click.self="emit('cancel')">
    <section class="create-dialog" role="dialog" aria-modal="true" aria-labelledby="create-mission-title">
      <h2 id="create-mission-title">创建增长任务</h2>
      <p class="hint">目标市场、目标客户、主推产品与目标、周期与指标、渠道与预算。</p>

      <div class="form-grid">
        <label>
          任务名称
          <input v-model="title" type="text" />
        </label>
        <label>
          任务目标
          <input v-model="objective" type="text" />
        </label>
        <label>
          目标国家（逗号分隔）
          <input v-model="countries" type="text" placeholder="ZA, DE" />
        </label>
        <label>
          目标行业（逗号分隔）
          <input v-model="industries" type="text" placeholder="mining equipment" />
        </label>
        <label>
          客户画像
          <input v-model="customerProfile" type="text" />
        </label>
        <label>
          主推产品
          <select v-model="primaryProductId">
            <option value="" disabled>选择产品</option>
            <option v-for="product in productsQuery.data.value ?? []" :key="product.id" :value="product.id">
              {{ product.name_en }}
            </option>
          </select>
        </label>
        <label>
          开始日期
          <input v-model="startDate" type="date" />
        </label>
        <label>
          结束日期
          <input v-model="endDate" type="date" />
        </label>
        <label>
          目标企业数
          <input v-model.number="accountTarget" type="number" min="0" />
        </label>
        <label>
          目标回复数
          <input v-model.number="replyTarget" type="number" min="0" />
        </label>
        <label>
          目标 RFQ 数
          <input v-model.number="rfqTarget" type="number" min="0" />
        </label>
        <label>
          预算（微元）
          <input v-model.number="budgetMicros" type="number" min="0" />
        </label>
        <label class="wide">
          可用渠道（逗号分隔）
          <input v-model="channels" type="text" placeholder="EMAIL, LINKEDIN" />
        </label>
      </div>

      <p v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>

      <div class="dialog-actions">
        <button class="button button-quiet" type="button" @click="emit('cancel')">取消</button>
        <button
          class="button button-primary"
          type="button"
          :disabled="!canSubmit || createMutation.isPending.value"
          @click="createMutation.mutate()"
        >
          {{ createMutation.isPending.value ? "正在创建…" : "创建任务" }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dialog-backdrop { position: fixed; z-index: 60; inset: 0; display: grid; place-items: center; background: rgb(16 42 86 / 34%); padding: 18px; }
.create-dialog { display: grid; width: min(720px, 100%); gap: 14px; border-radius: 20px; background: #fff; padding: 24px; box-shadow: 0 24px 70px rgb(16 42 86 / 24%); max-height: 92vh; overflow: auto; }
.create-dialog h2, .create-dialog p { margin: 0; }
.hint { color: var(--sg-muted); font-size: .78rem; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-grid label { display: grid; gap: 5px; color: var(--sg-ink); font-size: .74rem; }
.form-grid input, .form-grid select { width: 100%; box-sizing: border-box; border: 1px solid #d7e2f0; border-radius: 9px; padding: 8px 9px; font: inherit; }
.form-grid .wide { grid-column: 1 / -1; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
.error { color: var(--sg-danger); font-size: .76rem; }
</style>
