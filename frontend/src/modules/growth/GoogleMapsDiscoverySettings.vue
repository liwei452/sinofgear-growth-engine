<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref, watch } from "vue"

import {
  getGoogleMapsDiscoveryConfig,
  runGoogleMapsDiscovery,
  updateGoogleMapsDiscoveryConfig,
} from "./mapsApi"

const queryClient = useQueryClient()

const configQuery = useQuery({
  queryKey: ["growth", "maps-discovery-config"],
  queryFn: getGoogleMapsDiscoveryConfig,
})

const apiKey = ref("")
const enabled = ref(false)
const dailyQuota = ref(500)
const scheduleTime = ref("02:00")
const saving = ref(false)
const running = ref(false)
const saveError = ref("")
const runMessage = ref("")

watch(
  () => configQuery.data.value,
  (config) => {
    if (!config) return
    enabled.value = config.enabled
    dailyQuota.value = config.daily_quota
    scheduleTime.value = config.schedule_time
  },
)

const apiKeyConfigured = computed(() => configQuery.data.value?.api_key_configured ?? false)
const citiesLabel = computed(() => (
  configQuery.data.value?.cities ?? []
).map((city) => `${city.name} (${city.country_code})`).join("、"))
const keywordsLabel = computed(() => (configQuery.data.value?.keywords ?? []).join("、"))

async function save() {
  saveError.value = ""
  saving.value = true
  try {
    await updateGoogleMapsDiscoveryConfig({
      api_key: apiKey.value.trim() || undefined,
      enabled: enabled.value,
      daily_quota: dailyQuota.value,
      schedule_time: scheduleTime.value,
    })
    apiKey.value = ""
    await queryClient.invalidateQueries({ queryKey: ["growth", "maps-discovery-config"] })
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : "保存失败。"
  } finally {
    saving.value = false
  }
}

async function run() {
  runMessage.value = ""
  running.value = true
  try {
    const result = await runGoogleMapsDiscovery()
    runMessage.value = `本次完成：发现 ${result.fetched_count} 家，新增 ${result.created_count} 家，去重 ${result.duplicate_count} 家。`
    await queryClient.invalidateQueries({ queryKey: ["growth", "maps-discovery-config"] })
  } catch (error) {
    runMessage.value = error instanceof Error ? error.message : "运行失败。"
  } finally {
    running.value = false
  }
}
</script>

<template>
  <main class="maps-settings">
    <header class="maps-heading">
      <div>
        <p class="eyebrow">获客与市场</p>
        <h1>谷歌地图自动获客</h1>
        <p>只需填写一个 API Key，系统就会每天按「城市 × 行业关键词」自动发现海外企业并去重。</p>
      </div>
    </header>

    <section class="card">
      <h2>连接 Google Maps</h2>
      <p class="hint">
        系统只通过官方 Places API 获取公开企业信息，不会抓取网页或模拟点击。密钥保存后不会回显。
      </p>

      <label class="field">
        <span>Google Maps API Key</span>
        <input
          v-model="apiKey"
          type="password"
          autocomplete="off"
          :placeholder="apiKeyConfigured ? '已保存（留空则保持不变）' : '粘贴你的 Google Maps API Key'"
        />
      </label>

      <label class="check">
        <input v-model="enabled" type="checkbox" />
        <span>开启每天自动发现</span>
      </label>

      <div class="row">
        <label class="field">
          <span>每日最多发现</span>
          <input v-model.number="dailyQuota" type="number" min="1" max="5000" />
        </label>
        <label class="field">
          <span>每天执行时间</span>
          <input v-model="scheduleTime" type="text" inputmode="numeric" maxlength="5" placeholder="02:00" />
        </label>
      </div>

      <div class="defaults">
        <p><strong>已覆盖城市：</strong>{{ citiesLabel || "正在读取默认城市…" }}</p>
        <p><strong>行业关键词：</strong>{{ keywordsLabel || "正在读取默认关键词…" }}</p>
      </div>

      <p v-if="saveError" class="error" role="alert">{{ saveError }}</p>
      <button class="primary" :disabled="saving" @click="save">
        {{ saving ? "保存中…" : "保存并启用" }}
      </button>
    </section>

    <section class="card">
      <h2>手动运行一次</h2>
      <p class="hint">通常不需要手动操作；这里用于保存后立即验证一次。</p>
      <button class="secondary" :disabled="running" @click="run">
        {{ running ? "运行中…" : "立即发现一次" }}
      </button>
      <p v-if="runMessage" class="run-result" role="status">{{ runMessage }}</p>
    </section>
  </main>
</template>

<style scoped>
.maps-settings { display: grid; gap: 18px; max-width: 720px; }
.maps-heading h1 { margin: 3px 0 8px; }
.maps-heading p { margin: 0; color: var(--sg-muted); }
.card { display: grid; gap: 14px; border: 1px solid var(--sg-line); border-radius: 14px; background: #fff; padding: 20px; }
.card h2 { margin: 0; font-size: 1.02rem; }
.hint { margin: 0; color: var(--sg-muted); font-size: .82rem; line-height: 1.55; }
.field { display: grid; gap: 6px; font-size: .82rem; color: var(--sg-ink); }
.field input {
  width: 100%; box-sizing: border-box; border: 1px solid var(--sg-line); border-radius: 9px;
  padding: 9px 11px; font: inherit; background: #fbfcfe;
}
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.check { display: flex; align-items: center; gap: 8px; font-size: .86rem; }
.defaults { display: grid; gap: 6px; color: var(--sg-muted); font-size: .8rem; line-height: 1.55; }
.defaults strong { color: var(--sg-ink); }
.error, .run-result { margin: 0; font-size: .82rem; }
.error { color: var(--sg-danger); }
.run-result { color: var(--sg-brand); }
.primary, .secondary {
  border: 0; cursor: pointer; border-radius: 9px; padding: 10px 16px; font: inherit; font-weight: 700;
}
.primary { background: var(--sg-brand); color: #fff; }
.secondary { background: var(--sg-brand-soft); color: var(--sg-brand); }
.primary:disabled, .secondary:disabled { opacity: .55; cursor: not-allowed; }
@media (max-width: 640px) { .row { grid-template-columns: 1fr; } }
</style>
