import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import ProductLibraryPage from "../products/ProductLibraryPage.vue"
import { knowledgeQueryKeys } from "./api"
import KnowledgeLibraryPage from "./KnowledgeLibraryPage.vue"

it("filters capability concepts using the typed Chinese label", async () => {
  vi.stubGlobal("fetch", mockLists([
    concept({ concept_type: "CAPABILITY", code: "CAP-GEAR-GRINDING", label_zh: "磨齿能力" }),
  ]))
  const user = userEvent.setup()
  renderPage()

  await screen.findByText("磨齿能力")
  await user.selectOptions(screen.getByLabelText("类型"), "CAPABILITY")

  expect(screen.getByText("能力", { selector: "dd" })).toBeInTheDocument()
  expect(screen.getByText("CAP-GEAR-GRINDING")).toBeInTheDocument()
})

const userWith = (permissions: string[]): CurrentUser => ({
  user: { id: 1, username: "operator" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "CUSTOM", status: "ACTIVE", permissions },
})

const concept = (overrides: Record<string, unknown> = {}) => ({
  id: "concept-1", scope: "ORGANIZATION", organization: "org-1", concept_type: "MATERIAL",
  code: "ALLOY_STEEL", label_zh: "合金钢", label_en: "Alloy steel", description: "适合精密齿轮",
  status: "SUGGESTED", version: 1, evidence: ["evidence-1"], suggested_by_ai_run_id: null,
  created_by: 1, reviewed_by: null, reviewed_at: null,
  created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z", ...overrides,
})

function mockLists(concepts = [concept()]) {
  return vi.fn(async (path: string) => new Response(JSON.stringify({
    results: path === "/api/v1/knowledge/concepts" ? concepts
      : path === "/api/v1/knowledge/aliases" ? [{ id: "alias-1" }]
        : path === "/api/v1/knowledge/relations" ? [{ id: "relation-1" }, { id: "relation-2" }]
          : [{ id: "evidence-1" }],
  }), { status: 200, headers: { "Content-Type": "application/json" } }))
}

function renderPage(permissions = ["knowledge.read", "knowledge.create", "knowledge.review_organization"]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(permissions))
  return render(KnowledgeLibraryPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
}

function renderPageWithClient(queryClient: QueryClient, currentUser: CurrentUser) {
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser)
  return render(KnowledgeLibraryPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

afterEach(() => { vi.unstubAllGlobals(); document.cookie = "csrftoken=; Max-Age=0; path=/" })

it("explains the library and renders real counts, evidence, bilingual labels, and statuses", async () => {
  vi.stubGlobal("fetch", mockLists())
  renderPage()

  expect(await screen.findByRole("heading", { name: "知识库" })).toBeInTheDocument()
  expect(screen.getByText(/统一产品、材料和应用的叫法/)).toBeInTheDocument()
  expect(await screen.findByText("合金钢")).toBeInTheDocument()
  expect(screen.getByText("Alloy steel")).toBeInTheDocument()
  expect(screen.getByText("ALLOY_STEEL")).toBeInTheDocument()
  expect(screen.getByText("待审核")).toBeInTheDocument()
  expect(screen.getByText("1 条证据")).toBeInTheDocument()
  expect(screen.getByText("1 个名称")).toBeInTheDocument()
  expect(screen.getByText("2 条关系")).toBeInTheDocument()
  expect(screen.getByText("1 条证据资料")).toBeInTheDocument()
})

it("searches Chinese, English, and code and combines status, type, and scope filters", async () => {
  vi.stubGlobal("fetch", mockLists([
    concept(),
    concept({ id: "concept-2", code: "HELICAL_GEAR", label_zh: "斜齿轮", label_en: "Helical gear", concept_type: "PRODUCT_TYPE", status: "APPROVED", scope: "SYSTEM", organization: null }),
  ]))
  const user = userEvent.setup()
  renderPage()
  await screen.findByText("合金钢")

  await user.type(screen.getByLabelText("搜索知识"), "helical")
  expect(screen.queryByText("合金钢")).not.toBeInTheDocument()
  expect(screen.getByText("斜齿轮")).toBeInTheDocument()
  await user.clear(screen.getByLabelText("搜索知识"))
  await user.type(screen.getByLabelText("搜索知识"), "ALLOY")
  expect(screen.getByText("合金钢")).toBeInTheDocument()
  await user.clear(screen.getByLabelText("搜索知识"))
  await user.selectOptions(screen.getByLabelText("状态"), "APPROVED")
  await user.selectOptions(screen.getByLabelText("类型"), "PRODUCT_TYPE")
  await user.selectOptions(screen.getByLabelText("范围"), "SYSTEM")
  expect(screen.getByText("斜齿轮")).toBeInTheDocument()
  expect(screen.queryByText("合金钢")).not.toBeInTheDocument()
})

it("shows create and legal review controls only from permission codes and refreshes a review", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const reviewed = concept({ status: "APPROVED", reviewed_by: 1 })
  const fetchMock = mockLists()
  fetchMock.mockImplementation(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/approve") && options?.method === "POST") return new Response(JSON.stringify(reviewed), { status: 200, headers: { "Content-Type": "application/json" } })
    return mockLists() (path)
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["knowledge.read", "knowledge.review_organization"])
  await screen.findByText("合金钢")

  expect(screen.queryByRole("button", { name: "新增知识建议" })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "通过" })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "通过" }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/knowledge/concepts/concept-1/approve", expect.objectContaining({ method: "POST" }),
  ))
  expect(await screen.findByText("已通过“合金钢”")).toBeInTheDocument()
})

it("hides SYSTEM review without system permission and renders an actionable empty result", async () => {
  const systemSuggested = concept({ scope: "SYSTEM", organization: null })
  vi.stubGlobal("fetch", mockLists([systemSuggested]))
  const user = userEvent.setup()
  renderPage(["knowledge.read", "knowledge.review_organization"])
  await screen.findByText("合金钢")
  expect(screen.queryByRole("button", { name: "通过" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "驳回" })).not.toBeInTheDocument()

  vi.unstubAllGlobals()
  vi.stubGlobal("fetch", mockLists([]))
  renderPage(["knowledge.read"])
  expect(await screen.findByText("没有找到符合条件的知识")).toBeInTheDocument()
  await user.type(screen.getAllByLabelText("搜索知识").at(-1)!, "不存在")
})

it.each([
  { name: "system manager without reviewer", permissions: ["knowledge.read", "knowledge.manage_system"], scope: "SYSTEM", visible: false },
  { name: "organization reviewer on organization", permissions: ["knowledge.read", "knowledge.review_organization"], scope: "ORGANIZATION", visible: true },
  { name: "organization reviewer on system", permissions: ["knowledge.read", "knowledge.review_organization"], scope: "SYSTEM", visible: false },
  { name: "system reviewer with both permissions", permissions: ["knowledge.read", "knowledge.review_organization", "knowledge.manage_system"], scope: "SYSTEM", visible: true },
  { name: "administrator permission set", permissions: ["knowledge.read", "knowledge.create", "knowledge.review_organization", "knowledge.manage_system", "knowledge.deprecate"], scope: "SYSTEM", visible: true },
])("enforces the review permission matrix for $name", async ({ permissions, scope, visible }) => {
  const fetchMock = mockLists([concept({ scope, organization: scope === "SYSTEM" ? null : "org-1" })])
  vi.stubGlobal("fetch", fetchMock)
  renderPage(permissions)
  await screen.findByText("合金钢")

  if (visible) {
    expect(screen.getByRole("button", { name: "通过" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "驳回" })).toBeInTheDocument()
  } else {
    expect(screen.queryByRole("button", { name: "通过" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "驳回" })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/approve") || String(path).endsWith("/reject"))).toBe(false)
  }
})

it("does not submit SYSTEM suggestions with organization-create permission alone", async () => {
  vi.stubGlobal("fetch", mockLists([concept({ scope: "SYSTEM", organization: null })]))
  renderPage(["knowledge.read", "knowledge.create"])

  await screen.findByText("合金钢")
  expect(screen.queryByRole("button", { name: "提交审核" })).not.toBeInTheDocument()
})

it("requires a rejection reason and sends it before refreshing the state", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const rejected = concept({ status: "REJECTED" })
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/reject") && options?.method === "POST") return new Response(JSON.stringify(rejected), { status: 200, headers: { "Content-Type": "application/json" } })
    return mockLists()(path)
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup(); renderPage(["knowledge.read", "knowledge.review_organization"])
  await screen.findByText("合金钢")
  await user.click(screen.getByRole("button", { name: "驳回" }))
  await user.click(screen.getByRole("button", { name: "确认驳回" }))
  expect(screen.getByRole("alert")).toHaveTextContent("请填写驳回原因")
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/reject"))).toBe(false)
  await user.type(screen.getByLabelText("驳回原因（必填）"), "信息重复")
  await user.click(screen.getByRole("button", { name: "确认驳回" }))
  expect(await screen.findByText("已驳回“合金钢”")).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/knowledge/concepts/concept-1/reject", expect.objectContaining({ body: JSON.stringify({ comment: "信息重复" }) }))
})

it("shows a safe service error and retries all real lists", async () => {
  let conceptAttempt = 0
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/knowledge/concepts" && conceptAttempt++ === 0) return new Response(null, { status: 503 })
    return new Response(JSON.stringify({ results: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup(); renderPage(["knowledge.read"])
  expect(await screen.findByRole("alert")).toHaveTextContent("服务暂时不可用，请稍后重试")
  await user.click(screen.getByRole("button", { name: "重新加载知识库" }))
  expect(await screen.findByText("没有找到符合条件的知识")).toBeInTheDocument()
})

it("never renders a fresh knowledge cache from another organization on the same query client", async () => {
  let activeOrganization = "org-a"
  const fetchMock = vi.fn(async (path: string) => new Response(JSON.stringify({
    results: path === "/api/v1/knowledge/concepts"
      ? [concept({
        id: `concept-${activeOrganization}`,
        organization: activeOrganization,
        label_zh: activeOrganization === "org-a" ? "组织 A 知识" : "组织 B 知识",
      })]
      : [],
  }), { status: 200, headers: { "Content-Type": "application/json" } }))
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })

  const first = renderPageWithClient(queryClient, {
    ...userWith(["knowledge.read"]), organization: { id: "org-a", name: "组织 A", slug: "a" },
  })
  expect(await screen.findByText("组织 A 知识")).toBeInTheDocument()
  first.unmount()
  activeOrganization = "org-b"

  renderPageWithClient(queryClient, {
    ...userWith(["knowledge.read"]), organization: { id: "org-b", name: "组织 B", slug: "b" },
  })
  expect(screen.queryByText("组织 A 知识")).not.toBeInTheDocument()
  expect(await screen.findByText("组织 B 知识")).toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([path]) => path === "/api/v1/knowledge/concepts")).toHaveLength(2)
})

it("invalidates the fresh product-concept cache after review so the product page refetches approved applications", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let reviewed = false
  const suggested = concept({ concept_type: "INDUSTRY", code: "AUTOMOTIVE", label_zh: "汽车行业" })
  const approved = concept({ ...suggested, status: "APPROVED", reviewed_by: 1 })
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/approve") && options?.method === "POST") {
      reviewed = true
      return new Response(JSON.stringify(approved), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/knowledge/concepts") {
      return new Response(JSON.stringify({ results: [reviewed ? approved : suggested] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    if (path === "/api/v1/products") {
      return new Response(JSON.stringify({ next: null, previous: null, results: [] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    return new Response(JSON.stringify({ results: [] }), {
      status: 200, headers: { "Content-Type": "application/json" },
    })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  queryClient.setQueryData(knowledgeQueryKeys.productConcepts("org-1"), [])
  const user = userEvent.setup()
  const knowledge = renderPageWithClient(queryClient, userWith([
    "knowledge.read", "knowledge.review_organization",
  ]))
  await screen.findByText("汽车行业")
  await user.click(screen.getByRole("button", { name: "通过" }))
  await screen.findByText("已通过“汽车行业”")
  knowledge.unmount()

  render(ProductLibraryPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
  expect(await screen.findByRole("option", { name: "汽车行业" })).toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([path]) => path === "/api/v1/knowledge/concepts")).toHaveLength(2)
})

it.each([
  { action: "reject", startStatus: "SUGGESTED", resultStatus: "REJECTED", button: "驳回", notice: "已驳回“汽车行业”" },
  { action: "deprecate", startStatus: "APPROVED", resultStatus: "DEPRECATED", button: "停用", notice: "已停用“汽车行业”" },
])("removes stale approved product concepts after $action", async ({ action, startStatus, resultStatus, button, notice }) => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let reviewed = false
  const approved = concept({
    concept_type: "INDUSTRY", code: "AUTOMOTIVE", label_zh: "汽车行业", status: "APPROVED", reviewed_by: 1,
  })
  const starting = concept({ ...approved, status: startStatus })
  const updated = concept({ ...approved, status: resultStatus })
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith(`/${action}`) && options?.method === "POST") {
      reviewed = true
      return new Response(JSON.stringify(updated), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/knowledge/concepts") {
      return new Response(JSON.stringify({ results: [reviewed ? updated : starting] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    if (path === "/api/v1/products") {
      return new Response(JSON.stringify({ next: null, previous: null, results: [] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    return new Response(JSON.stringify({ results: [] }), {
      status: 200, headers: { "Content-Type": "application/json" },
    })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  queryClient.setQueryData(knowledgeQueryKeys.productConcepts("org-1"), [approved])
  const user = userEvent.setup()
  const knowledge = renderPageWithClient(queryClient, userWith([
    "knowledge.read", "knowledge.review_organization", "knowledge.deprecate",
  ]))
  await screen.findByText("汽车行业")
  await user.click(screen.getByRole("button", { name: button }))
  if (action === "reject") {
    await user.type(screen.getByLabelText("驳回原因（必填）"), "不再适用")
    await user.click(screen.getByRole("button", { name: "确认驳回" }))
  }
  await screen.findByText(notice)
  knowledge.unmount()

  render(ProductLibraryPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
  await waitFor(() => expect(fetchMock.mock.calls.filter(
    ([path]) => path === "/api/v1/knowledge/concepts",
  )).toHaveLength(2))
  await waitFor(() => expect(screen.queryByRole("option", { name: "汽车行业" })).not.toBeInTheDocument())
})
