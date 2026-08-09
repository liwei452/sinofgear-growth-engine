import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import ProductLibraryPage from "./ProductLibraryPage.vue"

const userWith = (permissions: string[]): CurrentUser => ({
  user: { id: 1, username: "operator" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "OPERATOR", status: "ACTIVE", permissions },
})

const product = {
  id: "product-1", organization: "org-1", name_zh: "精密斜齿轮", name_en: "Precision Helical Gear",
  module_min: "0.5000", module_max: "8.0000", tooth_count_min: 8, tooth_count_max: 240,
  pressure_angle: "20.000", accuracy_grade: "ISO 6", heat_treatment: "渗碳",
  surface_treatment: "喷丸", manufacturing_capabilities: ["滚齿", "磨齿"],
  inspection_capabilities: ["CMM"], moq: 10, lead_time: "4-6 周",
  landing_page_url: "https://example.com/gears/helical", status: "ACTIVE", version: 1,
  internal_notes: "", created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
  concept_links: [{
    id: "link-1", role: "MATERIAL", version: 1,
    concept: { id: "concept-1", code: "STEEL", concept_type: "MATERIAL", label_zh: "合金钢", label_en: "Alloy steel", version: 1 },
  }],
}

const concepts = [{
  id: "concept-1", scope: "SYSTEM", organization: null, concept_type: "MATERIAL", code: "STEEL",
  label_zh: "合金钢", label_en: "Alloy steel", description: "", status: "APPROVED", version: 1,
  suggested_by_ai_run_id: null, evidence: [], created_by: null, reviewed_by: 1, reviewed_at: null,
  created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
}]

async function renderPage(permissions = ["products.read", "products.manage"]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(permissions))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/products", component: ProductLibraryPage }],
  })
  await router.push("/products")
  const result = render(ProductLibraryPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()
  return { ...result, queryClient }
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("shows loading, then real products with status, specifications, delivery, and tags", async () => {
  let finish!: (response: Response) => void
  const pending = new Promise<Response>((resolve) => { finish = resolve })
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/products")) return pending
    return Promise.resolve(new Response(JSON.stringify({ results: concepts }), {
      status: 200, headers: { "Content-Type": "application/json" },
    }))
  })
  vi.stubGlobal("fetch", fetchMock)
  await renderPage()

  expect(screen.getByRole("status")).toHaveTextContent("正在加载产品")
  finish(new Response(JSON.stringify({ next: null, previous: null, results: [product] }), {
    status: 200, headers: { "Content-Type": "application/json" },
  }))

  expect(await screen.findByRole("heading", { name: "产品库" })).toBeInTheDocument()
  expect(screen.getByText("精密斜齿轮")).toBeInTheDocument()
  expect(screen.getByText("Precision Helical Gear")).toBeInTheDocument()
  expect(screen.getByText("已启用")).toBeInTheDocument()
  expect(screen.getByText(/模数 0.5000–8.0000/)).toBeInTheDocument()
  expect(screen.getByText(/MOQ 10/)).toBeInTheDocument()
  expect(screen.getByText("合金钢")).toBeInTheDocument()
})

it("filters by status and approved concept and follows only safe pagination", async () => {
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/knowledge/concepts") {
      return new Response(JSON.stringify({ results: concepts }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    return new Response(JSON.stringify({
      next: `${window.location.origin}/api/v1/products?cursor=next-safe`,
      previous: null,
      results: [product],
    }), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  await renderPage()
  await screen.findByText("精密斜齿轮")

  await user.selectOptions(screen.getByLabelText("产品状态"), "ACTIVE")
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/products?status=ACTIVE",
    expect.anything(),
  ))
  await user.selectOptions(screen.getByLabelText("材料标签"), "STEEL")
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/products?status=ACTIVE&material=STEEL",
    expect.anything(),
  ))
  await user.click(screen.getByRole("button", { name: "下一页" }))
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/products?cursor=next-safe",
    expect.anything(),
  )
})

it("shows an actionable empty state and hides write controls without permission", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(
    path === "/api/v1/knowledge/concepts"
      ? { results: [] }
      : { next: null, previous: null, results: [] },
  ), { status: 200, headers: { "Content-Type": "application/json" } })))
  await renderPage(["products.read"])

  expect(await screen.findByText("还没有符合条件的产品")).toBeInTheDocument()
  expect(screen.getByText("可以清除筛选后再看，或联系有权限的同事新建产品。")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "新建产品" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument()
})

it("keeps product details read-only without products.manage", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    const body = path === "/api/v1/knowledge/concepts" ? { results: concepts }
      : path === "/api/v1/products/product-1" ? product
        : { next: null, previous: null, results: [product] }
    return new Response(JSON.stringify(body), {
      status: 200, headers: { "Content-Type": "application/json", ETag: '"1"' },
    })
  }))
  const user = userEvent.setup()
  await renderPage(["products.read"])
  await screen.findByText("精密斜齿轮")
  await user.click(screen.getByRole("button", { name: "查看" }))
  expect(await screen.findByRole("dialog")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "保存修改" })).not.toBeInTheDocument()
})

it("shows a safe error and retries the list", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(null, { status: 503 }))
    .mockResolvedValue(new Response(JSON.stringify({ next: null, previous: null, results: [] }), {
      status: 200, headers: { "Content-Type": "application/json" },
    }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  await renderPage()

  expect(await screen.findByRole("alert")).toHaveTextContent("服务暂时不可用，请稍后重试。")
  await user.click(screen.getByRole("button", { name: "重新加载产品" }))
  expect(await screen.findByText("还没有符合条件的产品")).toBeInTheDocument()
})
