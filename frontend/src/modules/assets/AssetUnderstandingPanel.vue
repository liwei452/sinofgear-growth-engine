<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { ApiError } from "../../api/client"
import { getProductAIStatus, type ProductAIStatus } from "../settings/api"
import { getAssetUnderstanding, retryAssetUnderstanding, reviewAssetFact, startAssetUnderstanding, type AssetUnderstanding } from "./api"

const props=defineProps<{assetId:string;productId:string;canManage:boolean}>()
const result=ref<AssetUnderstanding|null>(null),loading=ref(false),message=ref("")
const providerStatus=ref<ProductAIStatus|null>(null),externalTextConsent=ref(false)
const needsConsent=computed(()=>providerStatus.value?.mode==="CONFIGURED_AI")
const prepareDisabled=computed(()=>!props.productId||loading.value||!providerStatus.value||providerStatus.value.mode==="CONFIGURATION_REQUIRED"||(needsConsent.value&&!externalTextConsent.value))
const errorText=(error:unknown)=>error instanceof ApiError?error.userMessage:"资料暂时无法处理，请稍后重试。"
async function prepare(){if(!props.productId||prepareDisabled.value)return;loading.value=true;message.value="";try{result.value=await startAssetUnderstanding(props.assetId,props.productId,externalTextConsent.value)}catch(error){message.value=errorText(error)}finally{loading.value=false}}
async function load(){loading.value=true;message.value="";try{result.value=await getAssetUnderstanding(props.assetId)}catch(error){message.value=errorText(error)}finally{loading.value=false}}
async function retry(){if(needsConsent.value&&!externalTextConsent.value)return;loading.value=true;message.value="";try{result.value=await retryAssetUnderstanding(props.assetId,externalTextConsent.value)}catch(error){message.value=errorText(error)}finally{loading.value=false}}
async function review(id:string,decision:"APPROVE"|"REJECT"){loading.value=true;message.value="";try{const fact=await reviewAssetFact(id,decision);if(result.value)result.value={...result.value,facts:result.value.facts.map(item=>item.id===id?fact:item)}}catch(error){message.value=errorText(error)}finally{loading.value=false}}
const statusText=(status:string)=>({SUGGESTED:"待确认",VERIFIED:"已验证",REJECTED:"已驳回"}[status]??status)
onMounted(async()=>{try{providerStatus.value=await getProductAIStatus()}catch(error){message.value=errorText(error)}})
</script>

<template>
  <section class="understanding" aria-label="资料理解与事实确认">
    <div class="actions">
      <button v-if="canManage" :disabled="prepareDisabled" class="primary-action" @click="prepare">准备产品事实</button>
      <button :disabled="loading" @click="load">查看已有事实</button>
    </div>
    <label v-if="canManage&&needsConsent" class="consent">
      <input v-model="externalTextConsent" type="checkbox">
      我确认本次处理：PDF 文件本身不会上传，但本地提取并裁剪后的有限文本、页码和任务格式会发送给 DeepSeek。
    </label>
    <p v-else-if="providerStatus?.mode==='FAKE_OFFLINE'" class="hint">当前为 Fake / 离线模式，资料文本不会发送给外部模型。</p>
    <p v-else-if="providerStatus?.mode==='CONFIGURATION_REQUIRED'" class="hint">真实 AI 尚未配置，暂时不能发送资料进行理解；可先在设置中心检查状态。</p>
    <p v-if="!productId" class="hint">先选择一个产品，AI 才能把资料整理到正确的事实库。</p>
    <p v-if="message" role="alert">{{ message }}</p>
    <div v-if="result" class="result">
      <div class="result-head"><strong>{{ result.provider_label }}</strong><span class="pill">{{ result.job.status }}</span></div>
      <button v-if="canManage&&result.job.status==='FAILED'" class="primary-action" :disabled="loading||(needsConsent&&!externalTextConsent)" @click="retry">重试解析</button>
      <p class="warning">{{ result.facts.some(fact=>!fact.is_demo) ? "DeepSeek 只生成带原文证据的候选事实；仍须逐项人工确认。" : "这是本地演示提供方；所有事实都必须人工确认。" }} 不会自动发布或联系客户。</p>
      <p v-for="warning in result.warnings" :key="warning" class="hint">{{ warning }}</p>
      <p v-if="!result.facts.length" class="empty">没有生成候选事实。系统不会用文件名或产品名伪装成图片识别结果。</p>
      <article v-for="fact in result.facts" :key="fact.id" class="fact">
        <div class="result-head"><strong>{{ fact.field_name }}：{{ fact.value }}</strong><span class="pill">{{ statusText(fact.review_status) }}</span></div>
        <p v-if="fact.risk_level==='HIGH'" class="risk">高风险事实，必须人工确认</p>
        <p v-if="fact.review_status==='VERIFIED'" class="verified-use">已进入事实库，可供 ICP 与多渠道内容使用</p>
        <p>置信度 {{ Math.round(Number(fact.confidence)*100) }}% · {{ fact.source_page ? `第 ${fact.source_page} 页` : "整份资料" }}</p>
        <blockquote>{{ fact.source_excerpt }}</blockquote>
        <div v-if="canManage&&fact.review_status==='SUGGESTED'" class="actions">
          <button class="primary-action" :disabled="loading" @click="review(fact.id,'APPROVE')">确认写入事实库</button>
          <button :disabled="loading" @click="review(fact.id,'REJECT')">不采用</button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.understanding{margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border-color,#d8dee8)}.actions,.result-head{display:flex;gap:.65rem;align-items:center;justify-content:space-between;flex-wrap:wrap}.consent{display:flex;align-items:flex-start;gap:.55rem;margin-top:.75rem;padding:.7rem;border:1px solid #c8d8ed;border-radius:.65rem;background:#f4f8fd;color:#334e68}.consent input{margin-top:.2rem}.result{display:grid;gap:.75rem;margin-top:.85rem}.warning,.risk{color:#8a4b08;background:#fff7e6;border-radius:.65rem;padding:.65rem}.verified-use{color:#276749;background:#edf9f2;border-radius:.65rem;padding:.55rem}.hint,.empty{color:#657184}.fact{border:1px solid #dbe4ef;border-radius:.8rem;padding:.85rem;background:#f9fbfe}.fact p{margin:.4rem 0}.pill{background:#eaf1fb;color:#245aa5;border-radius:999px;padding:.2rem .55rem;font-size:.8rem}blockquote{margin:.5rem 0;padding:.55rem .7rem;border-left:3px solid #8eb4e8;background:white;color:#42526a}
</style>
