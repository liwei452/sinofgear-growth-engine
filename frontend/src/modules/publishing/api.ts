import { ApiError, apiRequest } from "../../api/client"
import { getCursorPage, type CursorPage } from "../content/api"

const required=<T>(value:T|undefined):T=>{if(value===undefined)throw new ApiError(0,"服务响应不完整，请重试。");return value}
export type PublishTask={id:string;platform_content_id:string;social_account_id:string;platform_id:string;status:string;scheduled_at:string;requested_timezone:string;attempt_number:number;retry_not_before:string|null;last_error:Record<string,unknown>|null;attempts:Array<{number:number;status:string;outcome:string}>;published_post:{id:string;external_id:string;published_at:string}|null}
export type Calendar={timezone:string;start:string;end:string;metadata:{max_entries:number;returned_entries:number;truncated:boolean};days:Array<{date:string;entries:PublishTask[]}>}
const taskPath="/api/v1/publish-tasks"
export const publishingKeys={all:(org:string)=>["publishing",org] as const,tasks:(org:string)=>[...publishingKeys.all(org),"tasks"] as const,calendar:(org:string,start:string)=>[...publishingKeys.all(org),"calendar",start] as const}
export const listPublishTasks=async():Promise<CursorPage<PublishTask>>=>required(await apiRequest(taskPath))
export const getPublishTaskPage=(url:string)=>getCursorPage<PublishTask>(url,taskPath)
export const getPublishCalendar=async(input:{start:string;end:string;timezone:string;platform?:string;account?:string}):Promise<Calendar>=>{const p=new URLSearchParams(input);return required(await apiRequest(`/api/v1/publish-calendar?${p}`))}
export const schedulePublish=async(input:{platform_content_id:string;social_account_id:string;scheduled_at:string;timezone:string},key:string):Promise<PublishTask>=>required(await apiRequest(`${taskPath}/schedule`,{method:"POST",headers:{"Idempotency-Key":key},body:input}))
export const cancelPublish=async(id:string):Promise<PublishTask>=>required(await apiRequest(`${taskPath}/${id}/cancel`,{method:"POST",body:{}}))
export const retryPublish=async(id:string):Promise<PublishTask>=>required(await apiRequest(`${taskPath}/${id}/retry`,{method:"POST",body:{}}))
