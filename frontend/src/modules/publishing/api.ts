import { ApiError, apiRequest } from "../../api/client"
import { getCursorPage, listPlatformContents, safeCursorUrl, type CursorPage, type PlatformContent } from "../content/api"
import type { SocialAccount } from "../platformAccounts/api"

const required=<T>(value:T|undefined):T=>{if(value===undefined)throw new ApiError(0,"服务响应不完整，请重试。");return value}
export type PublishTask={id:string;platform_content_id:string;social_account_id:string;platform_id:string;status:string;scheduled_at:string;requested_timezone:string;attempt_number:number;retry_not_before:string|null;last_error:Record<string,unknown>|null;attempts:Array<{number:number;status:string;outcome:string}>;published_post:{id:string;external_id:string;published_at:string}|null}
export type Calendar={timezone:string;start:string;end:string;metadata:{max_entries:number;returned_entries:number;truncated:boolean};days:Array<{date:string;entries:PublishTask[]}>}
const taskPath="/api/v1/publish-tasks"
export const publishingKeys={all:(org:string)=>["publishing",org] as const,tasks:(org:string)=>[...publishingKeys.all(org),"tasks"] as const,calendar:(org:string,start:string)=>[...publishingKeys.all(org),"calendar",start] as const}
export const listPublishTasks=async():Promise<CursorPage<PublishTask>>=>required(await apiRequest(taskPath))
export const getPublishTaskPage=(url:string)=>getCursorPage<PublishTask>(url,taskPath)
export const getPublishTask=async(id:string):Promise<PublishTask>=>required(await apiRequest(`${taskPath}/${id}`))
export const getPublishCalendar=async(input:{start:string;end:string;timezone:string;platform?:string;account?:string}):Promise<Calendar>=>{const p=new URLSearchParams(input);return required(await apiRequest(`/api/v1/publish-calendar?${p}`))}
export const schedulePublish=async(input:{platform_content_id:string;social_account_id:string;scheduled_at:string;timezone:string},key:string):Promise<PublishTask>=>required(await apiRequest(`${taskPath}/schedule`,{method:"POST",headers:{"Idempotency-Key":key},body:input}))
export const cancelPublish=async(id:string):Promise<PublishTask>=>required(await apiRequest(`${taskPath}/${id}/cancel`,{method:"POST",body:{}}))
export const retryPublish=async(id:string):Promise<PublishTask>=>required(await apiRequest(`${taskPath}/${id}/retry`,{method:"POST",body:{}}))
export const runPublish=async(id:string):Promise<PublishTask>=>required(await apiRequest(`${taskPath}/${id}/run`,{method:"POST",body:{}}))

export function localMonthRange(anchor:Date,timezone:string):{start:string;end:string;timezone:string}{
  const start=new Date(anchor.getFullYear(),anchor.getMonth(),1)
  const end=new Date(anchor.getFullYear(),anchor.getMonth()+1,1)
  return {start:start.toISOString(),end:end.toISOString(),timezone}
}

export function approvedCurrentHeads(items:PlatformContent[]):PlatformContent[]{
  const newest=new Map<string,PlatformContent>()
  for(const item of items){
    const existing=newest.get(item.lineage_id)
    if(!existing||item.version>existing.version)newest.set(item.lineage_id,item)
  }
  return [...newest.values()].filter(item=>item.is_current_head&&item.status==="APPROVED")
}

export async function listApprovedCurrentHeads():Promise<PlatformContent[]>{
  const all:PlatformContent[]=[]
  const visited=new Set<string>()
  let page=await listPlatformContents({page_size:50})
  all.push(...page.results)
  while(page.next){const next=safeCursorUrl(page.next,"/api/v1/platform-contents");if(!next||visited.has(next))throw new ApiError(0,"内容分页地址无效。");visited.add(next);page=await getCursorPage<PlatformContent>(next,"/api/v1/platform-contents");all.push(...page.results)}
  return approvedCurrentHeads(all)
}

export function isEligiblePublishingPair(content:PlatformContent,account:SocialAccount):boolean{
  return content.status==="APPROVED"&&content.is_current_head
    && account.platform_id===content.platform_id&&account.status==="ACTIVE"
    && account.publish_mode==="API_AUTO"&&account.effective_capabilities.includes("PUBLISH")
}

export function shouldPollPublishTasks(tasks:PublishTask[],now=new Date()):boolean{
  return tasks.some(task=>{
    if(["QUEUED","RUNNING"].includes(task.status))return true
    if(task.status==="SCHEDULED")return new Date(task.scheduled_at).getTime()<=now.getTime()
    if(task.status==="RETRY_QUEUED")return !task.retry_not_before||new Date(task.retry_not_before).getTime()<=now.getTime()
    return false
  })
}
