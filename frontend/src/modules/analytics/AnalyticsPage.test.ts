import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"
import { currentUserQueryOptions } from "../auth/auth"
import AnalyticsPage from "./AnalyticsPage.vue"

const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{"Content-Type":"application/json"}})
afterEach(()=>vi.unstubAllGlobals())
function renderAnalytics(fetch:ReturnType<typeof vi.fn>,permissions=["tracking.read"],org="o1"){
  vi.stubGlobal("fetch",fetch)
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
  client.setQueryData(currentUserQueryOptions().queryKey,{user:{id:1,username:"reader"},organization:{id:org,name:"Org",slug:"org"},membership:{id:"m",role:"READ_ONLY",status:"ACTIVE",permissions}})
  render(AnalyticsPage,{global:{plugins:[[VueQueryPlugin,{queryClient:client}]]}})
  return client
}

it("explains the result before metrics and keeps operations collapsed",async()=>{
  const fetch=vi.fn((path:string)=>Promise.resolve(json(path.startsWith("/api/v1/analytics")
    ?{count:1,total_clicks:17,next:null,previous:null,results:[{date:"2026-08-10",campaign_id:"campaign-uuid",platform_id:"platform-uuid",country:"DE",product_id:"product-uuid",clicks:17}]}
    :{next:null,previous:null,results:[]})))
  renderAnalytics(fetch)

  expect(await screen.findByRole("heading",{name:"效果"})).toBeVisible()
  const conclusion=screen.getByRole("region",{name:"AI 结论"})
  const metrics=screen.getByRole("region",{name:"关键指标"})
  const trend=screen.getByRole("region",{name:"点击趋势"})
  const nextStep=screen.getByRole("region",{name:"下一步建议"})
  const operations=screen.getByRole("group",{name:"运营详情"})
  expect(await within(conclusion).findByText(/数据还不足以判断哪个平台效果最好/)).toBeVisible()
  expect(conclusion).toHaveTextContent("不能据此判断点击变化的原因")
  expect(conclusion.compareDocumentPosition(metrics)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(metrics.compareDocumentPosition(trend)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(trend.compareDocumentPosition(nextStep)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(operations).not.toHaveAttribute("open")
})

it("uses real names when available and never promotes an unresolved id as a name",async()=>{
  const fetch=vi.fn((path:string)=>{
    if(path.startsWith("/api/v1/analytics"))return Promise.resolve(json({count:2,total_clicks:20,next:null,previous:null,results:[
      {date:"2026-08-09",campaign_id:"campaign-1",platform_id:"platform-1",country:"DE",product_id:"product-1",clicks:8},
      {date:"2026-08-10",campaign_id:"campaign-missing",platform_id:"platform-1",country:"DE",product_id:"product-1",clicks:12},
    ]}))
    if(path==="/api/v1/campaigns")return Promise.resolve(json({next:null,previous:null,results:[{id:"campaign-1",name:"德国客户推广"}]}))
    if(path==="/api/v1/platforms")return Promise.resolve(json({results:[{id:"platform-1",name:"领英",code:"LINKEDIN",capabilities:[]}]}))
    if(path==="/api/v1/products")return Promise.resolve(json({next:null,previous:null,results:[{id:"product-1",name_zh:"精密齿轮",name_en:"Precision Gear"}]}))
    return Promise.resolve(json({next:null,previous:null,results:[]}))
  })
  renderAnalytics(fetch,["tracking.read","campaigns.read","memberships.read","products.read"])

  const details=await screen.findByRole("table",{name:"渠道点击明细"})
  expect(details).toHaveTextContent("德国客户推广")
  expect(details).toHaveTextContent("领英")
  expect(details).toHaveTextContent("精密齿轮")
  expect(details).toHaveTextContent("名称暂不可用")
  expect(details).not.toHaveTextContent("campaign-missing")
})

it("does not compare platforms measured on different date windows",async()=>{
  const fetch=vi.fn((path:string)=>Promise.resolve(json(path.startsWith("/api/v1/analytics")?{
    count:4,total_clicks:40,next:null,previous:null,results:[
      {date:"2026-08-01",campaign_id:"c",platform_id:"platform-a",country:"DE",product_id:"p",clicks:10},
      {date:"2026-08-02",campaign_id:"c",platform_id:"platform-a",country:"DE",product_id:"p",clicks:10},
      {date:"2026-08-03",campaign_id:"c",platform_id:"platform-b",country:"DE",product_id:"p",clicks:10},
      {date:"2026-08-04",campaign_id:"c",platform_id:"platform-b",country:"DE",product_id:"p",clicks:10},
    ],
  }:{next:null,previous:null,results:[]})))
  renderAnalytics(fetch)

  const conclusion=screen.getByRole("region",{name:"AI 结论"})
  expect(await within(conclusion).findByText(/数据还不足以判断哪个平台效果最好/)).toBeVisible()
})

it("does not treat one summary page as the complete comparison",async()=>{
  const fetch=vi.fn((path:string)=>Promise.resolve(json(path.startsWith("/api/v1/analytics")?{
    count:5,total_clicks:50,next:"/api/v1/analytics/channel-summary?cursor=next",previous:null,results:[
      {date:"2026-08-01",campaign_id:"c",platform_id:"a",country:"DE",product_id:"p",clicks:10},
      {date:"2026-08-02",campaign_id:"c",platform_id:"a",country:"DE",product_id:"p",clicks:10},
      {date:"2026-08-01",campaign_id:"c",platform_id:"b",country:"DE",product_id:"p",clicks:10},
      {date:"2026-08-02",campaign_id:"c",platform_id:"b",country:"DE",product_id:"p",clicks:10},
    ],
  }:{next:null,previous:null,results:[]})))
  renderAnalytics(fetch)

  const conclusion=screen.getByRole("region",{name:"AI 结论"})
  expect(await within(conclusion).findByText(/数据还不足以判断哪个平台效果最好/)).toBeVisible()
  expect(screen.getByText("当前页涉及平台")).toBeVisible()
})

it("reports a tie without naming a leading platform",async()=>{
  const fetch=vi.fn((path:string)=>Promise.resolve(json(path.startsWith("/api/v1/analytics")?{
    count:4,total_clicks:40,next:null,previous:null,results:[
      {date:"2026-08-01",campaign_id:"c",platform_id:"a",country:"DE",product_id:"p",clicks:10},
      {date:"2026-08-02",campaign_id:"c",platform_id:"a",country:"DE",product_id:"p",clicks:10},
      {date:"2026-08-01",campaign_id:"c",platform_id:"b",country:"DE",product_id:"p",clicks:10},
      {date:"2026-08-02",campaign_id:"c",platform_id:"b",country:"DE",product_id:"p",clicks:10},
    ],
  }:{next:null,previous:null,results:[]})))
  renderAnalytics(fetch)

  const conclusion=screen.getByRole("region",{name:"AI 结论"})
  expect(await within(conclusion).findByText(/点击数据持平，无法区分/)).toBeVisible()
  expect(conclusion).not.toHaveTextContent("点击数较高")
})

it("resolves campaign and product names from safe later pages",async()=>{
  const fetch=vi.fn((path:string)=>{
    if(path.startsWith("/api/v1/analytics"))return Promise.resolve(json({count:1,total_clicks:5,next:null,previous:null,results:[{date:"2026-08-01",campaign_id:"campaign-2",platform_id:"platform-1",country:"DE",product_id:"product-2",clicks:5}]}))
    if(path==="/api/v1/campaigns")return Promise.resolve(json({next:"/api/v1/campaigns?cursor=c2",previous:null,results:[]}))
    if(path==="/api/v1/campaigns?cursor=c2")return Promise.resolve(json({next:null,previous:"/api/v1/campaigns",results:[{id:"campaign-2",name:"第二页活动"}]}))
    if(path==="/api/v1/products")return Promise.resolve(json({next:"/api/v1/products?cursor=p2",previous:null,results:[]}))
    if(path==="/api/v1/products?cursor=p2")return Promise.resolve(json({next:null,previous:"/api/v1/products",results:[{id:"product-2",name_zh:"第二页产品"}]}))
    if(path==="/api/v1/platforms")return Promise.resolve(json({results:[{id:"platform-1",name:"领英",code:"LINKEDIN",capabilities:[]}]}))
    return Promise.resolve(json({next:null,previous:null,results:[]}))
  })
  renderAnalytics(fetch,["tracking.read","campaigns.read","memberships.read","products.read"])

  expect(await screen.findByText("第二页活动")).toBeVisible()
  expect(await screen.findByText("第二页产品")).toBeVisible()
})

it("shows the click total and filters without exposing unresolved provenance ids",async()=>{const fetch=vi.fn((path:string)=>Promise.resolve(json(path.startsWith("/api/v1/analytics")?{count:1,total_clicks:17,next:null,previous:null,results:[{date:"2026-08-10",campaign_id:"campaign-visible",platform_id:"platform-visible",country:"DE",product_id:"prod",clicks:17}]}:{next:null,previous:null,results:[]})));renderAnalytics(fetch);expect(await screen.findByLabelText("总点击数")).toHaveTextContent("17");const table=screen.getByRole("table",{name:"渠道点击明细"});expect(table).toHaveTextContent("名称暂不可用");expect(table).not.toHaveTextContent("campaign-visible");expect(table).not.toHaveTextContent("platform-visible");for(const label of ["活动","平台","产品","国家代码"])expect(screen.getByLabelText(label)).toBeInTheDocument()})

it("fails closed without tracking.read and exposes mutations only with tracking.manage",async()=>{const fetch=vi.fn();renderAnalytics(fetch,["publishing.read"]);expect(screen.getByRole("alert")).toHaveTextContent("没有分析权限");expect(screen.queryByRole("button",{name:"创建追踪链接"})).not.toBeInTheDocument();expect(fetch).not.toHaveBeenCalled()})

it("reports clipboard failure without navigating",async()=>{Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:vi.fn().mockRejectedValue(new Error("denied"))}});const fetch=vi.fn((path:string)=>Promise.resolve(json(path.startsWith("/api/v1/analytics")?{count:0,total_clicks:0,next:null,previous:null,results:[]}:path==="/api/v1/tracking-links"?{next:null,previous:null,results:[{id:"l",utm_campaign:"launch",full_url:"https://example.com/?utm_source=x"}]}:{next:null,previous:null,results:[]})));renderAnalytics(fetch);await userEvent.click(await screen.findByRole("button",{name:"复制"}));expect(screen.getByRole("status")).toHaveTextContent("复制失败")})

it("shows a named retry for a 503 summary",async()=>{const fetch=vi.fn((path:string)=>Promise.resolve(path.startsWith("/api/v1/analytics")?new Response(null,{status:503}):json({next:null,previous:null,results:[]})));renderAnalytics(fetch);expect(await screen.findByRole("alert")).toHaveTextContent("分析数据没有加载成功");expect(screen.getByRole("button",{name:"重新加载分析数据"})).toBeInTheDocument()})

it("requires an explicit valid choice for a multi-product brief and locks submitted provenance",async()=>{document.cookie="csrftoken=t; path=/";const fetch=vi.fn((path:string,init?:RequestInit)=>{let payload:unknown={next:null,previous:null,results:[]};if(path.startsWith("/api/v1/analytics"))payload={count:0,total_clicks:0,next:null,previous:null,results:[]};if(path==="/api/v1/publish-tasks")payload={next:null,previous:null,results:[{id:"task",platform_content_id:"pc",platform_id:"platform",published_post:{id:"post",external_id:"remote-1"}}]};if(path==="/api/v1/publish-tasks/task")payload={id:"task",platform_content_id:"pc",platform_id:"platform",published_post:{id:"post",external_id:"remote-1"}};if(path==="/api/v1/platform-contents/pc")payload={id:"pc",master_content_id:"master"};if(path==="/api/v1/master-contents/master")payload={id:"master",brief_id:"brief"};if(path==="/api/v1/content-briefs/brief")payload={id:"brief",campaign_id:"campaign",product_ids:["product-a","product-b"],landing_page_url:"https://example.com/gear"};if(path==="/api/v1/tracking-links"&&init?.method==="POST")payload={id:"link",full_url:"https://example.com/gear?utm_source=linkedin"};return Promise.resolve(json(payload))});renderAnalytics(fetch,["tracking.read","tracking.manage"]);const opener=await screen.findByRole("button",{name:"创建追踪链接"});await userEvent.click(opener);expect(screen.getByRole("heading",{name:"创建追踪链接"})).toHaveFocus();const dialog=screen.getByRole("dialog");await userEvent.selectOptions(within(dialog).getByLabelText("已发布内容"),"task");const product=await within(dialog).findByLabelText("产品");expect(within(dialog).getByRole("button",{name:"创建"})).toBeDisabled();await userEvent.selectOptions(product,"product-b");await userEvent.type(within(dialog).getByLabelText("来源"),"linkedin");await userEvent.type(within(dialog).getByLabelText("活动标识"),"launch");await userEvent.click(within(dialog).getByRole("button",{name:"创建"}));expect(await screen.findByRole("status")).toHaveTextContent("追踪链接已创建");const call=fetch.mock.calls.find(item=>item[0]==="/api/v1/tracking-links"&&item[1]?.method==="POST")!;expect(JSON.parse(call[1].body)).toEqual({destination:"https://example.com/gear",utm_source:"linkedin",utm_medium:"social",utm_campaign:"launch",campaign_id:"campaign",platform_id:"platform",product_id:"product-b",published_post_id:"post"})})

it("uses independent guarded cursors for tracking, short, and published lists",async()=>{const fetch=vi.fn((path:string)=>{if(path.startsWith("/api/v1/analytics"))return Promise.resolve(json({count:0,total_clicks:0,next:null,previous:null,results:[]}));if(path==="/api/v1/tracking-links")return Promise.resolve(json({next:"/api/v1/tracking-links?cursor=t2",previous:null,results:[]}));if(path==="/api/v1/tracking-links?cursor=t2")return Promise.resolve(json({next:null,previous:"/api/v1/tracking-links",results:[{id:"t2",utm_campaign:"page two",full_url:"https://example.com/two"}]}));if(path==="/api/v1/short-links")return Promise.resolve(json({next:"/api/v1/short-links?cursor=s2",previous:null,results:[]}));if(path==="/api/v1/short-links?cursor=s2")return Promise.resolve(json({next:null,previous:"/api/v1/short-links",results:[{id:"s2",redirect_path:"/s/two"}]}));if(path==="/api/v1/publish-tasks")return Promise.resolve(json({next:"/api/v1/publish-tasks?cursor=p2",previous:null,results:[]}));if(path==="/api/v1/publish-tasks?cursor=p2")return Promise.resolve(json({next:null,previous:"/api/v1/publish-tasks",results:[{id:"p2",published_post:{id:"post",external_id:"published-two"}}]}));return Promise.resolve(json({next:null,previous:null,results:[]}))});renderAnalytics(fetch,["tracking.read","tracking.manage"]);for(const name of ["追踪链接分页","短链接分页","已发布内容分页"]){const nav=await screen.findByRole("navigation",{name});await userEvent.click(within(nav).getByRole("button",{name:"下一页"}))}expect(await screen.findByText("page two")).toBeInTheDocument();expect(await screen.findByText("/s/two")).toBeInTheDocument();expect(await screen.findByText("published-two")).toBeInTheDocument();expect(fetch).toHaveBeenCalledWith("/api/v1/tracking-links?cursor=t2",expect.anything());expect(fetch).toHaveBeenCalledWith("/api/v1/short-links?cursor=s2",expect.anything());expect(fetch).toHaveBeenCalledWith("/api/v1/publish-tasks?cursor=p2",expect.anything())})
