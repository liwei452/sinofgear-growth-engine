<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue"
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { ApiError } from "../../api/client"
import OperationModal from "../../shared/components/OperationModal.vue"
import { currentUserQueryOptions } from "../auth/auth"
import { getProductPage, listProducts, safeProductPageUrl, type Product } from "../products/api"
import AssetUnderstandingPanel from "./AssetUnderstandingPanel.vue"
import { assetKeys, getAssetDownload, getAssetPage, linkAssetProduct, listAssets, resolveAssetDownloadUrl, uploadAsset, type AssetFilters } from "./api"

const client=useQueryClient(),user=useQuery(currentUserQueryOptions())
const type=ref(""),status=ref(""),tag=ref(""),dialog=ref(false),file=ref<File>(),uploadType=ref("IMAGE"),language=ref(""),tags=ref(""),message=ref(""),pageUrl=ref<string|null>(null),productByAsset=ref<Record<string,string>>({}),fileInput=ref<HTMLInputElement|null>(null)
const org=computed(()=>user.data.value?.organization.id??"")
const filters=computed<AssetFilters>(()=>({type:type.value,status:status.value,tag:tag.value}))
const assets=useQuery({queryKey:computed(()=>[...assetKeys.list(org.value,filters.value),pageUrl.value]),queryFn:()=>pageUrl.value?getAssetPage(pageUrl.value):listAssets(filters.value),enabled:computed(()=>Boolean(org.value))})
const canManage=computed(()=>user.data.value?.membership.permissions.includes("assets.manage")??false)
const products=useQuery({queryKey:computed(()=>[...assetKeys.all(org.value),"products","all-active"]),queryFn:async()=>{const all:Product[]=[],visited=new Set<string>();let page=await listProducts({status:"ACTIVE"});all.push(...page.results);while(page.next){const next=safeProductPageUrl(page.next);if(!next||visited.has(next))throw new ApiError(0,"产品分页地址无效。");visited.add(next);page=await getProductPage(next);all.push(...page.results)}return all},enabled:computed(()=>Boolean(org.value)&&canManage.value)})
const upload=useMutation({mutationFn:()=>uploadAsset({file:file.value!,asset_type:uploadType.value,language:language.value,tags:tags.value.split(",")}),onSuccess:async()=>{closeUpload();message.value="素材已上传。";await client.invalidateQueries({queryKey:assetKeys.all(org.value)})},onError:async()=>{await nextTick();fileInput.value?.focus()}})
const uploadError=computed(()=>upload.error.value instanceof ApiError?(upload.error.value.fieldErrors?.file?.[0]??upload.error.value.userMessage):"素材上传失败，请检查后重试。")
const link=useMutation({mutationFn:({assetId,productId}:{assetId:string;productId:string})=>linkAssetProduct(assetId,productId),onSuccess:async()=>{message.value="产品已关联。";await client.invalidateQueries({queryKey:assetKeys.all(org.value)})}})
const error=(value:unknown)=>value instanceof ApiError?value.userMessage:"素材暂时无法加载，请稍后重试。"
function pick(event:Event){
  const selected=(event.target as HTMLInputElement).files?.[0]
  file.value=selected
  if(!selected)return
  const mimeType={"application/pdf":"DOCUMENT","video/mp4":"VIDEO","image/jpeg":"IMAGE","image/png":"IMAGE","image/webp":"IMAGE"}[selected.type]
  if(mimeType)uploadType.value=mimeType
  else if(selected.name.toLocaleLowerCase().endsWith(".pdf"))uploadType.value="DOCUMENT"
}
function resetPage(){pageUrl.value=null}
function clearFilters(){type.value="";status.value="";tag.value="";resetPage()}
function closeUpload(){dialog.value=false;file.value=undefined;uploadType.value="IMAGE";language.value="";tags.value=""}
const selectedProduct=(asset:{id:string;products?:Array<{id:string}>})=>productByAsset.value[asset.id]||asset.products?.[0]?.id||""
const allowedDownloadOrigins=computed(()=>[window.location.origin,...String(import.meta.env.VITE_ASSET_DOWNLOAD_ORIGINS??"").split(",").map(value=>value.trim()).filter(Boolean)])
async function download(id:string){try{const result=await getAssetDownload(id);const url=resolveAssetDownloadUrl(result,allowedDownloadOrigins.value);window.open(url.href,"_blank","noopener,noreferrer")}catch{message.value="下载地址不安全或已失效，请重试。"}}
watch([org,type,status,tag],resetPage)
</script>

<template>
  <main class="page-stack">
    <header class="workspace-head">
      <div><p class="eyebrow">可复用素材</p><h1>素材库</h1><p>上传产品资料，让 AI 整理候选事实，再由你确认写入事实库。</p></div>
      <button v-if="canManage" class="primary-action" @click="dialog=true">上传素材</button>
    </header>
    <p v-if="message" role="status">{{ message }}</p>
    <section class="filters" aria-label="素材筛选">
      <label>类型<select v-model="type" @change="resetPage"><option value="">全部</option><option>IMAGE</option><option>VIDEO</option><option>DOCUMENT</option></select></label>
      <label>状态<select v-model="status" @change="resetPage"><option value="">全部</option><option>ACTIVE</option><option>ARCHIVED</option></select></label>
      <label>标签<input v-model="tag" placeholder="例如 product" @input="resetPage"></label>
      <button v-if="type||status||tag" @click="clearFilters">清除筛选</button>
    </section>
    <p v-if="assets.isPending.value" role="status">正在加载素材…</p>
    <section v-else-if="assets.isError.value" role="alert" class="panel"><h2>素材没有加载成功</h2><p>{{ error(assets.error.value) }}</p><button @click="assets.refetch()">重新加载素材</button></section>
    <section v-else-if="!assets.data.value?.results.length" class="panel"><h2>还没有符合条件的素材</h2><p>调整筛选条件，或上传第一份素材。</p></section>
    <section v-else class="cards" aria-label="素材列表">
      <article v-for="asset in assets.data.value?.results" :key="asset.id" class="panel">
        <div class="card-head"><div><h2>{{ asset.original_filename }}</h2><p>{{ asset.asset_type }} · {{ asset.mime_type }} · {{ asset.size_bytes }} B</p></div><span class="pill">{{ asset.status }}</span></div>
        <p v-if="asset.tags?.length">标签：{{ asset.tags.join('、') }}</p>
        <p>关联产品：{{ asset.products?.map(product=>product.name_en).join('、')||'暂无' }}</p>
        <div v-if="canManage" class="actions">
          <label>整理到产品<select v-model="productByAsset[asset.id]"><option value="">请选择</option><option v-for="product in products.data.value" :key="product.id" :value="product.id">{{ product.name_zh||product.name_en }}</option></select></label>
          <button :disabled="!productByAsset[asset.id]" @click="link.mutate({assetId:asset.id,productId:productByAsset[asset.id]})">关联</button>
        </div>
        <div class="actions"><button @click="download(asset.id)">安全下载</button></div>
        <AssetUnderstandingPanel :asset-id="asset.id" :product-id="selectedProduct(asset)" :can-manage="canManage" />
      </article>
      <nav class="actions" aria-label="素材分页"><button :disabled="!assets.data.value?.previous" @click="pageUrl=assets.data.value?.previous??null">上一页</button><button :disabled="!assets.data.value?.next" @click="pageUrl=assets.data.value?.next??null">下一页</button></nav>
    </section>
    <OperationModal v-if="dialog" title="上传素材" title-id="upload-title" @close="closeUpload">
      <form class="modal" @submit.prevent="upload.mutate()"><label>文件<input ref="fileInput" required type="file" accept="application/pdf,image/jpeg,image/png,image/webp,video/mp4" @change="pick"></label><label>素材类型<select v-model="uploadType"><option>IMAGE</option><option>VIDEO</option><option>DOCUMENT</option></select></label><label>语言<input v-model="language" placeholder="zh-CN"></label><label>标签（逗号分隔）<input v-model="tags"></label><p v-if="upload.isError.value" role="alert">{{ uploadError }}</p><div class="actions"><button type="button" @click="closeUpload">取消</button><button class="primary-action" :disabled="!file||upload.isPending.value">上传</button></div></form>
    </OperationModal>
  </main>
</template>

<style scoped>
.workspace-head,.card-head,.actions{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start}.filters{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}.filters label,.modal label{display:grid;gap:.35rem}.cards{display:grid;gap:1rem}.panel,.filters{padding:1.1rem;border:1px solid var(--border-color,#d8dee8);border-radius:1rem;background:white}.pill{background:#eef3f8;padding:.25rem .6rem;border-radius:999px}.modal{display:grid;gap:1rem}.actions{justify-content:flex-end}@media(max-width:700px){.workspace-head{display:grid}.filters{grid-template-columns:1fr}}
</style>
