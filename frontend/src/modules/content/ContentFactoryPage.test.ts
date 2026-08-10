import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import { assetKeys } from "../assets/api"
import { productQueryKeys } from "../products/api"
import { contentQueryKeys } from "./api"
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
  if (["/api/v1/products?status=ACTIVE", "/api/v1/products"].includes(path)) return { next: null, previous: null, results: [{ id: "product-1", name_zh: "精密齿轮", name_en: "Precision Gear", status: "ACTIVE" }] }
  if (path === "/api/v1/platforms") return { results: [{ id: "platform-1", code: "LINKEDIN", name: "LinkedIn", capabilities: ["PUBLISH"] }] }
  if (["/api/v1/assets?status=ACTIVE", "/api/v1/assets"].includes(path)) return { next: null, previous: null, results: [] }
  if (path === "/api/v1/jobs") return { next: null, previous: null, results: [] }
  if (path === "/api/v1/master-contents") return { next: null, previous: null, results: [] }
  if (["/api/v1/knowledge/concepts?status=APPROVED&page_size=50", "/api/v1/knowledge/concepts?page_size=50"].includes(path)) return {
    next: null, previous: null, results: [
      { id: "concept-helical", code: "HELICAL_GEAR", concept_type: "PRODUCT_TYPE", label_zh: "斜齿轮", label_en: "Helical Gear", status: "APPROVED" },
      { id: "concept-grinding", code: "GRINDING", concept_type: "PROCESS", label_zh: "磨齿", label_en: "Grinding", status: "APPROVED" },
      { id: "concept-din", code: "DIN", concept_type: "STANDARD", label_zh: "DIN", label_en: "DIN", status: "APPROVED" },
      { id: "concept-packaging", code: "PACKAGING_MACHINERY", concept_type: "INDUSTRY", label_zh: "鍖呰鏈烘", label_en: "Packaging Machinery", status: "APPROVED" },
      { id: "concept-material", code: "42CRMO", concept_type: "MATERIAL", label_zh: "42CrMo", label_en: "42CrMo", status: "APPROVED" },
    ],
  }
  return { results: [] }
}

function renderPage(permissions: string[], experience?: "ordinary" | "advanced") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(permissions))
  const view = render(ContentFactoryPage, { props: { experience }, global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
  return Object.assign(view, { queryClient })
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("keeps the existing professional page available in advanced mode", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(baseResponse(path)), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "jobs.read"], "advanced")

  expect(await screen.findByRole("heading", { name: "内容需求" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "生成任务" })).toBeVisible()
  expect(screen.getByRole("button", { name: "创建内容任务" })).toBeVisible()
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
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "assets.read", "jobs.read", "knowledge.read", "memberships.read"])
  await screen.findByRole("heading", { name: "AI 内容工厂" })
  await user.click(screen.getByRole("button", { name: "创建内容任务" }))

  await user.click(screen.getByLabelText("快速新建活动"))
  await user.type(screen.getByLabelText("活动名称（必填）"), "德国获客")
  await user.type(screen.getByLabelText("活动说明"), "面向工业采购")
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(await screen.findByLabelText("精密齿轮"))
  await user.click(screen.getByLabelText("LinkedIn"))
  await user.click(screen.getByLabelText("Helical Gear (PRODUCT_TYPE)"))
  await user.click(screen.getByLabelText("Grinding (PROCESS)"))
  await user.click(screen.getByLabelText("DIN (STANDARD)"))
  await user.click(screen.getByLabelText("Packaging Machinery (INDUSTRY)"))
  expect(screen.queryByLabelText("42CrMo (MATERIAL)")).not.toBeInTheDocument()
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
      asset_ids: [], platform_ids: ["platform-1"], concept_links: [
        { role: "PRODUCT_TYPE", concept_id: "concept-helical" },
        { role: "MANUFACTURING_PROCESS", concept_id: "concept-grinding" },
        { role: "STANDARD", concept_id: "concept-din" },
        { role: "TARGET_INDUSTRY", concept_id: "concept-packaging" },
      ],
    } },
  ])
})

it("validates product/platform choices and respects the brief reviewer split", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(baseResponse(path, [brief()])), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "assets.read", "memberships.read"])
  await screen.findByText("等待审核人员确认")
  expect(screen.queryByRole("button", { name: "确认需求可生成" })).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "创建内容任务" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  expect(screen.getByRole("alert")).toHaveTextContent("请至少选择一个产品和一个平台")
})

it("loads one safe cursor page and selects products and assets from page two", async () => {
  const secondProduct = { id: "product-2", name_zh: "第二页齿轮", name_en: "Page Two Gear", status: "ACTIVE" }
  const secondAsset = { id: "asset-2", asset_type: "IMAGE", original_filename: "page-two.png", mime_type: "image/png", size_bytes: 10, language: "zh", status: "ACTIVE", tags: [], created_at: "" }
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/products") return new Response(JSON.stringify({ next: "/api/v1/products?cursor=two", previous: null, results: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/products?cursor=two") return new Response(JSON.stringify({ next: null, previous: "/api/v1/products", results: [secondProduct] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/assets") return new Response(JSON.stringify({ next: "/api/v1/assets?cursor=two", previous: null, results: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/assets?cursor=two") return new Response(JSON.stringify({ next: null, previous: "/api/v1/assets", results: [secondAsset] }), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "assets.read", "memberships.read"])
  await user.click(await screen.findByRole("button", { name: "创建内容任务" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))

  await user.click(await screen.findByRole("button", { name: "加载更多产品" }))
  await user.click(screen.getByRole("button", { name: "加载更多素材" }))

  expect(await screen.findByLabelText("第二页齿轮")).toBeInTheDocument()
  expect(screen.getByText("page-two.png")).toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([path]) => path === "/api/v1/products?cursor=two")).toHaveLength(1)
  expect(fetchMock.mock.calls.filter(([path]) => path === "/api/v1/assets?cursor=two")).toHaveLength(1)
  expect(screen.queryByRole("button", { name: "加载更多产品" })).not.toBeInTheDocument()
})

it("requires selling points, advantages, and keywords before confirmation", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(baseResponse(path)), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "memberships.read"])
  await user.click(await screen.findByRole("button", { name: "创建内容任务" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByLabelText("精密齿轮"))
  await user.click(screen.getByLabelText("LinkedIn"))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  for (const [label, value] of [
    ["目标国家（必填）", "德国"], ["客户类型（必填）", "采购"],
    ["内容目标（必填）", "询盘"], ["行动号召（必填）", "联系"],
    ["落地页（必填）", "https://example.com"], ["语言（必填）", "de"],
  ]) await user.type(screen.getByLabelText(label), value)

  await user.click(screen.getByRole("button", { name: "下一步" }))

  expect(screen.getByRole("alert")).toHaveTextContent("请检查需求信息中的必填项")
  expect(screen.getByLabelText("卖点")).toHaveFocus()
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

it("shows named product, platform, and job errors and recovers each query", async () => {
  const attempts = new Map<string, number>()
  const recoveredJob = { job_id: "job-recovered", type: "CONTENT_GENERATE", status: "SUCCEEDED", progress: 100, attempt: 1, max_attempts: 3, created_at: "", finished_at: "", error: null, result_reference: {} }
  const fetchMock = vi.fn(async (path: string) => {
    if (["/api/v1/products", "/api/v1/platforms", "/api/v1/jobs"].includes(path)) {
      const attempt = (attempts.get(path) ?? 0) + 1
      attempts.set(path, attempt)
      if (attempt === 1) return new Response(JSON.stringify({ detail: "temporary" }), { status: 503, headers: { "Content-Type": "application/json" } })
      if (path === "/api/v1/jobs") return new Response(JSON.stringify({ next: null, previous: null, results: [recoveredJob] }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "jobs.read", "memberships.read"])

  await user.click(await screen.findByRole("button", { name: "重新加载产品" }))
  await user.click(screen.getByRole("button", { name: "重新加载平台" }))
  await user.click(screen.getByRole("button", { name: "重新加载生成记录" }))

  expect(await screen.findByText("任务 job-recovered")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "创建内容任务" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  expect(await screen.findByLabelText("精密齿轮")).toBeInTheDocument()
  expect(screen.getByLabelText("LinkedIn")).toBeInTheDocument()
  expect(attempts).toEqual(new Map([
    ["/api/v1/products", 2], ["/api/v1/platforms", 2], ["/api/v1/jobs", 2],
  ]))
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

it("ignores an in-flight polling response after unmount without scheduling again", async () => {
  const activeJob = { job_id: "job-deferred", type: "CONTENT_GENERATE", status: "RUNNING", progress: 25, attempt: 1, max_attempts: 3, created_at: "", finished_at: null, error: null, result_reference: null }
  let resolveDetail!: (response: Response) => void
  const detail = new Promise<Response>((resolve) => { resolveDetail = resolve })
  const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout")
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/jobs") return new Response(JSON.stringify({ next: null, previous: null, results: [activeJob] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/jobs/job-deferred") return detail
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const view = renderPage(["campaigns.read", "jobs.read"])
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs/job-deferred", expect.anything()))

  view.unmount()
  resolveDetail(new Response(JSON.stringify(activeJob), { status: 200, headers: { "Content-Type": "application/json" } }))
  await detail
  await new Promise((resolve) => setTimeout(resolve, 0))

  expect(setTimeoutSpy.mock.calls.filter(([, delay]) => delay === 2500)).toHaveLength(0)
})

it("clears protected campaign, job, and content data when permissions are revoked live", async () => {
  const activeJob = { job_id: "job-private", type: "CONTENT_GENERATE", status: "SUCCEEDED", progress: 100, attempt: 1, max_attempts: 3, created_at: "", finished_at: "", error: null, result_reference: {} }
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/jobs") return new Response(JSON.stringify({ next: null, previous: null, results: [activeJob] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/master-contents") return new Response(JSON.stringify({ next: null, previous: null, results: [{ id: "master-private" }] }), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(baseResponse(path, [brief()])), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const view = renderPage(["campaigns.read", "campaigns.manage", "jobs.read", "content.read"], "advanced")
  const cancelQueries = vi.spyOn(view.queryClient, "cancelQueries")

  expect(await screen.findByText("任务 job-private")).toBeVisible()
  expect(screen.getAllByText(campaign.name)).toHaveLength(2)
  expect(screen.queryByText("master-private")).not.toBeInTheDocument()

  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(["campaigns.manage"]))

  await waitFor(() => {
    expect(screen.queryByText("任务 job-private")).not.toBeInTheDocument()
    expect(screen.queryByText(campaign.name)).not.toBeInTheDocument()
  })
  expect(within(screen.getByLabelText("当前工作摘要")).getAllByText("0")).toHaveLength(4)
  expect(cancelQueries).toHaveBeenCalledWith({ queryKey: contentQueryKeys.campaigns("org-1") })
  expect(cancelQueries).toHaveBeenCalledWith({ queryKey: contentQueryKeys.briefs("org-1") })
  expect(cancelQueries).toHaveBeenCalledWith({ queryKey: contentQueryKeys.jobs("org-1") })
  expect(cancelQueries).toHaveBeenCalledWith({ queryKey: contentQueryKeys.masterContents("org-1", {}) })
})

it.each([
  ["products.read", () => productQueryKeys.list("org-1", { status: "ACTIVE" })],
  ["assets.read", () => assetKeys.list("org-1", { status: "ACTIVE" })],
  ["knowledge.read", () => [...contentQueryKeys.briefs("org-1"), "approved-concepts"]],
  ["campaigns.manage", null],
] as const)("closes an open wizard immediately when %s is revoked", async (revokedPermission, queryKey) => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(baseResponse(path)), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const permissions = ["campaigns.read", "campaigns.manage", "products.read", "assets.read", "knowledge.read", "memberships.read"]
  const view = renderPage(permissions, "ordinary")
  const user = userEvent.setup()

  await user.click(await screen.findByRole("button", { name: "让 AI 给我方案" }))
  expect(screen.getByRole("dialog")).toBeVisible()
  if (queryKey) expect(view.queryClient.getQueryData(queryKey())).toBeDefined()

  view.queryClient.setQueryData(
    currentUserQueryOptions().queryKey,
    currentUser(permissions.filter((permission) => permission !== revokedPermission)),
  )

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  if (queryKey) expect(view.queryClient.getQueryData(queryKey())).toBeUndefined()
})

it("removes the product recovery action as soon as products.read is revoked", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path === "/api/v1/products?status=ACTIVE") {
      return new Response(JSON.stringify({ detail: "PRODUCT_BACKEND_FAILURE" }), {
        status: 500, headers: { "Content-Type": "application/json" },
      })
    }
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  }))
  const permissions = ["campaigns.read", "campaigns.manage", "products.read", "memberships.read"]
  const view = renderPage(permissions, "ordinary")

  expect(await screen.findByRole("button", { name: "重新检查产品资料" })).toBeVisible()
  view.queryClient.setQueryData(
    currentUserQueryOptions().queryKey,
    currentUser(permissions.filter((permission) => permission !== "products.read")),
  )

  await waitFor(() => expect(screen.queryByRole("button", { name: "重新检查产品资料" })).not.toBeInTheDocument())
})

it("ignores a deferred conflict refresh after jobs.read is revoked", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const failedJob = { job_id: "job-refresh-revoked", type: "CONTENT_GENERATE", status: "FAILED", progress: 60, attempt: 1, max_attempts: 3, created_at: "", finished_at: "", error: { message: "failed" }, result_reference: null }
  let resolveDetail!: (response: Response) => void
  const detail = new Promise<Response>((resolve) => { resolveDetail = resolve })
  let jobLists = 0
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/jobs") {
      jobLists += 1
      return new Response(JSON.stringify({ next: null, previous: null, results: jobLists === 1 ? [failedJob] : [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/retry") && options?.method === "POST") return new Response(JSON.stringify({ detail: "conflict" }), { status: 409, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/jobs/job-refresh-revoked") return detail
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const permissions = ["campaigns.read", "jobs.read", "jobs.manage"]
  const view = renderPage(permissions, "advanced")
  const user = userEvent.setup()

  await user.click(await screen.findByRole("button", { name: "重新尝试" }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs/job-refresh-revoked", expect.anything()))
  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(["campaigns.read", "jobs.manage"]))
  resolveDetail(new Response(JSON.stringify({ ...failedJob, status: "SUCCEEDED", progress: 100 }), { status: 200, headers: { "Content-Type": "application/json" } }))
  await detail
  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(permissions))

  await waitFor(() => expect(jobLists).toBe(2))
  expect(screen.queryByText("任务 job-refresh-revoked")).not.toBeInTheDocument()
})

it("hides backend cursor details behind a fixed ordinary-mode recovery", async () => {
  const backendDetail = "Invalid cursor JOB_CURSOR_EXPIRED_400"
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/jobs") return new Response(JSON.stringify({ next: "/api/v1/jobs?cursor=expired", previous: null, results: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/jobs?cursor=expired") return new Response(JSON.stringify({ detail: backendDetail }), { status: 400, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["jobs.read"], "ordinary")

  await user.click(screen.getByRole("button", { name: "查看高级记录" }))
  await user.click(await screen.findByRole("button", { name: "加载更多生成任务" }))

  const recovery = await screen.findByRole("alert")
  expect(recovery).toHaveTextContent("生成记录下一页暂时无法加载，请重新加载后再试。")
  expect(recovery).not.toHaveTextContent(backendDetail)
  expect(within(recovery).getByRole("button", { name: "重新加载更多生成记录" })).toBeVisible()
})

it("loads linked unavailable records into the advanced draft editor", async () => {
  const staleDraft = {
    ...brief(),
    product_ids: ["product-1", "product-archived"],
    asset_ids: ["asset-archived"],
    concept_links: [{ role: "STANDARD", concept_id: "concept-rejected" }],
  }
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/content-briefs") return new Response(JSON.stringify({ next: null, previous: null, results: [staleDraft] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/products") return new Response(JSON.stringify({ next: null, previous: null, results: [
      { id: "product-1", name_zh: "精密齿轮", name_en: "Precision Gear", status: "ACTIVE" },
      { id: "product-archived", name_zh: "旧产品", name_en: "Old product", status: "ARCHIVED" },
    ] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/assets") return new Response(JSON.stringify({ next: null, previous: null, results: [
      { id: "asset-archived", asset_type: "IMAGE", original_filename: "old-photo.png", mime_type: "image/png", size_bytes: 1, language: "zh", status: "ARCHIVED", tags: [], created_at: "" },
    ] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/knowledge/concepts?page_size=50") return new Response(JSON.stringify({ next: null, previous: null, results: [
      { id: "concept-rejected", code: "OLD", concept_type: "STANDARD", label_zh: "旧标准", label_en: "Old standard", status: "REJECTED" },
    ] }), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "assets.read", "knowledge.read", "memberships.read"], "advanced")

  await user.click(await screen.findByRole("button", { name: "编辑需求草稿" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))

  expect(await screen.findByLabelText("旧产品（不可用，仅可移除）")).toBeVisible()
  expect(screen.getByLabelText("old-photo.png（不可用，仅可移除）")).toBeVisible()
  expect(screen.getByLabelText("Old standard (STANDARD)（不可用，仅可移除）")).toBeVisible()
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/products", expect.anything())
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/assets", expect.anything())
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/knowledge/concepts?page_size=50", expect.anything())
})

it("stops an in-flight job poll and ignores its response when jobs.read is revoked", async () => {
  const activeJob = { job_id: "job-revoked", type: "CONTENT_GENERATE", status: "RUNNING", progress: 25, attempt: 1, max_attempts: 3, created_at: "", finished_at: null, error: null, result_reference: null }
  let resolveDetail!: (response: Response) => void
  const detail = new Promise<Response>((resolve) => { resolveDetail = resolve })
  const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout")
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/jobs") return new Response(JSON.stringify({ next: null, previous: null, results: [activeJob] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/jobs/job-revoked") return detail
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const view = renderPage(["campaigns.read", "jobs.read"], "advanced")

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs/job-revoked", expect.anything()))
  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(["campaigns.read"]))
  resolveDetail(new Response(JSON.stringify({ ...activeJob, status: "SUCCEEDED", progress: 100 }), { status: 200, headers: { "Content-Type": "application/json" } }))
  await detail

  await waitFor(() => expect(screen.queryByText("任务 job-revoked")).not.toBeInTheDocument())
  expect(setTimeoutSpy.mock.calls.filter(([, delay]) => delay === 2500)).toHaveLength(0)
})

it("ignores an in-flight job response after the organization changes", async () => {
  const activeJob = { job_id: "job-old-organization", type: "CONTENT_GENERATE", status: "RUNNING", progress: 25, attempt: 1, max_attempts: 3, created_at: "", finished_at: null, error: null, result_reference: null }
  let resolveDetail!: (response: Response) => void
  const detail = new Promise<Response>((resolve) => { resolveDetail = resolve })
  let jobLists = 0
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/jobs") {
      jobLists += 1
      return new Response(JSON.stringify({ next: null, previous: null, results: jobLists === 1 ? [activeJob] : [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/jobs/job-old-organization") return detail
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const key = currentUserQueryOptions().queryKey
  queryClient.setQueryData(key, currentUser(["campaigns.read", "jobs.read"]))
  render(ContentFactoryPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs/job-old-organization", expect.anything()))

  queryClient.setQueryData(key, {
    ...currentUser(["campaigns.read", "jobs.read"]),
    organization: { id: "org-2", name: "另一组织", slug: "other" },
  })
  await waitFor(() => expect(jobLists).toBe(2))
  resolveDetail(new Response(JSON.stringify({ ...activeJob, status: "SUCCEEDED", progress: 100 }), {
    status: 200, headers: { "Content-Type": "application/json" },
  }))
  await detail
  await new Promise((resolve) => setTimeout(resolve, 0))

  expect(screen.queryByText("任务 job-old-organization")).not.toBeInTheDocument()
})

it("edits a draft brief and creates a revision only with campaigns.manage", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const conceptLinks = [{ role: "APPLICATION", concept_id: "concept-1" }]
  const draft = { ...brief(), id: "brief-draft", concept_links: conceptLinks }
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
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "memberships.read"])
  await user.click(await screen.findByRole("button", { name: /编辑需求草稿/ }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  expect(screen.getByLabelText("精密齿轮")).toBeChecked()
  expect(screen.getByLabelText("LinkedIn")).toBeChecked()
  await user.click(screen.getByRole("button", { name: "下一步" }))
  const country = screen.getByLabelText(/目标国家/)
  await user.clear(country)
  await user.type(country, "法国")
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: /保存需求草稿/ }))
  await user.click(await screen.findByRole("button", { name: /创建需求修订版/ }))

  await waitFor(() => expect(writes).toEqual([
    { path: "/api/v1/content-briefs/brief-draft", method: "PATCH", body: {
      target_country: "法国", customer_type: draft.customer_type, content_objective: draft.content_objective,
      cta: draft.cta, landing_page_url: draft.landing_page_url, language: draft.language,
      prohibited_claims: draft.prohibited_claims, selling_points: draft.selling_points,
      advantages: draft.advantages, keywords: draft.keywords,
      product_ids: draft.product_ids, asset_ids: draft.asset_ids,
      platform_ids: draft.platform_ids, concept_links: conceptLinks,
    } },
    { path: "/api/v1/content-briefs/brief-ready/revisions", method: "POST", body: {} },
  ]))
  expect(screen.getByRole("dialog")).toHaveTextContent("编辑需求草稿")
})

it("does not reopen a deferred revision after campaigns.manage is revoked and restored before success", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const readyBrief = { ...brief("READY"), id: "brief-deferred-revision" }
  const revision = { ...readyBrief, id: "brief-late-revision", status: "DRAFT", version: 2 }
  let resolveRevision!: (response: Response) => void
  const deferredRevision = new Promise<Response>((resolve) => { resolveRevision = resolve })
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/content-briefs") return new Response(JSON.stringify({ next: null, previous: null, results: [readyBrief] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/content-briefs/brief-deferred-revision/revisions" && options?.method === "POST") return deferredRevision
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const permissions = ["campaigns.read", "campaigns.manage"]
  const view = renderPage(permissions, "advanced")
  const user = userEvent.setup()

  await user.click(await screen.findByRole("button", { name: "创建需求修订版" }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/content-briefs/brief-deferred-revision/revisions",
    expect.objectContaining({ method: "POST" }),
  ))
  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(["campaigns.read"]))
  await waitFor(() => expect(screen.queryByRole("button", { name: "创建需求修订版" })).not.toBeInTheDocument())
  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(permissions))
  await screen.findByRole("button", { name: "创建需求修订版" })

  resolveRevision(new Response(JSON.stringify(revision), { status: 201, headers: { "Content-Type": "application/json" } }))
  await deferredRevision
  await new Promise((resolve) => setTimeout(resolve, 0))

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  expect(screen.queryByText("已从可生成需求创建新的草稿版本，请检查并保存。")).not.toBeInTheDocument()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it("does not show a deferred revision error after campaigns.manage is revoked and restored", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const readyBrief = { ...brief("READY"), id: "brief-deferred-error" }
  let rejectRevision!: (reason?: unknown) => void
  const deferredRevision = new Promise<Response>((_resolve, reject) => { rejectRevision = reject })
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/content-briefs") return new Response(JSON.stringify({ next: null, previous: null, results: [readyBrief] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/content-briefs/brief-deferred-error/revisions" && options?.method === "POST") return deferredRevision
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const permissions = ["campaigns.read", "campaigns.manage"]
  const view = renderPage(permissions, "advanced")
  const user = userEvent.setup()

  await user.click(await screen.findByRole("button", { name: "创建需求修订版" }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/content-briefs/brief-deferred-error/revisions",
    expect.objectContaining({ method: "POST" }),
  ))
  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(["campaigns.read"]))
  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(permissions))
  await screen.findByRole("button", { name: "创建需求修订版" })

  rejectRevision(new Error("late revision failed"))
  await expect(deferredRevision).rejects.toThrow("late revision failed")
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(screen.queryByText("已从可生成需求创建新的草稿版本，请检查并保存。")).not.toBeInTheDocument()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it("opens a deferred revision when campaign management authority remains uninterrupted", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const readyBrief = { ...brief("READY"), id: "brief-uninterrupted-revision" }
  const revision = { ...readyBrief, id: "brief-current-revision", status: "DRAFT", version: 2 }
  let resolveRevision!: (response: Response) => void
  const deferredRevision = new Promise<Response>((resolve) => { resolveRevision = resolve })
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/content-briefs") return new Response(JSON.stringify({ next: null, previous: null, results: [readyBrief] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/content-briefs/brief-uninterrupted-revision/revisions" && options?.method === "POST") return deferredRevision
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage"], "advanced")

  await user.click(await screen.findByRole("button", { name: "创建需求修订版" }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/content-briefs/brief-uninterrupted-revision/revisions",
    expect.objectContaining({ method: "POST" }),
  ))
  resolveRevision(new Response(JSON.stringify(revision), { status: 201, headers: { "Content-Type": "application/json" } }))

  expect(await screen.findByRole("dialog")).toHaveTextContent("编辑需求草稿")
  expect(screen.getByText("已从可生成需求创建新的草稿版本，请检查并保存。")).toBeVisible()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it.each([
  ["organization", {
    ...currentUser(["campaigns.read", "campaigns.manage"]),
    organization: { id: "org-2", name: "另一组织", slug: "other" },
  }],
  ["membership", {
    ...currentUser(["campaigns.read", "campaigns.manage"]),
    membership: { ...currentUser(["campaigns.read", "campaigns.manage"]).membership, id: "member-2" },
  }],
])("does not reopen a deferred revision after a %s switch away and back", async (_authority, switchedUser) => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const permissions = ["campaigns.read", "campaigns.manage"]
  const readyBrief = { ...brief("READY"), id: "brief-session-switch" }
  const revision = { ...readyBrief, id: "brief-stale-session-revision", status: "DRAFT", version: 2 }
  let resolveRevision!: (response: Response) => void
  const deferredRevision = new Promise<Response>((resolve) => { resolveRevision = resolve })
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/content-briefs") return new Response(JSON.stringify({ next: null, previous: null, results: [readyBrief] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/content-briefs/brief-session-switch/revisions" && options?.method === "POST") return deferredRevision
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const view = renderPage(permissions, "advanced")
  const user = userEvent.setup()

  await user.click(await screen.findByRole("button", { name: "创建需求修订版" }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/content-briefs/brief-session-switch/revisions",
    expect.objectContaining({ method: "POST" }),
  ))
  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, switchedUser)
  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(permissions))
  resolveRevision(new Response(JSON.stringify(revision), { status: 201, headers: { "Content-Type": "application/json" } }))
  await deferredRevision
  await new Promise((resolve) => setTimeout(resolve, 0))

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(screen.queryByText("已从可生成需求创建新的草稿版本，请检查并保存。")).not.toBeInTheDocument()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it("traps focus in the draft editor, closes on Escape, and restores the opener", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(baseResponse(path, [brief()])), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage"])
  const opener = await screen.findByRole("button", { name: "编辑需求草稿" })
  await user.click(opener)

  const dialog = screen.getByRole("dialog")
  expect(within(dialog).getByRole("heading", { name: "编辑需求草稿" })).toHaveFocus()
  await user.tab({ shift: true })
  expect(within(dialog).getByRole("button", { name: "下一步" })).toHaveFocus()
  await user.keyboard("{Escape}")

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(opener).toHaveFocus()
})
