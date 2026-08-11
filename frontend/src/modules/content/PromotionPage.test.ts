import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import PromotionPage from "./PromotionPage.vue"

const currentUser = (permissions: string[]): CurrentUser => ({
  user: { id: 1, username: "operator" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "CUSTOM", status: "ACTIVE", permissions },
})

const campaign = {
  id: "campaign-1", name: "德国获客", description: "", status: "DRAFT", version: 1,
  product_ids: [], created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
}
const brief = {
  id: "brief-1", campaign_id: "campaign-1", previous_version_id: null, version: 1, status: "READY",
  target_country: "德国", customer_type: "工业采购", content_objective: "获取询盘", cta: "立即询价",
  landing_page_url: "https://example.com/de", language: "de", prohibited_claims: [], selling_points: ["精密磨齿"],
  advantages: ["交期稳定"], keywords: ["精密齿轮"], product_ids: ["product-1"], asset_ids: [],
  platform_ids: ["platform-1"], concept_links: [], created_by: 1, reviewed_by: 1,
  reviewed_at: "2026-08-09T00:00:00Z", created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
}
const failedJob = {
  job_id: "job-failed-raw-id", type: "CONTENT_GENERATE", status: "FAILED", progress: 60,
  attempt: 1, max_attempts: 3, created_at: "", finished_at: "", error: { message: "provider traceback" },
  result_reference: null,
}

function response(path: string, options: { products?: boolean; productsOnNextPage?: boolean; records?: boolean } = {}) {
  if (path === "/api/v1/campaigns") return { next: null, previous: null, results: options.records ? [campaign] : [] }
  if (path === "/api/v1/content-briefs") return { next: null, previous: null, results: options.records ? [brief] : [] }
  if (["/api/v1/products", "/api/v1/products?status=ACTIVE"].includes(path)) return {
    next: options.productsOnNextPage ? "/api/v1/products?status=ACTIVE&cursor=two" : null, previous: null,
    results: options.products === false || options.productsOnNextPage ? [] : [{ id: "product-1", name_zh: "精密齿轮", name_en: "Precision Gear", status: "ACTIVE" }],
  }
  if (path === "/api/v1/products?status=ACTIVE&cursor=two") return {
    next: null, previous: "/api/v1/products?status=ACTIVE",
    results: [{ id: "product-2", name_zh: "第二页齿轮", name_en: "Page Two Gear", status: "ACTIVE" }],
  }
  if (path === "/api/v1/platforms") return { results: [{ id: "platform-1", code: "LINKEDIN", name: "LinkedIn", capabilities: ["PUBLISH"] }] }
  if (["/api/v1/assets", "/api/v1/assets?status=ACTIVE"].includes(path)) return { next: null, previous: null, results: [] }
  if (path === "/api/v1/jobs") return { next: null, previous: null, results: options.records ? [failedJob] : [] }
  if (path === "/api/v1/master-contents") return { next: null, previous: null, results: [] }
  if (path === "/api/v1/knowledge/concepts?status=APPROVED&page_size=50") return { next: null, previous: null, results: [] }
  return { results: [] }
}

function renderPage(permissions: string[], options: { products?: boolean; productsOnNextPage?: boolean; records?: boolean; campaignError?: boolean } = {}) {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(response(path, options)), {
    status: options.campaignError && path === "/api/v1/campaigns" ? 503 : 200,
    headers: { "Content-Type": "application/json" },
  })))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(permissions))
  return render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
}

afterEach(() => vi.unstubAllGlobals())

it("starts with the user's goal instead of internal content objects", async () => {
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "assets.read", "knowledge.read", "jobs.read", "memberships.read"])

  expect(await screen.findByRole("heading", { name: "你今天想推广什么？" })).toBeVisible()
  expect(screen.getByText("选择产品")).toBeVisible()
  expect(screen.getByText("告诉 AI 目标")).toBeVisible()
  expect(screen.getByText("确认方案")).toBeVisible()
  expect(screen.getByRole("button", { name: "选择产品并继续" })).toBeVisible()
  await waitFor(() => expect(screen.getByRole("button", { name: "选择产品并继续" })).toBeEnabled())
  expect(screen.getByRole("button", { name: "查看高级记录" })).toBeVisible()
  expect(screen.queryByRole("heading", { name: "内容需求" })).not.toBeInTheDocument()
  expect(screen.queryByRole("heading", { name: "生成任务" })).not.toBeInTheDocument()
})

it("opens the real content brief wizard when the available data is ready", async () => {
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "memberships.read"])
  const action = await screen.findByRole("button", { name: "选择产品并继续" })
  await waitFor(() => expect(action).toBeEnabled())

  await user.click(action)

  expect(screen.getByRole("dialog")).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "制定推广方案" })).toBeInTheDocument()
})

it("keeps the proposal action honest when permission or required data is missing", async () => {
  const first = renderPage(["campaigns.read", "products.read", "memberships.read"])
  expect(await screen.findByText("你当前没有创建推广方案的权限，请联系管理员。")).toBeVisible()
  expect(screen.queryByRole("button", { name: "选择产品并继续" })).not.toBeInTheDocument()
  first.unmount()

  renderPage(["campaigns.read", "campaigns.manage", "products.read", "memberships.read"], { products: false })
  const action = await screen.findByRole("button", { name: "选择产品并继续" })
  await waitFor(() => expect(action).toBeDisabled())
  expect(await screen.findByText("产品库还没有可推广的产品，请先补充产品资料。")).toBeVisible()
})

it("requires an empty first product page to be loaded before opening the wizard", async () => {
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "memberships.read"], { productsOnNextPage: true })

  const action = await screen.findByRole("button", { name: "选择产品并继续" })
  await waitFor(() => expect(action).toBeDisabled())
  expect(await screen.findByText("还有产品资料未加载，请先加载后再继续。")).toBeVisible()
  await user.click(screen.getByRole("button", { name: "加载更多产品资料" }))
  await waitFor(() => expect(action).toBeEnabled())
})

it("offers an ordinary recovery action when existing promotion records fail to load", async () => {
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "memberships.read"], { campaignError: true })

  expect(await screen.findByText("已有推广资料暂时没有加载成功，请重新检查后再试。")).toBeVisible()
  expect(screen.getByRole("button", { name: "重新检查已有推广资料" })).toBeVisible()
})

it("reveals real records on request with plain Chinese job labels and recovery", async () => {
  const user = userEvent.setup()
  renderPage([
    "campaigns.read", "campaigns.manage", "products.read", "jobs.read", "jobs.manage", "content.read", "memberships.read",
  ], { records: true })
  await screen.findByRole("heading", { name: "你今天想推广什么？" })
  expect(screen.queryByText("德国获客")).not.toBeInTheDocument()
  expect(screen.queryByText("job-failed-raw-id")).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "查看高级记录" }))

  expect(await screen.findAllByText("德国获客")).toHaveLength(2)
  expect(screen.getByRole("heading", { name: "内容需求" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "生成任务" })).toBeVisible()
  expect(screen.getByText("生成未完成")).toBeVisible()
  expect(screen.getByRole("button", { name: "再次尝试" })).toBeVisible()
  expect(screen.queryByText("job-failed-raw-id")).not.toBeInTheDocument()
  expect(screen.queryByText("FAILED")).not.toBeInTheDocument()
  expect(screen.queryByText("provider traceback")).not.toBeInTheDocument()
})

it("does not fetch or poll hidden jobs and keeps polling errors inside advanced records", async () => {
  const activeJob = { ...failedJob, job_id: "job-hidden", status: "RUNNING", progress: 20, finished_at: null, error: null }
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/jobs") return new Response(JSON.stringify({ next: null, previous: null, results: [activeJob] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/jobs/job-hidden") return new Response(JSON.stringify({ detail: "Not found." }), { status: 500, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(response(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(["campaigns.read", "campaigns.manage", "products.read", "memberships.read", "jobs.read"]))
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const action = await screen.findByRole("button", { name: "选择产品并继续" })
  await waitFor(() => expect(action).toBeEnabled())
  expect(fetchMock.mock.calls.some(([path]) => path === "/api/v1/jobs")).toBe(false)
  expect(fetchMock.mock.calls.some(([path]) => path === "/api/v1/jobs/job-hidden")).toBe(false)
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "查看高级记录" }))

  expect(await screen.findByText("生成记录暂时无法更新，请重新加载后再试。")).toBeVisible()
  expect(screen.getByRole("button", { name: "重新加载生成记录" })).toBeVisible()
  expect(screen.queryByText("Not found.")).not.toBeInTheDocument()
})

it("requests active products and assets and filters inactive records at the page boundary", async () => {
  const activeProduct = { id: "product-active", name_zh: "可推广齿轮", name_en: "Active Gear", status: "ACTIVE" }
  const archivedProduct = { id: "product-archived", name_zh: "已归档齿轮", name_en: "Archived Gear", status: "ARCHIVED" }
  const activeAsset = { id: "asset-active", asset_type: "IMAGE", original_filename: "active.png", mime_type: "image/png", size_bytes: 10, language: "zh", status: "ACTIVE", tags: [], created_at: "" }
  const archivedAsset = { ...activeAsset, id: "asset-archived", original_filename: "archived.png", status: "ARCHIVED" }
  const fetchMock = vi.fn(async (path: string) => {
    if (path.startsWith("/api/v1/products")) return new Response(JSON.stringify({ next: "/api/v1/products?status=ACTIVE&cursor=two", previous: null, results: [activeProduct, archivedProduct] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path.startsWith("/api/v1/assets")) return new Response(JSON.stringify({ next: null, previous: null, results: [activeAsset, archivedAsset] }), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(response(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(["campaigns.read", "campaigns.manage", "products.read", "assets.read", "memberships.read"]))
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const action = await screen.findByRole("button", { name: "选择产品并继续" })
  await waitFor(() => expect(action).toBeEnabled())
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/products?status=ACTIVE", expect.anything())
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/assets?status=ACTIVE", expect.anything())
  expect(within(screen.getByText("可推广产品").closest("article")!).getByText("已加载 1 项")).toBeVisible()
  expect(within(screen.getByText("可用素材").closest("article")!).getByText("已加载 1 项")).toBeVisible()

  await user.click(action)
  expect(screen.getByLabelText("可推广齿轮")).toBeVisible()
  expect(screen.queryByLabelText("已归档齿轮")).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "加载更多产品" })).toBeVisible()
  await user.click(screen.getByLabelText("可推广齿轮"))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.selectOptions(screen.getByLabelText("目标市场（必选）"), "德国")
  await user.selectOptions(screen.getByLabelText("目标客户（必选）"), "工业采购")
  await user.selectOptions(screen.getByLabelText("推广目标（必选）"), "获取询盘")
  await user.selectOptions(screen.getByLabelText("希望客户下一步（必选）"), "立即询价")
  await user.selectOptions(screen.getByLabelText("内容语言（必选）"), "de")
  await user.click(screen.getByLabelText("LinkedIn"))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  expect(screen.getByText("active.png")).toBeVisible()
  expect(screen.queryByText("archived.png")).not.toBeInTheDocument()
})

it("blocks platform definitions without memberships.read and does not request them", async () => {
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/platforms") return new Response(JSON.stringify({ detail: "forbidden" }), { status: 403, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(response(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(["campaigns.read", "campaigns.manage", "products.read"]))
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const action = await screen.findByRole("button", { name: "选择产品并继续" })
  await waitFor(() => expect(action).toBeDisabled())
  expect(screen.getByText("需要组织成员查看权限，才能读取平台定义。")).toBeVisible()
  expect(fetchMock.mock.calls.some(([path]) => path === "/api/v1/platforms")).toBe(false)
  expect(screen.getByText("来自系统支持的渠道定义，不代表账号已连接")).toBeVisible()
})

it("counts and offers only approved knowledge when the backend returns mixed statuses", async () => {
  const approved = { id: "concept-approved", code: "APPROVED_GEAR", concept_type: "PRODUCT_TYPE", label_zh: "已批准齿轮", label_en: "Approved Gear", status: "APPROVED" }
  const rejected = { id: "concept-rejected", code: "REJECTED_GEAR", concept_type: "PRODUCT_TYPE", label_zh: "已拒绝齿轮", label_en: "Rejected Gear", status: "REJECTED" }
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/knowledge/concepts?status=APPROVED&page_size=50") return new Response(JSON.stringify({ next: null, previous: null, results: [approved, rejected] }), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(response(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(["campaigns.read", "campaigns.manage", "products.read", "memberships.read", "knowledge.read"]))
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const action = await screen.findByRole("button", { name: "选择产品并继续" })
  await waitFor(() => expect(action).toBeEnabled())
  expect(within(screen.getByText("已批准知识").closest("article")!).getByText("已加载 1 项")).toBeVisible()

  await user.click(action)
  await user.click(screen.getByLabelText("精密齿轮"))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.selectOptions(screen.getByLabelText("目标市场（必选）"), "德国")
  await user.selectOptions(screen.getByLabelText("目标客户（必选）"), "工业采购")
  await user.selectOptions(screen.getByLabelText("推广目标（必选）"), "获取询盘")
  await user.selectOptions(screen.getByLabelText("希望客户下一步（必选）"), "立即询价")
  await user.selectOptions(screen.getByLabelText("内容语言（必选）"), "de")
  await user.click(screen.getByLabelText("LinkedIn"))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  expect(screen.getByLabelText("Approved Gear (PRODUCT_TYPE)")).toBeVisible()
  expect(screen.queryByLabelText("Rejected Gear (PRODUCT_TYPE)")).not.toBeInTheDocument()
})

it("shows the six real promotion steps and expands only the current one", async () => {
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "assets.read", "memberships.read"])

  expect(await screen.findByRole("heading", { name: "你今天想推广什么？" })).toBeVisible()
  for (const title of ["选择产品", "告诉 AI 目标", "查看可用素材", "确认方案", "生成内容", "批准发布"]) {
    expect(screen.getByRole("heading", { name: title })).toBeVisible()
  }
  expect(screen.getByRole("region", { name: "选择产品" })).toHaveAttribute("aria-current", "step")
  expect(screen.queryByRole("region", { name: "告诉 AI 目标" })).not.toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole("button", { name: "选择产品并继续" })).toBeEnabled())
  expect(screen.queryByText(/Campaign|ContentBrief|MasterContent|PlatformContent/)).not.toBeInTheDocument()
})

it("persists the preset beginner flow through the real campaign and brief contracts", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const writes: Array<{ path: string; body: Record<string, unknown> }> = []
  vi.stubGlobal("fetch", vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      const body = JSON.parse(String(options.body)) as Record<string, unknown>
      writes.push({ path, body })
      return new Response(JSON.stringify(path === "/api/v1/campaigns" ? campaign : brief), {
        status: 201, headers: { "Content-Type": "application/json" },
      })
    }
    return new Response(JSON.stringify(response(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser([
    "campaigns.read", "campaigns.manage", "products.read", "assets.read", "memberships.read",
  ]))
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const start = await screen.findByRole("button", { name: "选择产品并继续" })
  await waitFor(() => expect(start).toBeEnabled())
  await user.click(start)
  await user.click(screen.getByLabelText("精密齿轮"))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.selectOptions(screen.getByLabelText("目标市场（必选）"), "德国")
  await user.selectOptions(screen.getByLabelText("目标客户（必选）"), "工业采购")
  await user.selectOptions(screen.getByLabelText("推广目标（必选）"), "获取询盘")
  await user.selectOptions(screen.getByLabelText("希望客户下一步（必选）"), "立即询价")
  await user.selectOptions(screen.getByLabelText("内容语言（必选）"), "de")
  await user.click(screen.getByLabelText("LinkedIn"))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "精密制造" }))
  await user.click(screen.getByRole("button", { name: "质量可追溯" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "保存推广方案" }))

  await waitFor(() => expect(writes.map((item) => item.path)).toEqual(["/api/v1/campaigns", "/api/v1/content-briefs"]))
  expect(writes[0].body).toEqual({ name: "精密齿轮推广", description: "德国 · 获取询盘", status: "DRAFT", product_ids: [] })
  expect(writes[1].body).toEqual(expect.objectContaining({
    campaign_id: "campaign-1", product_ids: ["product-1"], platform_ids: ["platform-1"],
    target_country: "德国", customer_type: "工业采购", content_objective: "获取询盘",
    selling_points: ["精密制造"], advantages: ["质量可追溯"], keywords: ["精密齿轮"],
  }))
})
