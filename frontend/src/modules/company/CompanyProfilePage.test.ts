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

it("uses the beginner-facing product information title", async () => {
  await renderCompany(vi.fn(() => Promise.resolve(page([]))))
  expect(screen.getByRole("heading", { level: 1, name: "产品资料" })).toBeInTheDocument()
})

it("shows what AI knows, computes coverage from real data, and prioritizes missing tasks", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/products?status=ACTIVE") return Promise.resolve(page([{
      id: "p1", status: "ACTIVE", name_zh: "精密齿轮", name_en: "Precision Gear",
      manufacturing_capabilities: ["滚齿"], inspection_capabilities: ["齿形检测"],
      concept_links: [],
    }]))
    if (path === "/api/v1/knowledge/concepts?status=APPROVED") return Promise.resolve(json({ results: [
      { id: "k1", scope: "ORGANIZATION", organization: "org-1", status: "APPROVED", concept_type: "INDUSTRY", label_zh: "工业机器人", label_en: "Robotics", evidence: ["产品手册"] },
      { id: "k2", scope: "ORGANIZATION", organization: "org-1", status: "APPROVED", concept_type: "PROCESS", label_zh: "磨齿", label_en: "Grinding", evidence: [] },
    ] }))
    if (path === "/api/v1/knowledge/evidence?status=APPROVED") return Promise.resolve(json({ results: [{ id: "e1", organization: "org-1", status: "APPROVED" }] }))
    if (path === "/api/v1/assets?status=ACTIVE") return Promise.resolve(page([{ id: "a1", status: "ACTIVE" }]))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock)

  expect(await screen.findByRole("heading", { name: "产品资料" })).toBeVisible()
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

it("drops each revoked source from cached composite facts and ignores its late response", async () => {
  let resolveProducts!: (value: Response) => void
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) {
      return new Promise<Response>((resolve) => { resolveProducts = resolve })
    }
    if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(json({ results: [{
      id: "org-capability", scope: "ORGANIZATION", organization: "org-1", status: "APPROVED",
      concept_type: "CAPABILITY", label_zh: "知识能力", label_en: "", evidence: [],
    }] }))
    if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(json({ results: [] }))
    return Promise.resolve(page([]))
  })
  const { queryClient } = await renderCompany(fetchMock)

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4))
  queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(["knowledge.read", "assets.read"]))
  expect(await within(screen.getByRole("region", { name: "能力" })).findByText("知识能力")).toBeVisible()
  resolveProducts(page([{
    id: "late-product", status: "ACTIVE", name_zh: "迟到产品",
    manufacturing_capabilities: ["迟到产品能力"], inspection_capabilities: [], concept_links: [],
  }]))

  await waitFor(() => {
    expect(screen.queryByText("迟到产品")).not.toBeInTheDocument()
    expect(screen.queryByText("迟到产品能力")).not.toBeInTheDocument()
    expect(screen.getByText("知识能力")).toBeVisible()
  })

  queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(["products.read", "assets.read"]))
  await waitFor(() => {
    expect(screen.getByText("迟到产品")).toBeVisible()
    expect(screen.getByText("迟到产品能力")).toBeVisible()
    expect(screen.queryByText("知识能力")).not.toBeInTheDocument()
  })
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

it("uses organization knowledge and only product-linked system facts and evidence", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return Promise.resolve(page([{
      id: "product-1", organization: "org-1", status: "ACTIVE", name_zh: "公司产品",
      manufacturing_capabilities: [], inspection_capabilities: [],
      concept_links: [{
        id: "link-1", role: "CAPABILITY", version: 1,
        concept: { id: "system-linked", code: "SYS_CAP", concept_type: "CAPABILITY", label_zh: "产品关联系统能力", label_en: "", version: 1 },
      }],
    }]))
    if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(json({ results: [
      { id: "system-unlinked", scope: "SYSTEM", organization: null, status: "APPROVED", concept_type: "INDUSTRY", label_zh: "未关联全局行业", label_en: "", evidence: ["system-unlinked-evidence"] },
      { id: "system-linked", scope: "SYSTEM", organization: null, status: "APPROVED", concept_type: "CAPABILITY", label_zh: "产品关联系统能力", label_en: "", evidence: ["system-linked-evidence"] },
      { id: "other-org", scope: "ORGANIZATION", organization: "org-2", status: "APPROVED", concept_type: "STANDARD", label_zh: "其他组织标准", label_en: "", evidence: [] },
      { id: "current-org", scope: "ORGANIZATION", organization: "org-1", status: "APPROVED", concept_type: "PROCESS", label_zh: "本组织工艺", label_en: "", evidence: [] },
    ] }))
    if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(json({ results: [
      { id: "system-unlinked-evidence", organization: null, status: "APPROVED" },
      { id: "system-linked-evidence", organization: null, status: "APPROVED" },
      { id: "current-org-evidence", organization: "org-1", status: "APPROVED" },
      { id: "other-org-evidence", organization: "org-2", status: "APPROVED" },
    ] }))
    return Promise.resolve(page([]))
  })
  await renderCompany(fetchMock)

  expect(await screen.findByText("产品关联系统能力")).toBeVisible()
  expect(screen.getByText("本组织工艺")).toBeVisible()
  expect(screen.queryByText("未关联全局行业")).not.toBeInTheDocument()
  expect(screen.queryByText("其他组织标准")).not.toBeInTheDocument()
  expect(screen.getByRole("region", { name: "证据覆盖" })).toHaveTextContent("当前可确认 2 条证据依据")
  expect(screen.getByRole("region", { name: "建议补充" })).not.toHaveTextContent("补充证据")
})

it("shows product-linked ontology facts without requiring direct knowledge access", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return Promise.resolve(page([{
      id: "product-1", status: "ACTIVE", name_zh: "行业产品",
      manufacturing_capabilities: [], inspection_capabilities: [],
      concept_links: [{
        id: "link-1", role: "APPLICATION", version: 1,
        concept: { id: "system-industry", code: "SYS_IND", concept_type: "INDUSTRY", label_zh: "产品关联行业", label_en: "", version: 1 },
      }],
    }]))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock, ["products.read"])

  expect(await within(screen.getByRole("region", { name: "行业" })).findByText("产品关联行业")).toBeVisible()
  expect(fetchMock.mock.calls.every(([path]) => String(path).startsWith("/api/v1/products"))).toBe(true)
})

it("loads safe later active-product pages before deciding capability gaps", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/products?status=ACTIVE") return Promise.resolve(json({
      next: "/api/v1/products?status=ACTIVE&cursor=page-2", previous: null,
      results: [{ id: "product-1", status: "ACTIVE", name_zh: "第一页产品", manufacturing_capabilities: [], inspection_capabilities: [], concept_links: [] }],
    }))
    if (path === "/api/v1/products?status=ACTIVE&cursor=page-2") return Promise.resolve(json({
      next: null, previous: "/api/v1/products?status=ACTIVE",
      results: [{ id: "product-2", status: "ACTIVE", name_zh: "第二页产品", manufacturing_capabilities: ["后页磨齿能力"], inspection_capabilities: [], concept_links: [] }],
    }))
    if (path.includes("/knowledge/")) return Promise.resolve(json({ results: [] }))
    return Promise.resolve(page([]))
  })
  await renderCompany(fetchMock)

  expect(await screen.findByText("第二页产品")).toBeVisible()
  expect(screen.getByText("后页磨齿能力")).toBeVisible()
  expect(screen.getByRole("region", { name: "产品" })).toHaveTextContent("已读取全部 2 个启用产品")
  expect(screen.getByRole("region", { name: "建议补充" })).not.toHaveTextContent("补充能力")
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/products?status=ACTIVE&cursor=page-2", expect.objectContaining({ signal: expect.any(AbortSignal) }))
})

it.each([
  { label: "invalid", next: "https://evil.example/api/v1/products?cursor=2" },
  { label: "cycle", next: "/api/v1/products?status=ACTIVE" },
])("treats $label product pagination as unknown instead of missing", async ({ next }) => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/products?status=ACTIVE") return Promise.resolve(json({ next, previous: null, results: [] }))
    if (path.startsWith("/api/v1/knowledge/")) return Promise.resolve(json({ results: [] }))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock, ["products.read", "knowledge.read"])

  const coverage = screen.getByRole("region", { name: "资料完整度" })
  expect(await within(coverage).findByText("已确认 1 项，另有资料暂无法判断")).toBeVisible()
  expect(coverage).toHaveTextContent("部分资料暂不可用")
  expect(coverage).not.toHaveTextContent("已覆盖 1 项，共 8 项")
  const gaps = screen.getByRole("region", { name: "建议补充" })
  expect(gaps).not.toHaveTextContent("补充产品")
  expect(gaps).not.toHaveTextContent("补充能力")
  expect(gaps).not.toHaveTextContent("补充行业")
  expect(gaps).not.toHaveTextContent("补充工艺")
  expect(gaps).not.toHaveTextContent("补充标准")
  expect(gaps).not.toHaveTextContent("补充证据")
})

it("caps product pagination as unknown instead of inventing gaps", async () => {
  let productCalls = 0
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) {
      productCalls += 1
      const cursor = new URL(path, "http://localhost").searchParams.get("cursor")
      const pageNumber = cursor ? Number(cursor) : 1
      return Promise.resolve(json({
        next: `/api/v1/products?status=ACTIVE&cursor=${pageNumber + 1}`,
        previous: null,
        results: [],
      }))
    }
    if (path.startsWith("/api/v1/knowledge/")) return Promise.resolve(json({ results: [] }))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock, ["products.read", "knowledge.read"])

  expect(await screen.findByText("已确认 1 项，另有资料暂无法判断")).toBeVisible()
  expect(productCalls).toBe(100)
  expect(screen.getByRole("region", { name: "建议补充" })).not.toHaveTextContent(/补充产品|补充能力|补充行业|补充工艺|补充标准|补充证据/)
})

it("does not turn a failed product source into product, composite, or evidence gaps", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return Promise.resolve(json({ detail: "offline" }, 503))
    if (path.startsWith("/api/v1/knowledge/")) return Promise.resolve(json({ results: [] }))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock, ["products.read", "knowledge.read"])

  expect(await screen.findByText("已确认 1 项，另有资料暂无法判断")).toBeVisible()
  const gaps = screen.getByRole("region", { name: "建议补充" })
  expect(gaps).not.toHaveTextContent(/补充产品|补充能力|补充行业|补充工艺|补充标准|补充证据/)
})

it("keeps evidence pending while a readable product source is pending", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return new Promise<Response>(() => undefined)
    if (path.startsWith("/api/v1/knowledge/")) return Promise.resolve(json({ results: [] }))
    throw new Error(`Unexpected request: ${path}`)
  })
  const { queryClient } = await renderCompany(fetchMock, ["products.read", "knowledge.read", "knowledge.create"])

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
  await waitFor(() => {
    const knowledgeQueries = queryClient.getQueryCache().findAll({ queryKey: ["knowledge", "org-1"] })
    expect(knowledgeQueries).toHaveLength(2)
    expect(knowledgeQueries.every((query) => query.state.status === "success")).toBe(true)
  })
  const gaps = screen.getByRole("region", { name: "建议补充" })
  const evidenceRegion = screen.getByRole("region", { name: "证据覆盖" })
  expect(gaps).toHaveTextContent("0 项")
  expect(gaps).not.toHaveTextContent("补充证据")
  expect(within(evidenceRegion).getByRole("link", { name: "查看知识库" })).toHaveAttribute("href", "/knowledge")
  expect(within(evidenceRegion).queryByRole("link", { name: /补充|管理/ })).not.toBeInTheDocument()
  expect(screen.getByRole("region", { name: "资料完整度" })).toHaveTextContent("正在核对真实资料")
})

it.each([
  { label: "failed", productResponse: json({ detail: "offline" }, 503) },
  { label: "truncated", productResponse: json({ next: "https://evil.example/api/v1/products?cursor=2", previous: null, results: [] }) },
])("uses a neutral evidence CTA when a product contributor is $label", async ({ productResponse }) => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return Promise.resolve(productResponse)
    if (path.startsWith("/api/v1/knowledge/")) return Promise.resolve(json({ results: [] }))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock, ["products.read", "knowledge.read", "knowledge.create"])

  const evidenceRegion = screen.getByRole("region", { name: "证据覆盖" })
  expect(await within(evidenceRegion).findByRole("alert")).toHaveTextContent("当前是否存在缺口暂无法判断")
  expect(within(evidenceRegion).getByRole("link", { name: "查看知识库" })).toHaveAttribute("href", "/knowledge")
  expect(within(evidenceRegion).queryByRole("link", { name: /补充|管理/ })).not.toBeInTheDocument()
  expect(screen.getByRole("region", { name: "建议补充" })).not.toHaveTextContent("补充证据")
})

it("offers evidence supplementation only when evidence readiness is ready and evidence is empty", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return Promise.resolve(page([]))
    if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(json({ results: [{
      id: "company-knowledge", scope: "ORGANIZATION", organization: "org-1", status: "APPROVED",
      concept_type: "PRODUCT_TYPE", label_zh: "公司知识", label_en: "", evidence: [],
    }] }))
    if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(json({ results: [] }))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock, ["products.read", "knowledge.read", "knowledge.create"])

  const evidenceRegion = screen.getByRole("region", { name: "证据覆盖" })
  expect(await within(evidenceRegion).findByText("还没有可追溯的证据依据。")).toBeVisible()
  expect(within(evidenceRegion).getByRole("link", { name: "去知识库补充" })).toHaveAttribute("href", "/knowledge")
  expect(screen.getByRole("region", { name: "建议补充" })).toHaveTextContent("补充证据")
})

it("uses a view-only evidence CTA when ready evidence is already known", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return Promise.resolve(page([]))
    if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(json({ results: [] }))
    if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(json({ results: [{
      id: "evidence-1", organization: "org-1", status: "APPROVED",
    }] }))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock, ["products.read", "knowledge.read", "knowledge.create"])

  const evidenceRegion = screen.getByRole("region", { name: "证据覆盖" })
  expect(await within(evidenceRegion).findByText("当前可确认 1 条证据依据。")).toBeVisible()
  expect(within(evidenceRegion).getByRole("link", { name: "查看知识库" })).toHaveAttribute("href", "/knowledge")
  expect(within(evidenceRegion).queryByRole("link", { name: /补充|管理/ })).not.toBeInTheDocument()
  expect(screen.getByRole("region", { name: "建议补充" })).not.toHaveTextContent("补充证据")
})

it("hides the evidence CTA when evidence is unavailable without read permission", async () => {
  const fetchMock = vi.fn()
  await renderCompany(fetchMock, ["knowledge.create"])

  const evidenceRegion = screen.getByRole("region", { name: "证据覆盖" })
  expect(evidenceRegion).toHaveTextContent("你没有查看证据资料的权限。")
  expect(within(evidenceRegion).queryByRole("link")).not.toBeInTheDocument()
  expect(screen.getByRole("region", { name: "建议补充" })).not.toHaveTextContent("补充证据")
  expect(fetchMock).not.toHaveBeenCalled()
})

it("keeps the evidence CTA read-only without knowledge create permission", async () => {
  const fetchMock = vi.fn((path: string) => path.startsWith("/api/v1/knowledge/")
    ? Promise.resolve(json({ results: [] }))
    : Promise.resolve(page([])))
  await renderCompany(fetchMock, ["knowledge.read"])

  const evidenceRegion = screen.getByRole("region", { name: "证据覆盖" })
  expect(await within(evidenceRegion).findByText("还没有可追溯的证据依据。")).toBeVisible()
  expect(within(evidenceRegion).getByRole("link", { name: "查看知识库" })).toHaveAttribute("href", "/knowledge")
  expect(within(evidenceRegion).queryByRole("link", { name: /补充|管理/ })).not.toBeInTheDocument()
  expect(evidenceRegion).toHaveTextContent("如需补充或编辑，请联系管理员。")
})

it("does not turn a failed knowledge contributor into composite or evidence gaps", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return Promise.resolve(page([]))
    if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(json({ detail: "offline" }, 503))
    if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(json({ results: [] }))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock, ["products.read", "knowledge.read"])

  expect(await screen.findByText("已确认 1 项，另有资料暂无法判断")).toBeVisible()
  const gaps = screen.getByRole("region", { name: "建议补充" })
  expect(gaps).toHaveTextContent("补充产品")
  expect(gaps).not.toHaveTextContent(/补充能力|补充行业|补充工艺|补充标准|补充证据/)
})

it.each([
  { label: "products only", permissions: ["products.read"], expected: ["补充产品", "补充能力", "补充行业", "补充工艺", "补充标准"], count: 5 },
  { label: "knowledge only", permissions: ["knowledge.read"], expected: ["补充能力", "补充行业", "补充工艺", "补充标准", "补充证据"], count: 5 },
  { label: "neither source", permissions: [], expected: [], count: 0 },
])("uses only readable contributors for $label category readiness", async ({ permissions, expected, count }) => {
  const fetchMock = vi.fn((path: string) => path.startsWith("/api/v1/knowledge/")
    ? Promise.resolve(json({ results: [] }))
    : Promise.resolve(page([])))
  await renderCompany(fetchMock, permissions)

  const gaps = screen.getByRole("region", { name: "建议补充" })
  await waitFor(() => expect(gaps).toHaveTextContent(`${count} 项`))
  for (const title of expected) expect(gaps).toHaveTextContent(title)
})

it("prevents an initial cursor cycle from refetching or double-counting products", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/products?status=ACTIVE") return Promise.resolve(json({
      next: "/api/v1/products?status=ACTIVE", previous: null,
      results: [{ id: "product-1", status: "ACTIVE", name_zh: "唯一产品", manufacturing_capabilities: [], inspection_capabilities: [], concept_links: [] }],
    }))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock, ["products.read"])

  expect(await screen.findByText("已安全加载前 1 个启用产品")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "产品" })).getAllByText("唯一产品")).toHaveLength(1)
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it("deduplicates products by id across complete pages", async () => {
  const product = { id: "product-1", status: "ACTIVE", name_zh: "重复产品", manufacturing_capabilities: [], inspection_capabilities: [], concept_links: [] }
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/products?status=ACTIVE") return Promise.resolve(json({ next: "/api/v1/products?cursor=2&status=ACTIVE", previous: null, results: [product] }))
    if (path === "/api/v1/products?cursor=2&status=ACTIVE") return Promise.resolve(json({
      next: null, previous: "/api/v1/products?status=ACTIVE",
      results: [product, { ...product, id: "product-2", name_zh: "第二产品" }],
    }))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock, ["products.read"])

  expect(await screen.findByText("已读取全部 2 个启用产品")).toBeVisible()
  expect(within(screen.getByRole("region", { name: "产品" })).getAllByText("重复产品")).toHaveLength(1)
  expect(screen.getByText("第二产品")).toBeVisible()
})

it("summarizes only currently available company data and links to existing editors", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/products?status=ACTIVE") return Promise.resolve(page([{ id: "p1", status: "ACTIVE" }, { id: "p2", status: "ACTIVE" }]))
    if (path === "/api/v1/knowledge/concepts?status=APPROVED") return Promise.resolve(json({ results: [{
      id: "k1", scope: "ORGANIZATION", organization: "org-1", status: "APPROVED",
      concept_type: "PRODUCT_TYPE", label_zh: "公司知识", label_en: "", evidence: [],
    }] }))
    if (path === "/api/v1/knowledge/evidence?status=APPROVED") return Promise.resolve(json({ results: [] }))
    if (path === "/api/v1/assets?status=ACTIVE") return Promise.resolve(page([{ id: "a1", status: "ACTIVE" }, { id: "a2", status: "ACTIVE" }, { id: "a3", status: "ACTIVE" }]))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock)

  expect(await screen.findByRole("heading", { name: "产品资料" })).toBeVisible()
  expect(await screen.findByText("已读取全部 2 个启用产品")).toBeVisible()
  expect(await screen.findByText("当前可见 1 条知识")).toBeVisible()
  expect(await screen.findByText("当前页有 3 份素材")).toBeVisible()
  expect(screen.getByRole("link", { name: "管理产品资料" })).toHaveAttribute("href", "/products")
  expect(screen.getByRole("link", { name: "去知识库补充" })).toHaveAttribute("href", "/knowledge")
  expect(screen.getByRole("link", { name: "管理素材" })).toHaveAttribute("href", "/assets")
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
  expect(document.body).not.toHaveTextContent(/Ontology|SourceSignal|PERMISSION_DENIED|IN_REVIEW/)
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
    if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(json({ results: [{
      id: "k1", scope: "ORGANIZATION", organization: "org-1", status: "APPROVED",
      concept_type: "PRODUCT_TYPE", label_zh: "公司知识", label_en: "", evidence: [],
    }] }))
    if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(json({ results: [] }))
    return Promise.resolve(page([{ id: "a1", status: "ACTIVE" }]))
  })
  const user = userEvent.setup()
  await renderCompany(fetchMock)

  const productRegion = await screen.findByRole("region", { name: "产品" })
  expect(await within(productRegion).findByRole("alert")).toHaveTextContent("产品资料暂时无法读取")
  expect(await screen.findByText("当前可见 1 条知识")).toBeVisible()
  expect(screen.getByRole("region", { name: "资料完整度" })).toHaveTextContent("部分资料暂不可用")
  expect(screen.getByRole("region", { name: "资料完整度" })).not.toHaveTextContent("仍有可补充项")
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
