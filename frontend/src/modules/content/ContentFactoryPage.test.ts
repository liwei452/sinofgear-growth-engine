import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import { assetKeys } from "../assets/api"
import { productQueryKeys } from "../products/api"
import { contentQueryKeys } from "./api"
import "../../styles/tokens.css"
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
  vi.useRealTimers()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("uses the shared SinofGear blue tint for the ordinary promotion header", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(baseResponse(path)), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const view = renderPage([], "ordinary")

  await screen.findByRole("heading", { name: "你今天想推广什么？" })
  expect(getComputedStyle(view.container.querySelector(".promotion-header")!).backgroundColor).toBe("var(--sg-brand-tint)")
  expect(getComputedStyle(document.documentElement).getPropertyValue("--sg-brand-tint").trim()).toBe("#e8f2fa")
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

it("keeps ordinary advanced-record pagination safe and retryable after a 403", async () => {
  const privateUuid = "91a34e74-bfad-4e4c-8753-9475df12dbb2"
  const rawMessage = `Campaign access denied for ${privateUuid}`
  let attempts = 0
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/campaigns") return new Response(JSON.stringify({
      next: "/api/v1/campaigns?cursor=two", previous: null, results: [campaign],
    }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/campaigns?cursor=two") {
      attempts += 1
      return attempts === 1
        ? new Response(JSON.stringify({
            code: "PERMISSION_DENIED", message: rawMessage,
            recovery_action: "Contact your administrator and retry",
          }), { status: 403, headers: { "Content-Type": "application/json" } })
        : new Response(JSON.stringify({
            next: null, previous: "/api/v1/campaigns", results: [{ ...campaign, id: "campaign-2", name: "第二项推广" }],
          }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read"], "ordinary")

  await user.click(await screen.findByRole("button", { name: "查看高级记录" }))
  await user.click(screen.getByRole("button", { name: "加载更多推广活动" }))

  const recovery = await screen.findByRole("alert")
  expect(recovery).toHaveTextContent("下一页没有加载成功，请重试。")
  expect(document.body).not.toHaveTextContent("PERMISSION_DENIED")
  expect(document.body).not.toHaveTextContent("Contact your administrator")
  expect(document.body).not.toHaveTextContent(rawMessage)
  expect(document.body).not.toHaveTextContent(privateUuid)
  expect(screen.getByText(campaign.name)).toBeVisible()

  await user.click(within(recovery).getByRole("button", { name: "重试" }))
  expect(await screen.findByText("第二项推广")).toBeVisible()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it("keeps product, asset, and knowledge page errors safe in the ordinary wizard and clears them after retry", async () => {
  const privateUuid = "28a977bf-27c8-47d5-982b-dd308dcb2c65"
  const productRaw = `Invalid product_ids[0] ${privateUuid}`
  const assetRaw = `Invalid asset_ids[0] ${privateUuid}`
  const conceptRaw = `Invalid concept_links[0].concept_id ${privateUuid}`
  const attempts = { products: 0, assets: 0, concepts: 0 }
  const secondProduct = { id: "product-2", name_zh: "第二页齿轮", name_en: "Page Two Gear", status: "ACTIVE" }
  const secondAsset = { id: "asset-2", asset_type: "IMAGE", original_filename: "page-two.png", mime_type: "image/png", size_bytes: 10, language: "zh", status: "ACTIVE", tags: [], created_at: "" }
  const secondConcept = { id: "concept-2", code: "ISO_1328", concept_type: "STANDARD", label_zh: "ISO 1328", label_en: "ISO 1328", status: "APPROVED" }
  const badPage = (message: string) => new Response(JSON.stringify({
    code: "VALIDATION_ERROR", message, errors: { raw_field: [message] },
  }), { status: 400, headers: { "Content-Type": "application/json" } })
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/products?status=ACTIVE") return new Response(JSON.stringify({
      next: "/api/v1/products?status=ACTIVE&cursor=two", previous: null,
      results: [{ id: "product-1", name_zh: "精密齿轮", name_en: "Precision Gear", status: "ACTIVE" }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/products?status=ACTIVE&cursor=two") {
      attempts.products += 1
      return attempts.products === 1 ? badPage(productRaw) : new Response(JSON.stringify({
        next: null, previous: "/api/v1/products?status=ACTIVE", results: [secondProduct],
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/assets?status=ACTIVE") return new Response(JSON.stringify({
      next: "/api/v1/assets?status=ACTIVE&cursor=two", previous: null, results: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/assets?status=ACTIVE&cursor=two") {
      attempts.assets += 1
      return attempts.assets === 1 ? badPage(assetRaw) : new Response(JSON.stringify({
        next: null, previous: "/api/v1/assets?status=ACTIVE", results: [secondAsset],
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/knowledge/concepts?status=APPROVED&page_size=50") return new Response(JSON.stringify({
      next: "/api/v1/knowledge/concepts?status=APPROVED&page_size=50&cursor=two", previous: null,
      results: [{ id: "concept-1", code: "DIN", concept_type: "STANDARD", label_zh: "DIN", label_en: "DIN", status: "APPROVED" }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/knowledge/concepts?status=APPROVED&page_size=50&cursor=two") {
      attempts.concepts += 1
      return attempts.concepts === 1 ? badPage(conceptRaw) : new Response(JSON.stringify({
        next: null, previous: "/api/v1/knowledge/concepts?status=APPROVED&page_size=50", results: [secondConcept],
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.manage", "products.read", "assets.read", "knowledge.read", "memberships.read"], "ordinary")

  await user.click(await screen.findByRole("button", { name: "选择产品并继续" }))
  const products = screen.getByRole("group", { name: "这次推广什么？" })
  await user.click(within(products).getByRole("button", { name: "加载更多产品" }))
  let recovery = await within(products).findByRole("alert")
  expect(recovery).toHaveTextContent("下一页没有加载成功，请重试。")
  expect(document.body).not.toHaveTextContent(productRaw)
  expect(document.body).not.toHaveTextContent("raw_field")
  await user.click(within(recovery).getByRole("button", { name: "重试" }))
  expect(await screen.findByLabelText("第二页齿轮")).toBeVisible()
  expect(within(products).queryByRole("alert")).not.toBeInTheDocument()

  await user.click(screen.getByLabelText("精密齿轮"))
  await user.click(screen.getByRole("button", { name: "保存产品并继续" }))
  await user.selectOptions(screen.getByLabelText("目标市场（必选）"), "德国")
  await user.selectOptions(screen.getByLabelText("目标客户（必选）"), "工业采购")
  await user.selectOptions(screen.getByLabelText("推广目标（必选）"), "获取询盘")
  await user.selectOptions(screen.getByLabelText("希望客户下一步（必选）"), "立即询价")
  await user.selectOptions(screen.getByLabelText("内容语言（必选）"), "de")
  await user.click(screen.getByLabelText("LinkedIn"))
  await user.click(screen.getByRole("button", { name: "保存目标并查看素材" }))

  const assets = screen.getByRole("group", { name: "可选素材" })
  const concepts = screen.getByRole("group", { name: "已批准知识（可选）" })
  await user.click(within(assets).getByRole("button", { name: "加载更多素材" }))
  recovery = await within(assets).findByRole("alert")
  expect(recovery).toHaveTextContent("下一页没有加载成功，请重试。")
  expect(document.body).not.toHaveTextContent(assetRaw)
  await user.click(within(concepts).getByRole("button", { name: "加载更多知识" }))
  const conceptRecovery = await within(concepts).findByRole("alert")
  expect(conceptRecovery).toHaveTextContent("下一页没有加载成功，请重试。")
  expect(document.body).not.toHaveTextContent(conceptRaw)
  expect(document.body).not.toHaveTextContent(privateUuid)

  await user.click(within(recovery).getByRole("button", { name: "重试" }))
  await user.click(within(conceptRecovery).getByRole("button", { name: "重试" }))
  expect(await screen.findByText("page-two.png")).toBeVisible()
  expect(await screen.findByLabelText("ISO 1328 (STANDARD)")).toBeVisible()
  expect(within(assets).queryByRole("alert")).not.toBeInTheDocument()
  expect(within(concepts).queryByRole("alert")).not.toBeInTheDocument()
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

  await user.click(await screen.findByRole("button", { name: "选择产品并继续" }))
  expect(screen.getByRole("dialog")).toBeVisible()
  if (queryKey) expect(view.queryClient.getQueryData(queryKey())).toBeDefined()

  view.queryClient.setQueryData(
    currentUserQueryOptions().queryKey,
    currentUser(permissions.filter((permission) => permission !== revokedPermission)),
  )

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  if (queryKey) expect(view.queryClient.getQueryData(queryKey())).toBeUndefined()
})

it("aborts and clears the captured all-concepts query when knowledge access is revoked during editing", async () => {
  const draft = brief()
  let resolveConcepts!: (response: Response) => void
  const deferredConcepts = new Promise<Response>((resolve) => { resolveConcepts = resolve })
  let allConceptsSignal: AbortSignal | undefined
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/content-briefs") return new Response(JSON.stringify({ next: null, previous: null, results: [draft] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/knowledge/concepts?page_size=50") {
      allConceptsSignal = options?.signal ?? undefined
      return deferredConcepts
    }
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const permissions = ["campaigns.read", "campaigns.manage", "products.read", "assets.read", "knowledge.read", "memberships.read"]
  const view = renderPage(permissions, "ordinary")
  const allConceptsKey = [...contentQueryKeys.briefs("org-1"), "all-concepts"]

  await userEvent.click(await screen.findByRole("button", { name: "查看并修改方案" }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/knowledge/concepts?page_size=50",
    expect.objectContaining({ signal: expect.anything() }),
  ))
  view.queryClient.setQueryData(allConceptsKey, {
    next: null, previous: null, results: [{ id: "private-concept", label_zh: "不应保留" }],
  })

  view.queryClient.setQueryData(
    currentUserQueryOptions().queryKey,
    currentUser(permissions.filter((permission) => permission !== "knowledge.read")),
  )

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  expect(allConceptsSignal?.aborted).toBe(true)
  expect(view.queryClient.getQueryData(allConceptsKey)).toBeUndefined()
  resolveConcepts(new Response(JSON.stringify({ next: null, previous: null, results: [{ id: "late-private-concept" }] }), {
    status: 200, headers: { "Content-Type": "application/json" },
  }))
  await deferredConcepts
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(view.queryClient.getQueryData(allConceptsKey)).toBeUndefined()
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

it("keeps a new draft current when an older promotion already has generated content", async () => {
  const oldReady = { ...brief("READY"), id: "brief-old", version: 99, updated_at: "2026-08-01T00:00:00Z" }
  const newDraft = { ...brief("DRAFT"), id: "brief-new", campaign_id: "campaign-new", version: 1, updated_at: "2026-08-11T00:00:00Z" }
  const oldMaster = {
    id: "master-old", brief_id: "brief-old", brief_version: 99, generation_job_id: "job-old", ai_run_id: "run-old",
    lineage_id: "lineage-old", previous_version_id: null, version: 1,
    payload: { title: "旧推广内容", body: "旧内容", cta: "询价", concept_codes: [] }, provenance: {},
    status: "IN_REVIEW", is_current_head: true, created_by_id: 1, created_at: "", updated_at: "",
  }
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    const body = path === "/api/v1/content-briefs" ? { next: null, previous: null, results: [oldReady, newDraft] }
      : path === "/api/v1/master-contents" ? { next: null, previous: null, results: [oldMaster] }
        : baseResponse(path)
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })
  }))
  renderPage(["campaigns.read", "campaigns.manage", "campaigns.review", "content.read", "products.read", "memberships.read"], "ordinary")

  expect(await screen.findByRole("region", { name: "确认方案" })).toHaveAttribute("aria-current", "step")
  expect(screen.queryByRole("region", { name: "批准发布" })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "查看并修改方案" })).toBeVisible()
})

it("polls a submitted ordinary job while advanced records stay collapsed and prevents duplicate generation", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let resolveJob!: (response: Response) => void
  const jobDetail = new Promise<Response>((resolve) => { resolveJob = resolve })
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/generate-master-content") && options?.method === "POST") {
      return new Response(JSON.stringify({ job_id: "job-ordinary", status: "QUEUED" }), { status: 202, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/jobs/job-ordinary") return jobDetail
    return new Response(JSON.stringify(baseResponse(path, [brief("READY")])), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  const view = renderPage(["campaigns.read", "content.manage", "content.read", "jobs.read"], "ordinary")

  const generate = await screen.findByRole("button", { name: "生成推广内容" })
  await user.click(generate)
  expect(await screen.findByText("等待开始")).toBeVisible()
  expect(screen.getByRole("button", { name: "生成推广内容" })).toBeDisabled()
  expect(screen.getByRole("button", { name: "查看高级记录" })).toHaveAttribute("aria-expanded", "false")
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs/job-ordinary", expect.anything()))
  await user.click(screen.getByRole("button", { name: "生成推广内容" }))
  expect(fetchMock.mock.calls.filter(([path, options]) => String(path).endsWith("/generate-master-content") && options?.method === "POST")).toHaveLength(1)

  view.unmount()
  resolveJob(new Response(JSON.stringify({ job_id: "job-ordinary", type: "CONTENT_GENERATE", status: "CANCELED", progress: 0, attempt: 1, max_attempts: 3, created_at: "", finished_at: "", error: null, result_reference: null }), { status: 200, headers: { "Content-Type": "application/json" } }))
})

it("advances a real draft through ready and hidden polling to approval for its matching result", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let ready = false
  let complete = false
  const readyBrief = { ...brief("READY"), id: "brief-flow", version: 2, updated_at: "2026-08-11T00:00:00Z" }
  const draftBrief = { ...readyBrief, status: "DRAFT" }
  const matchingMaster = {
    id: "master-flow", brief_id: "brief-flow", brief_version: 2, generation_job_id: "job-flow", ai_run_id: "run-flow",
    lineage_id: "lineage-flow", previous_version_id: null, version: 1,
    payload: { title: "本次推广内容", body: "内容", cta: "询价", concept_codes: [] }, provenance: {},
    status: "IN_REVIEW", is_current_head: true, created_by_id: 1, created_at: "", updated_at: "",
  }
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/content-briefs/brief-flow/ready" && options?.method === "POST") {
      ready = true
      return new Response(JSON.stringify(readyBrief), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/content-briefs/brief-flow/generate-master-content" && options?.method === "POST") {
      return new Response(JSON.stringify({ job_id: "job-flow", status: "QUEUED" }), { status: 202, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/jobs/job-flow") {
      complete = true
      return new Response(JSON.stringify({ job_id: "job-flow", type: "CONTENT_GENERATE", status: "SUCCEEDED", progress: 100, attempt: 1, max_attempts: 3, created_at: "", finished_at: "", error: null, result_reference: { type: "master_content", id: "master-flow", version: 1 } }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/content-briefs") return new Response(JSON.stringify({ next: null, previous: null, results: [ready ? readyBrief : draftBrief] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path === "/api/v1/master-contents") return new Response(JSON.stringify({ next: null, previous: null, results: complete ? [matchingMaster] : [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(baseResponse(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "campaigns.review", "content.manage", "content.read", "jobs.read"], "ordinary")

  await user.click(await screen.findByRole("button", { name: "确认方案可生成" }))
  await user.click(await screen.findByRole("button", { name: "生成推广内容" }))

  expect(await screen.findByRole("region", { name: "批准发布" })).toHaveAttribute("aria-current", "step")
  expect(screen.getByRole("link", { name: "查看并确认" })).toHaveAttribute("href", "/reviews")
  expect(screen.getByRole("button", { name: "查看高级记录" })).toHaveAttribute("aria-expanded", "false")
})

it("keeps generation locked while the ordinary recovery scan is still pending", async () => {
  const currentBrief = { ...brief("READY"), id: "a3d6b1fc-6c13-4f52-a798-7f80631d7443", version: 3 }
  let resolveRecovery!: (response: Response) => void
  const pendingRecovery = new Promise<Response>((resolve) => { resolveRecovery = resolve })
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50") return pendingRecovery
    if (path.endsWith("/generate-master-content") && options?.method === "POST") {
      return new Response(JSON.stringify({ job_id: "unexpected", status: "QUEUED" }), { status: 202, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(baseResponse(path, [currentBrief])), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "content.manage", "content.read", "jobs.read"], "ordinary")

  const generate = await screen.findByRole("button", { name: "生成推广内容" })
  expect(generate).toBeDisabled()
  await user.click(generate)
  expect(fetchMock.mock.calls.some(([path, options]) => String(path).endsWith("/generate-master-content") && options?.method === "POST")).toBe(false)

  resolveRecovery(new Response(JSON.stringify({ next: null, previous: null, results: [] }), { status: 200, headers: { "Content-Type": "application/json" } }))
  await waitFor(() => expect(generate).toBeEnabled())
})

it("keeps generation locked after a recovery error until retry exhausts the scan", async () => {
  const currentBrief = { ...brief("READY"), id: "e74f298f-5458-47e7-9482-319dd66ad554", version: 2 }
  let recoveryAttempts = 0
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50") {
      recoveryAttempts += 1
      return recoveryAttempts === 1
        ? new Response(JSON.stringify({ detail: "temporary failure" }), { status: 503, headers: { "Content-Type": "application/json" } })
        : new Response(JSON.stringify({ next: null, previous: null, results: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(baseResponse(path, [currentBrief])), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["campaigns.read", "content.manage", "content.read", "jobs.read"], "ordinary")

  const retry = await screen.findByRole("button", { name: "重新检查生成记录" })
  const generate = screen.getByRole("button", { name: "生成推广内容" })
  expect(generate).toBeDisabled()
  await user.click(retry)
  await waitFor(() => expect(recoveryAttempts).toBe(2))
  await waitFor(() => expect(generate).toBeEnabled())
})

it("scans three recovery pages before restoring the current generation", async () => {
  const currentBrief = { ...brief("READY"), id: "c4ebdcda-d963-4691-876e-d69b0bd70e1a", version: 8 }
  const unrelated = {
    job_id: "c8038619-f384-4c0c-b244-8ce0d3274457", type: "CONTENT_GENERATE", status: "FAILED", progress: 12,
    attempt: 1, max_attempts: 3, created_at: "2026-08-11T03:00:00Z", finished_at: "2026-08-11T03:01:00Z",
    error: { message: "unrelated" }, result_reference: null,
    source_reference: { brief_id: "9750530a-c203-4ee6-845f-6771dfc15dd7", brief_version: 1 },
  }
  const matching = {
    ...unrelated,
    job_id: "07d60091-287c-441a-9e86-9655f41849bc",
    source_reference: { brief_id: currentBrief.id, brief_version: currentBrief.version },
  }
  const second = "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50&cursor=second"
  const third = "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50&cursor=third"
  const fetchMock = vi.fn(async (path: string) => {
    const body = path === "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50"
      ? { next: second, previous: null, results: [unrelated] }
      : path === second
        ? { next: third, previous: "/api/v1/jobs", results: [unrelated] }
        : path === third
          ? { next: null, previous: second, results: [matching] }
          : baseResponse(path, [currentBrief])
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  renderPage(["campaigns.read", "content.manage", "content.read", "jobs.read", "jobs.manage"], "ordinary")

  expect(await screen.findByText("生成未完成")).toBeVisible()
  expect(fetchMock.mock.calls.filter(([path]) => path === second)).toHaveLength(1)
  expect(fetchMock.mock.calls.filter(([path]) => path === third)).toHaveLength(1)
  expect(screen.getByRole("button", { name: "生成推广内容" })).toBeDisabled()
})

it("does not unlock generation until every recovery page has no current match", async () => {
  const currentBrief = { ...brief("READY"), id: "bd08a04e-224b-4f41-9b8b-ae43f6ddcd67", version: 5 }
  const second = "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50&cursor=last"
  let resolveLast!: (response: Response) => void
  const lastPage = new Promise<Response>((resolve) => { resolveLast = resolve })
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50") {
      return new Response(JSON.stringify({ next: second, previous: null, results: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === second) return lastPage
    return new Response(JSON.stringify(baseResponse(path, [currentBrief])), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  renderPage(["campaigns.read", "content.manage", "content.read", "jobs.read"], "ordinary")

  const generate = await screen.findByRole("button", { name: "生成推广内容" })
  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => path === second)).toBe(true))
  expect(generate).toBeDisabled()
  resolveLast(new Response(JSON.stringify({ next: null, previous: "/api/v1/jobs", results: [] }), { status: 200, headers: { "Content-Type": "application/json" } }))
  await waitFor(() => expect(generate).toBeEnabled())
})

it("aborts an old recovery scan and starts a clean scan when the latest brief changes", async () => {
  const firstBrief = { ...brief("READY"), id: "fa224e41-7077-4dd4-ab45-0959647eb3be", version: 1 }
  const nextBrief = { ...firstBrief, id: "58e89e3e-92c0-4454-96c4-2e8727fb19f5", version: 2, updated_at: "2026-08-11T04:00:00Z" }
  let recoveryCalls = 0
  let firstSignal: AbortSignal | null = null
  const neverSettles = new Promise<Response>(() => undefined)
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50") {
      recoveryCalls += 1
      if (recoveryCalls === 1) {
        firstSignal = options?.signal ?? null
        return neverSettles
      }
      return new Response(JSON.stringify({ next: null, previous: null, results: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(baseResponse(path, [firstBrief])), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const view = renderPage(["campaigns.read", "content.manage", "content.read", "jobs.read"], "ordinary")

  expect(await screen.findByRole("button", { name: "生成推广内容" })).toBeDisabled()
  view.queryClient.setQueryData(contentQueryKeys.briefs("org-1"), { next: null, previous: null, results: [nextBrief] })

  await waitFor(() => expect(recoveryCalls).toBe(2))
  expect(firstSignal?.aborted).toBe(true)
  await waitFor(() => expect(screen.getByRole("button", { name: "生成推广内容" })).toBeEnabled())
})

it("restores the current brief's running generation from the server after a remount", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const currentBrief = {
    ...brief("READY"),
    id: "9f15f0d6-f28b-41ac-a31e-b246df7b4d56",
    version: 4,
  }
  const matchingJob = {
    job_id: "c8e67868-d908-402d-a2e6-5a7c1c6079f8", type: "CONTENT_GENERATE", status: "RUNNING", progress: 38,
    attempt: 1, max_attempts: 3, created_at: "2026-08-11T01:00:00Z", finished_at: null, error: null,
    result_reference: null,
    source_reference: { brief_id: currentBrief.id, brief_version: currentBrief.version },
  }
  let submitted = false
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === `/api/v1/content-briefs/${currentBrief.id}/generate-master-content` && options?.method === "POST") {
      submitted = true
      return new Response(JSON.stringify({ job_id: matchingJob.job_id, status: "QUEUED" }), { status: 202, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50") {
      return new Response(JSON.stringify({ next: null, previous: null, results: submitted ? [matchingJob] : [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === `/api/v1/jobs/${matchingJob.job_id}`) {
      return new Response(JSON.stringify(matchingJob), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(baseResponse(path, [currentBrief])), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const permissions = ["campaigns.read", "content.manage", "content.read", "jobs.read"]
  const user = userEvent.setup()
  const first = renderPage(permissions, "ordinary")

  await user.click(await screen.findByRole("button", { name: "生成推广内容" }))
  expect(await screen.findByText("正在生成")).toBeVisible()
  first.unmount()

  const second = renderPage(permissions, "ordinary")
  expect(await screen.findByText("正在生成")).toBeVisible()
  expect(screen.getByRole("button", { name: "生成推广内容" })).toBeDisabled()
  expect(screen.getByRole("button", { name: "查看高级记录" })).toHaveAttribute("aria-expanded", "false")
  await user.click(screen.getByRole("button", { name: "生成推广内容" }))
  expect(fetchMock.mock.calls.filter(([path, options]) => String(path).endsWith("/generate-master-content") && options?.method === "POST")).toHaveLength(1)
  second.unmount()
})

it("restores only the latest failed job for the current brief and ignores unrelated jobs", async () => {
  const currentBrief = {
    ...brief("READY"),
    id: "3e42cc89-e937-43f4-bb36-98b333e64906",
    version: 2,
  }
  const unrelated = {
    job_id: "73b85c2c-e6cf-4fac-b3cf-e52f830cfe2a", type: "CONTENT_GENERATE", status: "RUNNING", progress: 70,
    attempt: 1, max_attempts: 3, created_at: "2026-08-11T03:00:00Z", finished_at: null, error: null, result_reference: null,
    source_reference: { brief_id: "2127b472-b0e3-4dad-ad9b-1d5c74aa5570", brief_version: 7 },
  }
  const missingReference = {
    ...unrelated, job_id: "7078aef4-a20a-4e69-b1ea-a472729d9b79", created_at: "2026-08-11T02:00:00Z", source_reference: null,
  }
  const matchingFailed = {
    ...unrelated,
    job_id: "089c1318-5f67-4d60-8f40-c3e12f212923", status: "FAILED", progress: 46,
    created_at: "2026-08-11T01:00:00Z", finished_at: "2026-08-11T01:01:00Z", error: { message: "provider failed" },
    source_reference: { brief_id: currentBrief.id, brief_version: currentBrief.version },
  }
  const fetchMock = vi.fn(async (path: string) => {
    const body = path === "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50"
      ? { next: null, previous: null, results: [unrelated, missingReference, matchingFailed] }
      : baseResponse(path, [currentBrief])
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  renderPage(["campaigns.read", "content.manage", "content.read", "jobs.read", "jobs.manage"], "ordinary")

  expect(await screen.findByText("生成未完成")).toBeVisible()
  expect(screen.getByRole("button", { name: "再次尝试" })).toBeVisible()
  expect(screen.getByRole("button", { name: "生成推广内容" })).toBeDisabled()
  expect(fetchMock.mock.calls.some(([path]) => path === `/api/v1/jobs/${unrelated.job_id}`)).toBe(false)
  expect(fetchMock.mock.calls.some(([path]) => path === `/api/v1/jobs/${missingReference.job_id}`)).toBe(false)
})

it("explains a scheduled retry with safe Chinese copy in ordinary mode", async () => {
  const currentBrief = {
    ...brief("READY"), id: "16709db2-f90d-46fa-982b-6825fe581d6a", version: 2,
  }
  const retrying = {
    job_id: "c545eb30-6dc2-43b9-aea6-0cdd1e0c2c2e", type: "CONTENT_GENERATE", status: "RUNNING",
    progress: 35, attempt: 1, max_attempts: 3, created_at: "2026-08-12T06:00:00Z", finished_at: null,
    error: null, result_reference: null, retry_count: 1, next_retry_at: "2026-08-12T06:30:00Z",
    source_reference: { brief_id: currentBrief.id, brief_version: currentBrief.version },
  }
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(
    path === "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50"
      ? { next: null, previous: null, results: [retrying] }
      : path === `/api/v1/jobs/${retrying.job_id}` ? retrying : baseResponse(path, [currentBrief]),
  ), { status: 200, headers: { "Content-Type": "application/json" } })))
  renderPage(["campaigns.read", "content.manage", "content.read", "jobs.read"], "ordinary")

  expect(await screen.findByText(/第 1 次.*再次处理/)).toBeVisible()
  expect(screen.getByText("暂时无需操作，系统会按计划继续。")).toBeVisible()
  expect(document.body).not.toHaveTextContent(/V4|Flash|Pro|模型/)
})

it("continues through server job pages until it finds the current brief's latest job", async () => {
  const currentBrief = {
    ...brief("READY"),
    id: "29389f7c-bfe5-4417-a580-3d1d5eb3de50",
    version: 6,
  }
  const unrelated = {
    job_id: "35e67a40-2a83-4cb1-aeb1-b0655761e863", type: "CONTENT_GENERATE", status: "FAILED", progress: 20,
    attempt: 1, max_attempts: 3, created_at: "2026-08-11T03:00:00Z", finished_at: "2026-08-11T03:01:00Z",
    error: { message: "unrelated" }, result_reference: null,
    source_reference: { brief_id: "e1029fbb-ceea-4030-aef5-5b8ab56d944a", brief_version: 1 },
  }
  const matching = {
    ...unrelated,
    job_id: "3f85f431-3d57-4eea-967c-aec556691584", created_at: "2026-08-11T02:00:00Z",
    source_reference: { brief_id: currentBrief.id, brief_version: currentBrief.version },
  }
  const next = "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50&cursor=second"
  const fetchMock = vi.fn(async (path: string) => {
    const body = path === "/api/v1/jobs?type=CONTENT_GENERATE&page_size=50"
      ? { next, previous: null, results: [unrelated] }
      : path === next
        ? { next: null, previous: "/api/v1/jobs", results: [matching] }
        : baseResponse(path, [currentBrief])
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  renderPage(["campaigns.read", "content.manage", "content.read", "jobs.read", "jobs.manage"], "ordinary")

  expect(await screen.findByText("生成未完成")).toBeVisible()
  expect(fetchMock.mock.calls.filter(([path]) => path === next)).toHaveLength(1)
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
