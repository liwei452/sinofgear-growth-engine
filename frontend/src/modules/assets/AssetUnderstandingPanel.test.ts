import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"
import AssetUnderstandingPanel from "./AssetUnderstandingPanel.vue"

afterEach(()=>vi.unstubAllGlobals())
const response=(value:unknown)=>new Response(JSON.stringify(value),{status:200,headers:{"Content-Type":"application/json"}})
const result={job:{id:"j1",status:"SUCCEEDED",progress:100,attempt:1,max_attempts:3,error:null},provider_label:"Fake Provider · 本地演示",is_partial:false,warnings:[],facts:[{id:"f1",product:"p1",asset:"a1",category:"SPECIFICATION",field_name:"accuracy",value:"DIN 6",confidence:"0.9000",source_page:1,source_region:null,source_excerpt:"Accuracy: DIN 6",risk_level:"HIGH",review_status:"SUGGESTED",provider_label:"Fake Provider · 本地演示",is_demo:true,reviewed_by:null,reviewed_at:null,review_note:"",created_at:"2026-08-15T00:00:00Z",updated_at:"2026-08-15T00:00:00Z"}]}
function mount(productId="p1"){const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});render(AssetUnderstandingPanel,{props:{assetId:"a1",productId,canManage:true},global:{plugins:[[VueQueryPlugin,{queryClient:client}]]}})}

it("requires a product before preparing facts",()=>{mount("");expect(screen.getByRole("button",{name:"准备产品事实"})).toBeDisabled()})
it("shows explicit Fake evidence and approves only after a human action",async()=>{document.cookie="csrftoken=t; path=/";const fetch=vi.fn().mockResolvedValueOnce(response(result)).mockResolvedValueOnce(response({...result.facts[0],review_status:"VERIFIED"}));vi.stubGlobal("fetch",fetch);mount();await userEvent.click(screen.getByRole("button",{name:"准备产品事实"}));expect(await screen.findByText("Fake Provider · 本地演示")).toBeInTheDocument();expect(screen.getByText("Accuracy: DIN 6")).toBeInTheDocument();expect(screen.getByText("高风险事实，必须人工确认")).toBeInTheDocument();await userEvent.click(screen.getByRole("button",{name:"确认写入事实库"}));expect(await screen.findByText("已验证")).toBeInTheDocument();expect(fetch).toHaveBeenCalledTimes(2)})
