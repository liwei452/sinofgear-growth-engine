import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import ContentFactoryPage from "./ContentFactoryPage.vue"

const currentUser = (permissions: string[]): CurrentUser => ({
  user: { id: 1, username: "operator" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "CUSTOM", status: "ACTIVE", permissions },
})
const campaign = { id: "campaign-1", name: "德国获客", description: "", status: "DRAFT", version: 1, product_ids: [], created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z" }
const brief = (status = "DRAFT") => ({
  id: "brief-1", campaign_id: "campaign-1", previous_version_id: null, version: 1, status,
  target_country: "德国", customer_type: "工业采购", content_objective: "获取询盘", cta: "立即询价",
  landing_page_url: "https://example.com/de", language: "de", prohibited_claims: ["永不磨损"],
  selling_points: ["精密磨齿"], advantages: ["交期稳定"], keywords: ["精密齿轮"],
  product_ids: ["product-1"], asset_ids: [], platform_ids: ["platform-1"], concept_links: [],
  created_by: 1, reviewed_by: null, reviewed_at: null,
  created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
})

function baseResponse(path: string, activeBriefs: unknown[] = []) {
  if (path === "/api/v1/campaigns") return { next: null, previous: null, results: [campaign] }
  if (path === "/api/v1/content-briefs") return { next: null, previous: null, results: activeBriefs }
  if (path === "/api/v1/products") return { next: null, previous: null, results: [{ id: "product-1", name_zh: "精密齿轮", name_en: "Precision Gear", status: "ACTIVE" }] }
  if (path === "/api/v1/platforms") return { results: [{ id: "platform-1", code: "LINKEDIN", name: "LinkedIn", capabilities: ["PUBLISH"] }] }
  if (path === "/api/v1/assets") return { next: null, previous: null, results: [] }
  if (path === "/api/v1/jobs") return { next: null, previous: null, results: [] }
  if (path === "/api/v1/master-contents") return { next: null, previous: null, results: [] }
  return { results: [] }
}

function renderPage(permissions: string[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(permissions))
  return render(ContentFactoryPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("guides a beginner through campaign creation and sends the exact brief payload", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const bodies: Array<{ path: string; body: unknown }> = []
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST" && path === "/api/v1/campaigns") {
      bodies.push({ path, body: JSON.parse(String(options.body)) })
      return new Response(JSON.stringify(campaign), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    if (options?.method === "POST" && path === "/api/v1/content-briefs") {
      bodies.push({ path, body: JSON.parse(String(options.body)) })
      return new Response(JSON.stringify(brief()), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "assets.read", "jobs.read"])
  await screen.findByRole("heading", { name: "AI 内容工厂" })
  await user.click(screen.getByRole("button", { name: "创建内容任务" }))

  await user.click(screen.getByLabelText("快速新建活动"))
  await user.type(screen.getByLabelText("活动名称（必填）"), "德国获客")
  await user.type(screen.getByLabelText("活动说明"), "面向工业采购")
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(await screen.findByLabelText("精密齿轮"))
  await user.click(screen.getByLabelText("LinkedIn"))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.type(screen.getByLabelText("目标国家（必填）"), "德国")
  await user.type(screen.getByLabelText("客户类型（必填）"), "工业采购")
  await user.type(screen.getByLabelText("内容目标（必填）"), "获取询盘")
  await user.type(screen.getByLabelText("行动号召（必填）"), "立即询价")
  await user.type(screen.getByLabelText("落地页（必填）"), "https://example.com/de")
  await user.type(screen.getByLabelText("语言（必填）"), "de")
  await user.type(screen.getByLabelText("卖点"), "精密磨齿, 精密磨齿")
  await user.type(screen.getByLabelText("优势"), "交期稳定")
  await user.type(screen.getByLabelText("关键词"), "精密齿轮")
  await user.type(screen.getByLabelText("禁用说法"), "永不磨损")
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "创建需求草稿" }))

  await screen.findByText("内容需求已创建，等待审核人员确认。")
  expect(bodies).toEqual([
    { path: "/api/v1/campaigns", body: { name: "德国获客", description: "面向工业采购", status: "DRAFT", product_ids: [] } },
    { path: "/api/v1/content-briefs", body: {
      campaign_id: "campaign-1", target_country: "德国", customer_type: "工业采购",
      content_objective: "获取询盘", cta: "立即询价", landing_page_url: "https://example.com/de",
      language: "de", prohibited_claims: ["永不磨损"], selling_points: ["精密磨齿"],
      advantages: ["交期稳定"], keywords: ["精密齿轮"], product_ids: ["product-1"],
      asset_ids: [], platform_ids: ["platform-1"], concept_links: [],
    } },
  ])
})

it("validates product/platform choices and respects the brief reviewer split", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(baseResponse(path, [brief()])), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "assets.read"])
  await screen.findByText("等待审核人员确认")
  expect(screen.queryByRole("button", { name: "确认需求可生成" })).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "创建内容任务" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  expect(screen.getByRole("alert")).toHaveTextContent("请至少选择一个产品和一个平台")
})

it("starts generation only for READY briefs with content.manage and shows one job card", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/generate-master-content") && options?.method === "POST") {
      return new Response(JSON.stringify({ job_id: "job-1", status: "QUEUED" }), {
        status: 202, headers: { "Content-Type": "application/json" },
      })
    }
    if (path === "/api/v1/jobs/job-1") {
      return new Response(JSON.stringify({ job_id: "job-1", type: "CONTENT_GENERATE", status: "SUCCEEDED", progress: 100, attempt: 1, max_attempts: 3, created_at: "", finished_at: "", error: null, result_reference: {} }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    return new Response(JSON.stringify(baseResponse(path, [brief("READY")])), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "content.manage", "jobs.read", "jobs.manage"])
  await user.click(await screen.findByRole("button", { name: "开始AI生成" }))

  expect(await screen.findByText("生成完成")).toBeInTheDocument()
  expect(screen.getAllByText(/任务 job-1/)).toHaveLength(1)
  expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/generate-master-content"))).toHaveLength(1)
})

it("resumes an existing active job once and stops polling at a terminal state", async () => {
  const activeJob = { job_id: "job-existing", type: "CONTENT_GENERATE", status: "RUNNING", progress: 35, attempt: 1, max_attempts: 3, created_at: "", finished_at: null, error: null, result_reference: null }
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/jobs") return new Response(JSON.stringify({ next: null, previous: null, results: [activeJob] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/jobs/job-existing") return new Response(JSON.stringify({ ...activeJob, status: "SUCCEEDED", progress: 100, finished_at: "2026-08-09T00:01:00Z" }), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)

  renderPage(["campaigns.read", "jobs.read", "content.read"])

  await waitFor(() => expect(fetchMock.mock.calls.filter(([path]) => String(path).includes("job-existing"))).toHaveLength(1))
  expect(await screen.findByText("SUCCEEDED")).toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([path]) => path === "/api/v1/jobs/job-existing")).toHaveLength(1)
})

it("fetches fresh workflow data after the organization changes", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const fetchMock = vi.fn(async (path: string) => new Response(JSON.stringify(baseResponse(path)), {
    status: 200, headers: { "Content-Type": "application/json" },
  }))
  vi.stubGlobal("fetch", fetchMock)
  const key = currentUserQueryOptions().queryKey
  queryClient.setQueryData(key, currentUser(["campaigns.read"]))
  const first = render(ContentFactoryPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
  await screen.findByRole("heading", { level: 1 })
  await new Promise((resolve) => setTimeout(resolve, 0))
  first.unmount()

  queryClient.setQueryData(key, {
    ...currentUser(["campaigns.read"]),
    organization: { id: "org-2", name: "鍙︿竴缁勭粐", slug: "other" },
  })
  render(ContentFactoryPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
  await screen.findByRole("heading", { level: 1 })
  await new Promise((resolve) => setTimeout(resolve, 0))

  expect(fetchMock.mock.calls.filter(([path]) => path === "/api/v1/campaigns")).toHaveLength(2)
})

it("guards retry and refreshes a failed job after a conflict", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const failedJob = { job_id: "job-failed", type: "CONTENT_GENERATE", status: "FAILED", progress: 60, attempt: 1, max_attempts: 3, created_at: "", finished_at: "", error: { message: "failed" }, result_reference: null }
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/jobs") return new Response(JSON.stringify({ next: null, previous: null, results: [failedJob] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path.endsWith("/retry") && options?.method === "POST") return new Response(JSON.stringify({ detail: "conflict" }), { status: 409, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/jobs/job-failed") return new Response(JSON.stringify(failedJob), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "jobs.read", "jobs.manage"])
  await user.click(await screen.findByRole("button", { name: /重新尝试/ }))

  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => path === "/api/v1/jobs/job-failed")).toBe(true))
  expect(screen.getAllByRole("alert")).toHaveLength(2)
})

it("cancels polling timers on job cancellation and page unmount", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const activeJob = { job_id: "job-cancel", type: "CONTENT_GENERATE", status: "RUNNING", progress: 25, attempt: 1, max_attempts: 3, created_at: "", finished_at: null, error: null, result_reference: null }
  const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout")
  const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout")
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/jobs") return new Response(JSON.stringify({ next: null, previous: null, results: [activeJob] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path.endsWith("/cancel") && options?.method === "POST") return new Response(JSON.stringify({ ...activeJob, status: "CANCELED" }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/jobs/job-cancel") return new Response(JSON.stringify(activeJob), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  const view = renderPage(["campaigns.read", "jobs.read", "jobs.manage"])
  await waitFor(() => expect(setTimeoutSpy.mock.calls.some(([, delay]) => delay === 2500)).toBe(true))
  const timerIndex = setTimeoutSpy.mock.calls.findIndex(([, delay]) => delay === 2500)
  expect(timerIndex).toBeGreaterThanOrEqual(0)
  const pollingTimer = setTimeoutSpy.mock.results[timerIndex]?.value

  await user.click(screen.getByRole("button", { name: /取消任务/ }))
  expect(await screen.findByText("CANCELED")).toBeInTheDocument()
  expect(clearTimeoutSpy).toHaveBeenCalledWith(pollingTimer)
  view.unmount()
})

it("edits a draft brief and creates a revision only with campaigns.manage", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const draft = { ...brief(), id: "brief-draft" }
  const readyBrief = { ...brief("READY"), id: "brief-ready" }
  const writes: Array<{ path: string; method: string; body: unknown }> = []
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/content-briefs") return new Response(JSON.stringify({ next: null, previous: null, results: [draft, readyBrief] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/content-briefs/brief-draft" && options?.method === "PATCH") {
      writes.push({ path, method: "PATCH", body: JSON.parse(String(options.body)) })
      return new Response(JSON.stringify({ ...draft, ...JSON.parse(String(options.body)) }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/brief-ready/revisions") && options?.method === "POST") {
      writes.push({ path, method: "POST", body: JSON.parse(String(options.body)) })
      return new Response(JSON.stringify({ ...readyBrief, id: "brief-revision", status: "DRAFT", version: 2 }), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage"])
  await user.click(await screen.findByRole("button", { name: /编辑需求草稿/ }))
  const country = screen.getByLabelText(/目标国家/)
  await user.clear(country)
  await user.type(country, "法国")
  await user.click(screen.getByRole("button", { name: /保存需求草稿/ }))
  await user.click(await screen.findByRole("button", { name: /创建需求修订版/ }))

  await waitFor(() => expect(writes).toEqual([
    { path: "/api/v1/content-briefs/brief-draft", method: "PATCH", body: {
      target_country: "法国", customer_type: draft.customer_type, content_objective: draft.content_objective,
      cta: draft.cta, landing_page_url: draft.landing_page_url, language: draft.language,
    } },
    { path: "/api/v1/content-briefs/brief-ready/revisions", method: "POST", body: {} },
  ]))
})
