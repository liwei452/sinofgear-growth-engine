<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, ref } from "vue"
import { RouterLink } from "vue-router"

import {
  companyFactsQueryKeys,
  companyFactsQueryOptions,
  type FieldProvenance,
  verifyCompanyFact,
} from "./api"

type FactRow = {
  id: string | null
  name: string
  value: string
  source: string
  verified: boolean
  updated: string
  cost: string
}

const queryClient = useQueryClient()
const factsQuery = useQuery(companyFactsQueryOptions())
const locallyVerified = ref(new Set<string>())
const verificationError = ref("")

const fieldLabels: Record<string, string> = {
  company_name: "公司名称",
  quality_system: "质量体系",
  accuracy_grade: "精度等级",
  lead_time: "标准交付周期",
}

function apiFactRow(fact: FieldProvenance): FactRow {
  const costYuan = fact.source_cost_micros / 1_000_000
  return {
    id: fact.id,
    name: fieldLabels[fact.field_name] ?? fact.field_name,
    value: fact.field_value,
    source: fact.source_label,
    verified: fact.verification_status === "VERIFIED" || locallyVerified.value.has(fact.id),
    updated: new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date(fact.updated_at)),
    cost: costYuan ? `${costYuan.toFixed(2)} 元` : "免费",
  }
}

const facts = computed(() => (factsQuery.data.value ?? [])
  .filter(fact => !fact.is_demo).map(apiFactRow))
const factsReadable = computed(() => !factsQuery.isPending.value && !factsQuery.isError.value)

const verifyMutation = useMutation({
  mutationFn: verifyCompanyFact,
  onSuccess: async (_result, factId) => {
    locallyVerified.value = new Set([...locallyVerified.value, factId])
    await queryClient.invalidateQueries({ queryKey: companyFactsQueryKeys.all })
  },
  onError: () => { verificationError.value = "公司事实暂时无法确认，请稍后重试。" },
})

async function verify(fact: FactRow): Promise<void> {
  if (!fact.id) return
  verificationError.value = ""
  await verifyMutation.mutateAsync(fact.id).catch(() => undefined)
}
</script>

<template>
  <div class="growth-page">
    <header class="growth-hero"><div><p class="eyebrow">公司资料</p><h1>我的公司</h1><p>AI 只使用已确认事实生成推广内容；不确定字段会要求人工确认。</p></div><span class="fake-label">{{ factsQuery.isError.value ? "事实暂时无法读取" : facts.length ? "事实库记录" : "尚无事实记录" }}</span></header>
    <section class="growth-card" role="region" aria-label="公司事实">
      <div class="growth-heading"><div><h2>AI 已理解的事实</h2><p>每个字段显示来源、更新时间和可能的来源成本。</p></div></div>
      <p v-if="factsQuery.isPending.value" class="approval-status">正在读取公司事实。</p>
      <section v-else-if="factsQuery.isError.value" role="alert" class="approval-status"><p>公司事实暂时无法读取；不会将旧缓存或空白当作当前事实。</p><button class="button button-secondary" type="button" @click="factsQuery.refetch()">重新读取公司事实</button></section>
      <div v-else-if="factsReadable" class="fact-table-wrap">
        <table>
          <thead><tr><th>公司事实</th><th>字段来源</th><th>确认状态</th><th>更新时间</th><th>来源成本</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="fact in facts" :key="fact.id ?? fact.name">
              <td><strong>{{ fact.value }}</strong><small>{{ fact.name }}</small></td>
              <td>{{ fact.source }}</td>
              <td><span :class="fact.verified ? 'verified' : 'pending'">{{ fact.verified ? "已确认" : "待确认" }}</span></td>
              <td>{{ fact.updated }}</td><td>{{ fact.cost }}</td>
              <td><button v-if="fact.id && !fact.verified" class="button button-secondary" type="button" :disabled="verifyMutation.isPending.value" :aria-label="`确认 ${fact.value}`" @click="verify(fact)">确认</button><span v-else>—</span></td>
            </tr>
            <tr v-if="!facts.length"><td colspan="6">还没有已保存的公司事实</td></tr>
          </tbody>
        </table>
      </div>
      <p v-if="verificationError" role="alert" class="approval-status">{{ verificationError }}</p>
    </section>
    <section class="growth-card suggestions" role="region" aria-label="产品事实"><h2>产品事实</h2><p>产品库中的规格、适配范围和审核状态会在这里作为能力依据使用。</p><RouterLink class="button button-secondary" to="/products">查看产品库</RouterLink></section>
    <section class="growth-card suggestions" role="region" aria-label="素材与资料"><h2>素材与资料</h2><p>上传的资料只会提取为待确认事实；没有保存的资料不会被当作公司能力。</p><RouterLink class="button button-secondary" to="/assets">查看素材与资料</RouterLink></section>
    <section class="growth-card suggestions" role="region" aria-label="内容准备"><h2>内容准备</h2><p>内容需要基于已确认的公司和产品事实；缺少事实时先补充资料。</p><RouterLink class="button button-secondary" to="/content-factory">前往内容与发布</RouterLink></section>
    <section class="growth-card suggestions" role="region" aria-label="渠道准备"><h2>渠道准备</h2><p>渠道是否可用取决于已保存的账户状态；未连接时继续使用人工发布包。</p><RouterLink class="button button-secondary" to="/platform-accounts">查看渠道账户</RouterLink></section>
    <section class="growth-card suggestions"><h2>建议补充</h2><ul><li>可公开的检测设备与报告摘要</li><li>标准交付周期和加急边界</li><li>可公开的包装机械应用案例</li></ul><RouterLink class="button button-primary" to="/assets">上传资料并提取事实</RouterLink></section>
  </div>
</template>
<style scoped src="./growth-pages.css"></style>
