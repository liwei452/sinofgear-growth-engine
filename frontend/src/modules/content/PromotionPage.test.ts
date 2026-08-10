import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
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
  if (path === "/api/v1/products") return {
    next: options.productsOnNextPage ? "/api/v1/products?cursor=two" : null, previous: null,
    results: options.products === false || options.productsOnNextPage ? [] : [{ id: "product-1", name_zh: "精密齿轮", name_en: "Precision Gear", status: "ACTIVE" }],
  }
  if (path === "/api/v1/platforms") return { results: [{ id: "platform-1", code: "LINKEDIN", name: "LinkedIn", capabilities: ["PUBLISH"] }] }
  if (path === "/api/v1/assets") return { next: null, previous: null, results: [] }
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
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "assets.read", "knowledge.read", "jobs.read"])

  expect(await screen.findByRole("heading", { name: "你今天想推广什么？" })).toBeVisible()
  expect(screen.getByText("选择推广目标")).toBeVisible()
  expect(screen.getByText("确认 AI 方案")).toBeVisible()
  expect(screen.getByText("批准后执行")).toBeVisible()
  expect(screen.getByRole("button", { name: "让 AI 给我方案" })).toBeVisible()
  await waitFor(() => expect(screen.getByRole("button", { name: "让 AI 给我方案" })).toBeEnabled())
  expect(screen.getByRole("button", { name: "查看高级记录" })).toBeVisible()
  expect(screen.queryByRole("heading", { name: "内容需求" })).not.toBeInTheDocument()
  expect(screen.queryByRole("heading", { name: "生成任务" })).not.toBeInTheDocument()
})

it("opens the real content brief wizard when the available data is ready", async () => {
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read"])
  const action = await screen.findByRole("button", { name: "让 AI 给我方案" })
  await waitFor(() => expect(action).toBeEnabled())

  await user.click(action)

  expect(screen.getByRole("dialog")).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "创建内容任务" })).toBeInTheDocument()
})

it("keeps the proposal action honest when permission or required data is missing", async () => {
  const first = renderPage(["campaigns.read", "products.read"])
  expect(await screen.findByText("你当前没有创建推广方案的权限，请联系管理员。")).toBeVisible()
  expect(screen.queryByRole("button", { name: "让 AI 给我方案" })).not.toBeInTheDocument()
  first.unmount()

  renderPage(["campaigns.read", "campaigns.manage", "products.read"], { products: false })
  const action = await screen.findByRole("button", { name: "让 AI 给我方案" })
  await waitFor(() => expect(action).toBeDisabled())
  expect(await screen.findByText("产品库还没有可推广的产品，请先补充产品资料。")).toBeVisible()
})

it("allows the real wizard to load products from a known next page", async () => {
  renderPage(["campaigns.read", "campaigns.manage", "products.read"], { productsOnNextPage: true })

  const action = await screen.findByRole("button", { name: "让 AI 给我方案" })
  await waitFor(() => expect(action).toBeEnabled())
  expect(screen.queryByText("产品库还没有可推广的产品，请先补充产品资料。")).not.toBeInTheDocument()
})

it("offers an ordinary recovery action when existing promotion records fail to load", async () => {
  renderPage(["campaigns.read", "campaigns.manage", "products.read"], { campaignError: true })

  expect(await screen.findByText("已有推广资料暂时没有加载成功，请重新检查后再试。")).toBeVisible()
  expect(screen.getByRole("button", { name: "重新检查已有推广资料" })).toBeVisible()
})

it("reveals real records on request with plain Chinese job labels and recovery", async () => {
  const user = userEvent.setup()
  renderPage([
    "campaigns.read", "campaigns.manage", "products.read", "jobs.read", "jobs.manage", "content.read",
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
