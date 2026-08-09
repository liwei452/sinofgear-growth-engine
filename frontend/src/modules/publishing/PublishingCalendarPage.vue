<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { ApiError } from "../../api/client"
import OperationModal from "../../shared/components/OperationModal.vue"
import { currentUserQueryOptions } from "../auth/auth"
import { listSocialAccounts } from "../platformAccounts/api"
import { cancelPublish,getPublishCalendar,getPublishTaskPage,isEligiblePublishingPair,listApprovedCurrentHeads,listPublishTasks,localMonthRange,publishingKeys,retryPublish,schedulePublish,shouldPollPublishTasks } from "./api"
const client=useQueryClient(),user=useQuery(currentUserQueryOptions()),open=ref(false),contentId=ref(""),accountId=ref(""),localTime=ref(""),message=ref(""),pageUrl=ref<string|null>(null),accountFilter=ref(""),submitting=ref(false),intentKey=ref(""),formError=ref("")
const org=computed(()=>user.data.value?.organization.id??""),canManage=computed(()=>user.data.value?.membership.permissions.includes("publishing.manage")??false)
const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||"UTC",anchor=ref(new Date()),monthLabel=computed(()=>anchor.value.toLocaleDateString("zh-CN",{year:"numeric",month:"long"}))
const range=computed(()=>localMonthRange(anchor.value,timezone))
const calendarInput=computed(()=>({...range.value,...(accountFilter.value?{account:accountFilter.value}:{})}))
const calendar=useQuery({queryKey:computed(()=>[...publishingKeys.calendar(org.value,range.value.start),accountFilter.value]),queryFn:()=>getPublishCalendar(calendarInput.value),enabled:computed(()=>Boolean(org.value))})
const tasks=useQuery({queryKey:computed(()=>[...publishingKeys.tasks(org.value),pageUrl.value]),queryFn:()=>pageUrl.value?getPublishTaskPage(pageUrl.value):listPublishTasks(),enabled:computed(()=>Boolean(org.value)),refetchInterval:query=>shouldPollPublishTasks(query.state.data?.results??[])?5000:false})
const contents=useQuery({queryKey:computed(()=>[...publishingKeys.all(org.value),"contents","approved-heads"]),queryFn:listApprovedCurrentHeads,enabled:computed(()=>Boolean(org.value)&&canManage.value)})
const accounts=useQuery({queryKey:computed(()=>[...publishingKeys.all(org.value),"accounts"]),queryFn:listSocialAccounts,enabled:computed(()=>Boolean(org.value)&&canManage.value)})
const selectedContent=computed(()=>contents.data.value?.find(item=>item.id===contentId.value))
const eligible=computed(()=>selectedContent.value?accounts.data.value?.filter(account=>isEligiblePublishingPair(selectedContent.value!,account))??[]:[])
const refresh=()=>client.invalidateQueries({queryKey:publishingKeys.all(org.value)})
const schedule=useMutation({mutationFn:(input:{contentId:string;accountId:string;scheduledAt:string;key:string})=>schedulePublish({platform_content_id:input.contentId,social_account_id:input.accountId,scheduled_at:input.scheduledAt,timezone},input.key),onSuccess:async()=>{closeSchedule();message.value="发布任务已安排。";await refresh()}})
const action=useMutation({mutationFn:({id,kind}:{id:string;kind:"cancel"|"retry"})=>kind==="cancel"?cancelPublish(id):retryPublish(id),onSettled:refresh})
const err=(v:unknown)=>v instanceof ApiError?v.userMessage:"发布数据暂时无法加载，请稍后重试。"
function move(delta:number){anchor.value=new Date(anchor.value.getFullYear(),anchor.value.getMonth()+delta,1)}
function nextIntentKey(){intentKey.value=crypto.randomUUID()}
function openSchedule(){nextIntentKey();formError.value="";open.value=true}
function closeSchedule(){open.value=false;contentId.value="";accountId.value="";localTime.value="";formError.value="";nextIntentKey()}
async function submitSchedule(){
  if(submitting.value)return
  submitting.value=true
  try{
    const [freshContents,freshAccounts]=await Promise.all([listApprovedCurrentHeads(),listSocialAccounts()])
    const content=freshContents.find(item=>item.id===contentId.value)
    const account=freshAccounts.find(item=>item.id===accountId.value)
    if(!content||!account||!isEligiblePublishingPair(content,account))throw new ApiError(0,"内容或账户已发生变化，请重新选择。")
    const scheduledAt=new Date(localTime.value)
    if(Number.isNaN(scheduledAt.getTime()))throw new ApiError(0,"请选择有效的发布时间。")
    await schedule.mutateAsync({contentId:content.id,accountId:account.id,scheduledAt:scheduledAt.toISOString(),key:intentKey.value})
  }catch(error){formError.value=err(error)
  }finally{submitting.value=false}
}
function retryReady(task:{retry_not_before:string|null}){return !task.retry_not_before||new Date(task.retry_not_before).getTime()<=Date.now()}
function safeError(error:Record<string,unknown>|null){if(!error)return "";return typeof error.message==="string"?error.message:"发布失败，请重试。"}
watch([contentId,accountId,localTime],()=>{if(open.value){nextIntentKey();formError.value=""}})
watch(org,()=>{pageUrl.value=null;accountFilter.value=""})
</script>
<template>
  <main class="page-stack">
    <header class="workspace-head"><div><p class="eyebrow">发布运营</p><h1>发布日历</h1><p>{{ monthLabel }} · 时区 {{ timezone }}</p></div><button v-if="canManage" class="primary-action" @click="openSchedule">安排发布</button></header><p v-if="message" role="status">{{ message }}</p><nav class="month-nav" aria-label="月份"><button @click="move(-1)">上个月</button><strong>{{ monthLabel }}</strong><button @click="move(1)">下个月</button></nav><label>账户筛选<select v-model="accountFilter"><option value="">全部账户</option><option v-for="account in accounts.data.value" :key="account.id" :value="account.id">{{ account.display_name }}</option></select></label><p v-if="calendar.isPending.value" role="status">正在加载发布日历…</p><section v-else-if="calendar.isError.value" role="alert" class="panel"><h2>日历没有加载成功</h2><p>{{ err(calendar.error.value) }}</p><button @click="calendar.refetch()">重新加载日历</button></section><template v-else><p v-if="calendar.data.value?.metadata.truncated" role="status" class="warning">当前月份任务较多，日历仅展示前 {{ calendar.data.value.metadata.max_entries }} 条。</p><section class="agenda"><article v-for="day in calendar.data.value?.days" :key="day.date" class="panel"><h2>{{ day.date }}</h2><div v-for="entry in day.entries" :key="entry.id" class="task"><div><strong>{{ entry.status }}</strong><span> · 第 {{ entry.attempt_number }} 次尝试</span><p v-if="entry.last_error">{{ safeError(entry.last_error) }}</p></div><span>{{ new Date(entry.scheduled_at).toLocaleString() }}</span><div v-if="canManage" class="actions"><button v-if="['SCHEDULED','QUEUED','RUNNING'].includes(entry.status)" @click="action.mutate({id:entry.id,kind:'cancel'})">取消</button><button v-if="entry.status==='FAILED'&&retryReady(entry)" @click="action.mutate({id:entry.id,kind:'retry'})">重试</button></div></div></article></section></template><section class="panel"><h2>最近任务</h2><p v-if="tasks.isError.value" role="alert">{{ err(tasks.error.value) }} <button @click="tasks.refetch()">重新加载任务</button></p><p v-else-if="!tasks.data.value?.results.length">暂无发布任务。</p><ul v-else><li v-for="task in tasks.data.value?.results" :key="task.id">{{ task.status }} · 第 {{ task.attempt_number }} 次尝试 · {{ new Date(task.scheduled_at).toLocaleString() }}<span v-if="task.last_error"> · {{ safeError(task.last_error) }}</span></li></ul><nav class="actions" aria-label="发布任务分页"><button :disabled="!tasks.data.value?.previous" @click="pageUrl=tasks.data.value?.previous??null">上一页</button><button :disabled="!tasks.data.value?.next" @click="pageUrl=tasks.data.value?.next??null">下一页</button></nav></section>
    <OperationModal v-if="open" title="安排发布" title-id="schedule-title" @close="closeSchedule"><form class="modal" @submit.prevent="submitSchedule"><label>已审核当前内容<select v-model="contentId" required><option value="" disabled>请选择</option><option v-for="item in contents.data.value" :key="item.id" :value="item.id">{{ item.payload.title }}</option></select></label><label>可发布账户<select v-model="accountId" required><option value="" disabled>请选择</option><option v-for="item in eligible" :key="item.id" :value="item.id">{{ item.display_name }}</option></select></label><p v-if="!eligible.length">没有可自动发布的账户；请选择内容，或配置同平台 API_AUTO + PUBLISH 账户。</p><label>发布时间<input v-model="localTime" required type="datetime-local"></label><p v-if="formError||schedule.isError.value" role="alert">{{ formError||err(schedule.error.value) }}</p><div class="actions"><button type="button" @click="closeSchedule">取消</button><button class="primary-action" :disabled="!contentId||!accountId||!localTime||submitting||schedule.isPending.value">确认安排</button></div></form></OperationModal>
  </main>
</template>
<style scoped>.workspace-head,.month-nav,.task,.actions{display:flex;justify-content:space-between;gap:1rem;align-items:center}.panel{padding:1.1rem;border:1px solid var(--border-color,#d8dee8);border-radius:1rem;background:white}.agenda{display:grid;gap:1rem}.task{padding:.7rem 0;border-top:1px solid #e5e9ef}.warning{padding:.8rem;background:#fff6d9}.modal{display:grid;gap:1rem}.modal label{display:grid;gap:.35rem}.actions{justify-content:flex-end}@media(max-width:700px){.workspace-head,.task{display:grid}.month-nav{align-items:center}}</style>
