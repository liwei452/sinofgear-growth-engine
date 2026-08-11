import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import CompanyProfilePage from "./CompanyProfilePage.vue"

const userWith = (permissions: string[]): CurrentUser => ({
  user: { id: 1, username: "operator" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "OPERATOR", status: "ACTIVE", permissions },
})

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function page(results: unknown[]): Response {
  return json({ next: null, previous: null, results })
}

async function renderCompany(
  fetchMock: ReturnType<typeof vi.fn>,
  permissions = [
    "products.read", "products.manage",
    "knowledge.read", "knowledge.create",
    "assets.read", "assets.manage",
  ],
) {
  vi.stubGlobal("fetch", fetchMock)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/company-profile", component: CompanyProfilePage },
      { path: "/products", component: { template: "<p>产品编辑器</p>" } },
      { path: "/knowledge", component: { template: "<p>知识编辑器</p>" } },
      { path: "/assets", component: { template: "<p>素材编辑器</p>" } },
    ],
  })
  router.push("/company-profile")
  await router.isReady()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(permissions))
  const view = render(CompanyProfilePage, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  return { ...view, queryClient }
}

afterEach(() => vi.unstubAllGlobals())

it("shows what AI knows, computes coverage from real data, and prioritizes missing tasks", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/products?status=ACTIVE") return Promise.resolve(page([{
      id: "p1", status: "ACTIVE", name_zh: "精密齿轮", name_en: "Precision Gear",
      manufacturing_capabilities: ["滚齿"], inspection_capabilities: ["齿形检测"],
      concept_links: [],
    }]))
    if (path === "/api/v1/knowledge/concepts?status=APPROVED") return Promise.resolve(json({ results: [
      { id: "k1", status: "APPROVED", concept_type: "INDUSTRY", label_zh: "工业机器人", label_en: "Robotics", evidence: ["产品手册"] },
      { id: "k2", status: "APPROVED", concept_type: "PROCESS", label_zh: "磨齿", label_en: "Grinding", evidence: [] },
    ] }))
    if (path === "/api/v1/knowledge/evidence?status=APPROVED") return Promise.resolve(json({ results: [{ id: "e1", status: "APPROVED" }] }))
    if (path === "/api/v1/assets?status=ACTIVE") return Promise.resolve(page([{ id: "a1", status: "ACTIVE" }]))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock)

  expect(await screen.findByRole("heading", { name: "AI 对公司的了解" })).toBeVisible()
  expect(screen.getByRole("region", { name: "公司身份" })).toHaveTextContent("示例组织")
  expect(await within(screen.getByRole("region", { name: "产品" })).findByText("精密齿轮")).toBeVisible()
  expect(screen.getByRole("region", { name: "能力" })).toHaveTextContent("滚齿")
  expect(screen.getByRole("region", { name: "行业" })).toHaveTextContent("工业机器人")
  expect(screen.getByRole("region", { name: "工艺" })).toHaveTextContent("磨齿")
  expect(screen.getByRole("region", { name: "资料完整度" })).toHaveTextContent("已覆盖 7 项，共 8 项")
  expect(screen.getByRole("region", { name: "资料完整度" })).not.toHaveTextContent("%")
  const gaps = screen.getByRole("region", { name: "建议补充" })
  expect(gaps).toHaveTextContent("补充标准")
  expect(within(gaps).getByRole("link", { name: "去知识库补充标准" })).toHaveAttribute("href", "/knowledge")
})

it("aborts company source requests when the organization changes and never renders the old organization response", async () => {
  const pending: Array<{ path: string; signal?: AbortSignal; resolve: (value: Response) => void }> = []
  const fetchMock = vi.fn((path: string, options?: RequestInit) => new Promise<Response>((resolve) => {
    pending.push({ path, signal: options?.signal ?? undefined, resolve })
  }))
  const { queryClient } = await renderCompany(fetchMock)
  await waitFor(() => expect(pending).toHaveLength(4))
  expect(screen.getByRole("region", { name: "资料完整度" })).toHaveTextContent("正在核对真实资料")
  expect(screen.getByRole("region", { name: "资料完整度" })).not.toHaveTextContent("已覆盖")

  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    ...userWith(["products.read", "products.manage", "knowledge.read", "knowledge.create", "assets.read", "assets.manage"]),
    organization: { id: "org-2", name: "新组织", slug: "new" },
  })

  await waitFor(() => expect(pending).toHaveLength(8))
  expect(pending.slice(0, 4).every((request) => request.signal?.aborted)).toBe(true)
  for (const request of pending.slice(4)) {
    request.resolve(request.path.includes("knowledge") ? json({ results: [] }) : page([]))
  }
  for (const request of pending.slice(0, 4)) {
    request.resolve(request.path.startsWith("/api/v1/products")
      ? page([{ id: "old-product", status: "ACTIVE", name_zh: "旧组织产品" }])
      : request.path.includes("knowledge") ? json({ results: [] }) : page([]))
  }

  expect(await screen.findByText("新组织")).toBeVisible()
  expect(screen.queryByText("旧组织产品")).not.toBeInTheDocument()
})

it("retries only company sources the user is allowed to read", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(json({ detail: "offline" }, 503))
    if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(json({ results: [] }))
    return Promise.resolve(page([]))
  })
  await renderCompany(fetchMock, ["knowledge.read"])

  const capabilities = await screen.findByRole("region", { name: "能力" })
  await userEvent.click(await within(capabilities).findByRole("button", { name: "重新加载能力资料" }))
  expect(fetchMock.mock.calls.every(([path]) => String(path).startsWith("/api/v1/knowledge/"))).toBe(true)
})

it("excludes inactive and unapproved records from company understanding", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return Promise.resolve(page([{
      id: "draft-product", status: "DRAFT", name_zh: "草稿产品",
      manufacturing_capabilities: ["未确认能力"], inspection_capabilities: [], concept_links: [],
    }]))
    if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(json({ results: [{
      id: "suggested-industry", status: "SUGGESTED", concept_type: "INDUSTRY",
      label_zh: "未审核行业", label_en: "", evidence: [],
    }] }))
    if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(json({ results: [{ id: "rejected-evidence", status: "REJECTED" }] }))
    if (path.startsWith("/api/v1/assets")) return Promise.resolve(page([{ id: "archived-asset", status: "ARCHIVED" }]))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock)

  expect(await screen.findByText("已覆盖 1 项，共 8 项")).toBeVisible()
  expect(screen.queryByText("草稿产品")).not.toBeInTheDocument()
  expect(screen.queryByText("未确认能力")).not.toBeInTheDocument()
  expect(screen.queryByText("未审核行业")).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/products?status=ACTIVE", expect.anything())
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/assets?status=ACTIVE", expect.anything())
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/knowledge/concepts?status=APPROVED", expect.anything())
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/knowledge/evidence?status=APPROVED", expect.anything())
})

it("does not count rejected evidence referenced by an approved concept", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(json({ results: [{
      id: "approved-concept", status: "APPROVED", concept_type: "PRODUCT_TYPE",
      label_zh: "已审核概念", label_en: "", evidence: ["rejected-evidence"],
    }] }))
    if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(json({ results: [{
      id: "rejected-evidence", status: "REJECTED",
    }] }))
    return Promise.resolve(page([]))
  })
  await renderCompany(fetchMock)

  expect(await screen.findByText("已覆盖 1 项，共 8 项")).toBeVisible()
  expect(screen.getByRole("region", { name: "建议补充" })).toHaveTextContent("补充证据")
})

it("summarizes only currently available company data and links to existing editors", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/products?status=ACTIVE") return Promise.resolve(page([{ id: "p1", status: "ACTIVE" }, { id: "p2", status: "ACTIVE" }]))
    if (path === "/api/v1/knowledge/concepts?status=APPROVED") return Promise.resolve(json({ results: [{ id: "k1", status: "APPROVED" }] }))
    if (path === "/api/v1/knowledge/evidence?status=APPROVED") return Promise.resolve(json({ results: [] }))
    if (path === "/api/v1/assets?status=ACTIVE") return Promise.resolve(page([{ id: "a1", status: "ACTIVE" }, { id: "a2", status: "ACTIVE" }, { id: "a3", status: "ACTIVE" }]))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock)

  expect(await screen.findByRole("heading", { name: "AI 对公司的了解" })).toBeVisible()
  expect(await screen.findByText("当前页有 2 个产品")).toBeVisible()
  expect(await screen.findByText("当前可见 1 条知识")).toBeVisible()
  expect(await screen.findByText("当前页有 3 份素材")).toBeVisible()
  expect(screen.getByRole("link", { name: "管理产品资料" })).toHaveAttribute("href", "/products")
  expect(screen.getByRole("link", { name: "管理公司知识" })).toHaveAttribute("href", "/knowledge")
  expect(screen.getByRole("link", { name: "管理素材" })).toHaveAttribute("href", "/assets")
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
})

it("shows honest empty guidance instead of invented company facts", async () => {
  const fetchMock = vi.fn((path: string) => path.startsWith("/api/v1/knowledge/concepts")
    ? Promise.resolve(json({ results: [] }))
    : Promise.resolve(page([])))
  await renderCompany(fetchMock)

  expect(await screen.findByText("还没有产品资料")).toBeVisible()
  expect(await screen.findByText("还没有公司知识")).toBeVisible()
  expect(await screen.findByText("还没有可用素材")).toBeVisible()
  expect(screen.getByRole("link", { name: "去产品库补充" })).toHaveAttribute("href", "/products")
})

it("contains a failed source locally and lets the user retry it", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return Promise.resolve(json({ detail: "offline" }, 503))
    if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(json({ results: [{ id: "k1", status: "APPROVED" }] }))
    if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(json({ results: [] }))
    return Promise.resolve(page([{ id: "a1", status: "ACTIVE" }]))
  })
  const user = userEvent.setup()
  await renderCompany(fetchMock)

  const productRegion = await screen.findByRole("region", { name: "产品" })
  expect(await within(productRegion).findByRole("alert")).toHaveTextContent("产品资料暂时无法读取")
  expect(await screen.findByText("当前可见 1 条知识")).toBeVisible()
  expect(await screen.findByText("当前页有 1 份素材")).toBeVisible()
  await user.click(within(productRegion).getByRole("button", { name: "重新加载产品资料" }))
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/products?status=ACTIVE", expect.any(Object))
})

it("permission-gates every source and editor link", async () => {
  const fetchMock = vi.fn().mockResolvedValue(json({ results: [] }))
  await renderCompany(fetchMock, ["knowledge.read"])

  expect(await screen.findByText("你没有查看产品资料的权限。")).toBeVisible()
  expect(screen.getByText("你没有查看素材的权限。")).toBeVisible()
  expect(screen.queryByRole("link", { name: /产品/ })).not.toBeInTheDocument()
  expect(await screen.findByRole("link", { name: "查看知识库" })).toHaveAttribute("href", "/knowledge")
  expect(screen.getAllByText(/如需补充(?:或编辑)?，请联系管理员/).length).toBeGreaterThan(0)
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it.each([
  { read: "products.read", action: "查看产品库", path: "/products" },
  { read: "knowledge.read", action: "查看知识库", path: "/knowledge" },
  { read: "assets.read", action: "查看素材库", path: "/assets" },
])("uses read-only wording for $read without implying mutation authority", async ({ read, action, path }) => {
  const fetchMock = vi.fn((requestPath: string) => requestPath.startsWith("/api/v1/knowledge/concepts")
    ? Promise.resolve(json({ results: [] }))
    : Promise.resolve(page([])))
  await renderCompany(fetchMock, [read])

  expect(await screen.findByRole("link", { name: action })).toHaveAttribute("href", path)
  expect(screen.queryByRole("link", { name: /补充|管理/ })).not.toBeInTheDocument()
  expect(screen.getAllByText(/如需补充(?:或编辑)?，请联系管理员/).length).toBeGreaterThan(0)
})

it("updates source actions when the current user's permissions change", async () => {
  const fetchMock = vi.fn((path: string) => path.startsWith("/api/v1/knowledge/concepts")
    ? Promise.resolve(json({ results: [] }))
    : Promise.resolve(page([])))
  const readPermissions = ["products.read", "knowledge.read", "assets.read"]
  const { queryClient } = await renderCompany(fetchMock, readPermissions)

  expect(await screen.findByRole("link", { name: "查看产品库" })).toBeVisible()
  expect(screen.getByRole("link", { name: "查看知识库" })).toBeVisible()
  expect(screen.getByRole("link", { name: "查看素材库" })).toBeVisible()

  queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith([
    ...readPermissions,
    "products.manage", "knowledge.create", "assets.manage",
  ]))

  await waitFor(() => {
    expect(screen.getByRole("link", { name: "去产品库补充" })).toBeVisible()
    expect(screen.getByRole("link", { name: "去知识库补充" })).toBeVisible()
    expect(screen.getByRole("link", { name: "去素材库补充" })).toBeVisible()
  })
  expect(screen.queryByRole("link", { name: /查看.+库/ })).not.toBeInTheDocument()
})
