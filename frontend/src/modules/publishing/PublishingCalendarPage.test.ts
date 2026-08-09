import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"
import { currentUserQueryOptions } from "../auth/auth"
import PublishingCalendarPage from "./PublishingCalendarPage.vue"

it("shows the calendar timezone, task status, and scheduling action",async()=>{vi.stubGlobal("fetch",vi.fn((path:string)=>Promise.resolve(new Response(JSON.stringify(path.startsWith("/api/v1/publish-calendar")?{timezone:"Asia/Shanghai",start:"2026-08-01T00:00:00Z",end:"2026-09-01T00:00:00Z",metadata:{max_entries:100,returned_entries:1,truncated:false},days:[{date:"2026-08-10",entries:[{id:"t1",platform_content_id:"c1",social_account_id:"a1",platform_id:"p1",status:"SCHEDULED",scheduled_at:"2026-08-10T08:00:00Z",attempt_number:0,attempts:[]}]}]}:{next:null,previous:null,results:[]}),{status:200,headers:{"Content-Type":"application/json"}}))));const client=new QueryClient({defaultOptions:{queries:{retry:false}}});client.setQueryData(currentUserQueryOptions().queryKey,{user:{id:1,username:"op"},organization:{id:"o1",name:"Org",slug:"org"},membership:{id:"m",role:"OPERATOR",status:"ACTIVE",permissions:["publishing.read","publishing.manage"]}});render(PublishingCalendarPage,{global:{plugins:[[VueQueryPlugin,{queryClient:client}]]}});expect(await screen.findByText("SCHEDULED")).toBeInTheDocument();expect(screen.getByText(/Asia\/Shanghai/)).toBeInTheDocument();expect(screen.getByRole("button",{name:"安排发布"})).toBeInTheDocument()})

afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals()})
function renderPublishing(permissions:string[],fetch:ReturnType<typeof vi.fn>){vi.stubGlobal("fetch",fetch);const client=new QueryClient({defaultOptions:{queries:{retry:false}}});client.setQueryData(currentUserQueryOptions().queryKey,{user:{id:1,username:"user"},organization:{id:"o1",name:"Org",slug:"org"},membership:{id:"m",role:"READ_ONLY",status:"ACTIVE",permissions}});render(PublishingCalendarPage,{global:{plugins:[[VueQueryPlugin,{queryClient:client}]]}})}
it("announces a truncated calendar and explains when no account can publish",async()=>{const calendar={timezone:"UTC",start:"2026-08-01T00:00:00Z",end:"2026-09-01T00:00:00Z",metadata:{max_entries:2,returned_entries:2,truncated:true},days:[]};const fetch=vi.fn((path:string)=>Promise.resolve(new Response(JSON.stringify(path.startsWith("/api/v1/publish-calendar")?calendar:path==="/api/v1/social-accounts"?{results:[{id:"a",status:"ACTIVE",effective_capabilities:[],display_name:"Manual"}]}:{next:null,previous:null,results:[]}),{status:200,headers:{"Content-Type":"application/json"}})));renderPublishing(["publishing.read","publishing.manage"],fetch);expect(await screen.findByText(/前 2 条/)).toBeInTheDocument();await userEvent.click(screen.getByRole("button",{name:"安排发布"}));expect(screen.getByText(/没有可自动发布的账户/)).toBeInTheDocument();expect(screen.getByRole("button",{name:"确认安排"})).toBeDisabled()})
it("hides schedule and task actions from publishing readers",async()=>{const calendar={timezone:"UTC",start:"2026-08-01T00:00:00Z",end:"2026-09-01T00:00:00Z",metadata:{max_entries:100,returned_entries:1,truncated:false},days:[{date:"2026-08-10",entries:[{id:"t",status:"SCHEDULED",scheduled_at:"2026-08-10T00:00:00Z",attempts:[]}]}]};const fetch=vi.fn((path:string)=>Promise.resolve(new Response(JSON.stringify(path.startsWith("/api/v1/publish-calendar")?calendar:{next:null,previous:null,results:[]}),{status:200,headers:{"Content-Type":"application/json"}})));renderPublishing(["publishing.read"],fetch);expect(await screen.findByText("SCHEDULED")).toBeInTheDocument();expect(screen.queryByRole("button",{name:"安排发布"})).not.toBeInTheDocument();expect(screen.queryByRole("button",{name:"取消"})).not.toBeInTheDocument()})
it("shows a named retry for a 503 calendar",async()=>{const fetch=vi.fn((path:string)=>Promise.resolve(path.startsWith("/api/v1/publish-calendar")?new Response(null,{status:503}):new Response(JSON.stringify({next:null,previous:null,results:[]}),{status:200,headers:{"Content-Type":"application/json"}})));renderPublishing(["publishing.read"],fetch);expect(await screen.findByRole("alert")).toHaveTextContent("日历没有加载成功");expect(screen.getByRole("button",{name:"重新加载日历"})).toBeInTheDocument()})
it("offers only exact-platform API-auto accounts and reuses the intent key after a conflict",async()=>{document.cookie="csrftoken=t; path=/";const content={id:"c1",master_content_id:"m",master_version:1,platform_id:"p1",lineage_id:"l",previous_version_id:null,version:1,payload:{title:"Approved head",body:"",cta:"",concept_codes:[],platform_code:"x"},provenance:{},status:"APPROVED",is_current_head:true,created_by_id:1,created_at:"",updated_at:""};const accounts=[{id:"good",platform_id:"p1",display_name:"Good API",publish_mode:"API_AUTO",status:"ACTIVE",effective_capabilities:["PUBLISH"],credential_configured:true},{id:"manual",platform_id:"p1",display_name:"Manual",publish_mode:"MANUAL",status:"ACTIVE",effective_capabilities:["PUBLISH"],credential_configured:true},{id:"other",platform_id:"p2",display_name:"Other platform",publish_mode:"API_AUTO",status:"ACTIVE",effective_capabilities:["PUBLISH"],credential_configured:true}];const keys:string[]=[];let schedules=0;const fetch=vi.fn((path:string,init?:RequestInit)=>{if(path.startsWith("/api/v1/publish-calendar"))return Promise.resolve(new Response(JSON.stringify({metadata:{max_entries:100,returned_entries:0,truncated:false},days:[]}),{status:200,headers:{"Content-Type":"application/json"}}));if(path.startsWith("/api/v1/platform-contents"))return Promise.resolve(new Response(JSON.stringify({next:null,previous:null,results:[content]}),{status:200,headers:{"Content-Type":"application/json"}}));if(path==="/api/v1/social-accounts")return Promise.resolve(new Response(JSON.stringify({results:accounts}),{status:200,headers:{"Content-Type":"application/json"}}));if(path==="/api/v1/publish-tasks/schedule"){keys.push(new Headers(init?.headers).get("Idempotency-Key")!);schedules++;return Promise.resolve(new Response(JSON.stringify(schedules===1?{detail:"Conflict"}:{id:"t1"}),{status:schedules===1?409:201,headers:{"Content-Type":"application/json"}}))}return Promise.resolve(new Response(JSON.stringify({next:null,previous:null,results:[]}),{status:200,headers:{"Content-Type":"application/json"}}))});renderPublishing(["publishing.read","publishing.manage"],fetch);await userEvent.click(await screen.findByRole("button",{name:"安排发布"}));expect(screen.getByRole("heading",{name:"安排发布"})).toHaveFocus();await userEvent.selectOptions(await screen.findByLabelText("已审核当前内容"),"c1");const accountSelect=screen.getByLabelText("可发布账户");expect(within(accountSelect).getByRole("option",{name:"Good API"})).toBeInTheDocument();expect(within(accountSelect).queryByRole("option",{name:"Manual"})).not.toBeInTheDocument();expect(within(accountSelect).queryByRole("option",{name:"Other platform"})).not.toBeInTheDocument();await userEvent.selectOptions(accountSelect,"good");await userEvent.type(screen.getByLabelText("发布时间"),"2026-08-12T12:00");await userEvent.click(screen.getByRole("button",{name:"确认安排"}));expect(await screen.findByRole("alert")).toBeInTheDocument();await userEvent.click(screen.getByRole("button",{name:"确认安排"}));expect(await screen.findByText("发布任务已安排。")).toBeInTheDocument();expect(keys).toHaveLength(2);expect(keys[1]).toBe(keys[0])})

it("refreshes the visible calendar row when active recent-task polling completes",async()=>{
  vi.useFakeTimers()
  let calendarCalls=0,taskCalls=0
  const entry=(status:string)=>({id:"poll-task",platform_content_id:"content",social_account_id:"account",platform_id:"platform",status,scheduled_at:"2026-08-10T08:00:00Z",requested_timezone:"UTC",attempt_number:1,retry_not_before:null,last_error:null,attempts:[],published_post:null})
  const fetch=vi.fn((path:string)=>{
    if(path.startsWith("/api/v1/publish-calendar")){calendarCalls++;return Promise.resolve(new Response(JSON.stringify({timezone:"UTC",start:"",end:"",metadata:{max_entries:100,returned_entries:1,truncated:false},days:[{date:"2026-08-10",entries:[entry(calendarCalls===1?"SCHEDULED":"SUCCEEDED")]}]}),{status:200,headers:{"Content-Type":"application/json"}}))}
    if(path==="/api/v1/publish-tasks"){taskCalls++;return Promise.resolve(new Response(JSON.stringify({next:null,previous:null,results:[entry(taskCalls===1?"QUEUED":"SUCCEEDED")]}),{status:200,headers:{"Content-Type":"application/json"}}))}
    return Promise.resolve(new Response(JSON.stringify({results:[]}),{status:200,headers:{"Content-Type":"application/json"}}))
  })
  renderPublishing(["publishing.read"],fetch)
  await vi.waitFor(()=>expect(within(screen.getByRole("heading",{name:"2026-08-10"}).parentElement!).getByText("SCHEDULED")).toBeInTheDocument())
  await vi.advanceTimersByTimeAsync(5000)
  await vi.waitFor(()=>expect(within(screen.getByRole("heading",{name:"2026-08-10"}).parentElement!).getByText("SUCCEEDED")).toBeInTheDocument())
  expect(taskCalls).toBeGreaterThanOrEqual(2)
  expect(calendarCalls).toBeGreaterThanOrEqual(2)
})

it("guards cancel and retry synchronously per task, disables only that action, and surfaces conflicts",async()=>{
  document.cookie="csrftoken=t; path=/"
  let resolveCancel!:(response:Response)=>void,resolveRetry!:(response:Response)=>void
  const cancelResponse=new Promise<Response>(resolve=>{resolveCancel=resolve}),retryResponse=new Promise<Response>(resolve=>{resolveRetry=resolve})
  const base={platform_content_id:"content",social_account_id:"account",platform_id:"platform",scheduled_at:"2026-08-10T08:00:00Z",requested_timezone:"UTC",attempt_number:1,retry_not_before:null,last_error:null,attempts:[],published_post:null}
  const calendar={timezone:"UTC",start:"",end:"",metadata:{max_entries:100,returned_entries:2,truncated:false},days:[{date:"2026-08-10",entries:[{...base,id:"cancel-task",status:"SCHEDULED"},{...base,id:"retry-task",status:"FAILED"}]}]}
  const fetch=vi.fn((path:string,init?:RequestInit)=>{
    if(path.startsWith("/api/v1/publish-calendar"))return Promise.resolve(new Response(JSON.stringify(calendar),{status:200,headers:{"Content-Type":"application/json"}}))
    if(path==="/api/v1/publish-tasks/cancel-task/cancel"&&init?.method==="POST")return cancelResponse
    if(path==="/api/v1/publish-tasks/retry-task/retry"&&init?.method==="POST")return retryResponse
    if(path==="/api/v1/social-accounts")return Promise.resolve(new Response(JSON.stringify({results:[]}),{status:200,headers:{"Content-Type":"application/json"}}))
    return Promise.resolve(new Response(JSON.stringify({next:null,previous:null,results:[]}),{status:200,headers:{"Content-Type":"application/json"}}))
  })
  renderPublishing(["publishing.read","publishing.manage"],fetch)
  const cancel=await screen.findByRole("button",{name:"取消"}),retry=screen.getByRole("button",{name:"重试"})
  await fireEvent.click(cancel);await fireEvent.click(cancel)
  expect(cancel).toBeDisabled();expect(retry).not.toBeDisabled()
  expect(fetch.mock.calls.filter(call=>call[0]==="/api/v1/publish-tasks/cancel-task/cancel")).toHaveLength(1)
  resolveCancel(new Response(JSON.stringify({...base,id:"cancel-task",status:"CANCELED"}),{status:200,headers:{"Content-Type":"application/json"}}))
  await waitFor(()=>expect(cancel).not.toBeDisabled())
  await fireEvent.click(retry);await fireEvent.click(retry)
  expect(retry).toBeDisabled();expect(cancel).not.toBeDisabled()
  expect(fetch.mock.calls.filter(call=>call[0]==="/api/v1/publish-tasks/retry-task/retry")).toHaveLength(1)
  resolveRetry(new Response(JSON.stringify({detail:"Retry window has changed."}),{status:409,headers:{"Content-Type":"application/json"}}))
  expect(await screen.findByRole("alert")).toHaveTextContent("Retry window has changed.")
  expect(retry).not.toBeDisabled()
})

it("loads safe account-filter options for publishing readers without exposing management controls",async()=>{
  const fetch=vi.fn((path:string)=>{
    if(path.startsWith("/api/v1/publish-calendar"))return Promise.resolve(new Response(JSON.stringify({timezone:"UTC",start:"",end:"",metadata:{max_entries:100,returned_entries:0,truncated:false},days:[]}),{status:200,headers:{"Content-Type":"application/json"}}))
    if(path==="/api/v1/social-accounts")return Promise.resolve(new Response(JSON.stringify({results:[{id:"reader-account",platform_id:"platform",display_name:"Reader-visible account",publish_mode:"MANUAL",status:"ACTIVE",effective_capabilities:[],credential_configured:false}]}),{status:200,headers:{"Content-Type":"application/json"}}))
    return Promise.resolve(new Response(JSON.stringify({next:null,previous:null,results:[]}),{status:200,headers:{"Content-Type":"application/json"}}))
  })
  renderPublishing(["publishing.read"],fetch)
  expect(await screen.findByRole("option",{name:"Reader-visible account"})).toBeInTheDocument()
  expect(screen.queryByRole("button",{name:"安排发布"})).not.toBeInTheDocument()
  expect(fetch.mock.calls.some(call=>String(call[0]).startsWith("/api/v1/platform-contents"))).toBe(false)
})

it("does not let a stale schedule completion close or reset a newly reopened dialog",async()=>{
  document.cookie="csrftoken=t; path=/"
  let resolveSchedule!:(response:Response)=>void
  const pendingSchedule=new Promise<Response>(resolve=>{resolveSchedule=resolve})
  const content={id:"content",master_content_id:"m",master_version:1,platform_id:"platform",lineage_id:"line",previous_version_id:null,version:1,payload:{title:"Approved",body:"",cta:"",concept_codes:[],platform_code:"x"},provenance:{},status:"APPROVED",is_current_head:true,created_by_id:1,created_at:"",updated_at:""}
  const account={id:"account",platform_id:"platform",display_name:"API account",publish_mode:"API_AUTO",status:"ACTIVE",effective_capabilities:["PUBLISH"],credential_configured:true}
  const fetch=vi.fn((path:string,init?:RequestInit)=>{
    if(path.startsWith("/api/v1/publish-calendar"))return Promise.resolve(new Response(JSON.stringify({timezone:"UTC",start:"",end:"",metadata:{max_entries:100,returned_entries:0,truncated:false},days:[]}),{status:200,headers:{"Content-Type":"application/json"}}))
    if(path.startsWith("/api/v1/platform-contents"))return Promise.resolve(new Response(JSON.stringify({next:null,previous:null,results:[content]}),{status:200,headers:{"Content-Type":"application/json"}}))
    if(path==="/api/v1/social-accounts")return Promise.resolve(new Response(JSON.stringify({results:[account]}),{status:200,headers:{"Content-Type":"application/json"}}))
    if(path==="/api/v1/publish-tasks/schedule"&&init?.method==="POST")return pendingSchedule
    return Promise.resolve(new Response(JSON.stringify({next:null,previous:null,results:[]}),{status:200,headers:{"Content-Type":"application/json"}}))
  })
  renderPublishing(["publishing.read","publishing.manage"],fetch)
  const open=await screen.findByRole("button",{name:"安排发布"});await userEvent.click(open)
  await userEvent.selectOptions(screen.getByLabelText("已审核当前内容"),"content");await userEvent.selectOptions(screen.getByLabelText("可发布账户"),"account");await userEvent.type(screen.getByLabelText("发布时间"),"2026-08-12T12:00");await userEvent.click(screen.getByRole("button",{name:"确认安排"}))
  await waitFor(()=>expect(fetch.mock.calls.some(call=>call[0]==="/api/v1/publish-tasks/schedule")).toBe(true))
  await userEvent.keyboard("{Escape}");await userEvent.click(open)
  await userEvent.selectOptions(screen.getByLabelText("已审核当前内容"),"content");await userEvent.selectOptions(screen.getByLabelText("可发布账户"),"account");await userEvent.type(screen.getByLabelText("发布时间"),"2026-08-13T13:30")
  resolveSchedule(new Response(JSON.stringify({id:"scheduled"}),{status:201,headers:{"Content-Type":"application/json"}}))
  expect(await screen.findByText("发布任务已安排。")).toBeInTheDocument()
  expect(screen.getByRole("dialog")).toBeInTheDocument()
  expect(screen.getByLabelText("发布时间")).toHaveValue("2026-08-13T13:30")
})
