<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"

import { ApiError } from "../../api/client"
import {
  createRecommendation,
  getRecommendation,
  listRecommendations,
  selectRecommendationOption,
  type ContentRecommendation,
  type ContentRecommendationOption,
} from "./api"

const props = defineProps<{ canManage: boolean }>()
const emit = defineEmits<{ (event: "brief-ready", briefId: string): void }>()

const recommendation = ref<ContentRecommendation | null>(null)
const selectedOption = ref<ContentRecommendationOption | null>(null)
const providerLabel = ref("")
const busy = ref(false)
const error = ref("")
let timer: ReturnType<typeof setTimeout> | null = null
let disposed = false

function errorText(value: unknown): string {
  return value instanceof ApiError ? value.userMessage : "AI 推荐没有完成，请稍后重试。"
}

async function refresh(id: string): Promise<void> {
  try {
    const next = await getRecommendation(id)
    if (disposed) return
    recommendation.value = next
    if (["QUEUED", "RUNNING"].includes(next.status)) {
      timer = setTimeout(() => { void refresh(id) }, 1200)
    } else {
      busy.value = false
      if (next.status === "FAILED") error.value = "AI 推荐没有完成，可以重新尝试。"
    }
  } catch (value) {
    if (disposed) return
    busy.value = false
    error.value = errorText(value)
  }
}

async function recommend(): Promise<void> {
  if (!props.canManage || busy.value) return
  busy.value = true
  error.value = ""
  selectedOption.value = null
  try {
    const accepted = await createRecommendation()
    providerLabel.value = accepted.generation_label
    await refresh(accepted.recommendation_id)
  } catch (value) {
    busy.value = false
    error.value = errorText(value)
  }
}

function choose(option: ContentRecommendationOption): void {
  selectedOption.value = option
}

async function generateSelected(): Promise<void> {
  if (!recommendation.value || !selectedOption.value || busy.value) return
  busy.value = true
  error.value = ""
  try {
    const selection = await selectRecommendationOption(
      recommendation.value.id, selectedOption.value.id,
    )
    emit("brief-ready", selection.brief_id)
  } catch (value) {
    error.value = errorText(value)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try {
    const page = await listRecommendations()
    if (!disposed && page.results.length) {
      recommendation.value = page.results[0]
      providerLabel.value = page.results[0].provider_mode === "FAKE_OFFLINE"
        ? "Fake / 离线演示推荐" : "已配置真实 AI 推荐"
    }
  } catch {
    // The main action remains available; failures are reported when the user requests AI.
  }
})

onBeforeUnmount(() => {
  disposed = true
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <section class="recommendation-panel" aria-labelledby="recommendation-title">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">AI 先判断，再生成</p>
        <h2 id="recommendation-title">推广方向</h2>
        <p>AI 会根据已确认的产品事实、市场和客户画像推荐三个方向。</p>
      </div>
      <button
        v-if="canManage"
        class="primary-action"
        type="button"
        :disabled="busy"
        @click="recommend"
      >
        {{ busy && !recommendation ? "AI 正在分析…" : "让 AI 推荐推广方向" }}
      </button>
    </div>
    <p v-if="providerLabel" class="provider-label">{{ providerLabel }}</p>
    <p v-if="error" role="alert" class="form-alert">{{ error }}</p>
    <p v-if="recommendation && ['QUEUED', 'RUNNING'].includes(recommendation.status)" role="status">
      AI 正在比较市场、产品和客户画像…
    </p>
    <div v-if="recommendation?.status === 'READY'" class="direction-grid">
      <article
        v-for="option in recommendation.options"
        :key="option.id"
        class="direction-card"
        :class="{ selected: selectedOption?.id === option.id }"
      >
        <p class="direction-meta">{{ option.market_code }} · {{ option.language }} · {{ option.channel_codes.join(' / ') }}</p>
        <h3>{{ option.theme }}</h3>
        <p>{{ option.customer_profile }}</p>
        <p><strong>推荐原因：</strong>{{ option.rationale }}</p>
        <p><strong>事实依据：</strong>{{ option.evidence.length }} 项已确认事实</p>
        <p v-if="option.missing_information.length" class="muted">
          仍需补充：{{ option.missing_information.join('、') }}
        </p>
        <button type="button" :aria-pressed="selectedOption?.id === option.id" @click="choose(option)">
          选择这个方向
        </button>
      </article>
    </div>
    <div v-if="selectedOption" class="selected-action">
      <p>已选择：{{ selectedOption.market_code }} · {{ selectedOption.theme }}</p>
      <button class="primary-action" type="button" :disabled="busy" @click="generateSelected">
        {{ busy ? "正在准备…" : "生成这组内容" }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.recommendation-panel{display:grid;gap:1rem;padding:1.25rem;border:1px solid #d8e4f4;border-radius:1rem;background:#f8fbff}.panel-heading{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start}.panel-heading h2{margin:.2rem 0}.provider-label{width:max-content;padding:.3rem .65rem;border-radius:999px;background:#e8f1ff;color:#174e96;font-weight:700}.direction-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}.direction-card{display:grid;align-content:start;gap:.6rem;padding:1rem;border:1px solid #d8dee8;border-radius:.85rem;background:#fff}.direction-card.selected{border-color:#2167c7;box-shadow:0 0 0 2px rgba(33,103,199,.12)}.direction-card h3,.direction-card p{margin:0}.direction-meta{color:#2167c7;font-weight:700}.selected-action{display:flex;justify-content:space-between;gap:1rem;align-items:center;padding-top:.25rem}.form-alert{padding:.8rem 1rem;border-radius:.75rem;background:#fff0ed;color:#79291d}.muted{color:#667085}@media(max-width:850px){.direction-grid{grid-template-columns:1fr}.panel-heading,.selected-action{display:grid}.panel-heading button,.selected-action button{width:100%}}
</style>
