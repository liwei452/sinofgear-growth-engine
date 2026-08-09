import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import KnowledgeLibraryPage from "./KnowledgeLibraryPage.vue"

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
