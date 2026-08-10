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

it("summarizes only currently available company data and links to existing editors", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/products") return Promise.resolve(page([{ id: "p1" }, { id: "p2" }]))
    if (path === "/api/v1/knowledge/concepts") return Promise.resolve(json({ results: [{ id: "k1" }] }))
    if (path === "/api/v1/assets") return Promise.resolve(page([{ id: "a1" }, { id: "a2" }, { id: "a3" }]))
    throw new Error(`Unexpected request: ${path}`)
  })
  await renderCompany(fetchMock)

  expect(await screen.findByRole("heading", { name: "公司资料" })).toBeVisible()
  expect(await screen.findByText("当前页有 2 个产品")).toBeVisible()
  expect(await screen.findByText("当前可见 1 条知识")).toBeVisible()
  expect(await screen.findByText("当前页有 3 份素材")).toBeVisible()
  expect(screen.getByRole("link", { name: "管理产品资料" })).toHaveAttribute("href", "/products")
  expect(screen.getByRole("link", { name: "管理公司知识" })).toHaveAttribute("href", "/knowledge")
  expect(screen.getByRole("link", { name: "管理素材" })).toHaveAttribute("href", "/assets")
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
})

it("shows honest empty guidance instead of invented company facts", async () => {
  const fetchMock = vi.fn((path: string) => path === "/api/v1/knowledge/concepts"
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
    if (path === "/api/v1/products") return Promise.resolve(json({ detail: "offline" }, 503))
    if (path === "/api/v1/knowledge/concepts") return Promise.resolve(json({ results: [{ id: "k1" }] }))
    return Promise.resolve(page([{ id: "a1" }]))
  })
  const user = userEvent.setup()
  await renderCompany(fetchMock)

  const productRegion = await screen.findByRole("region", { name: "产品资料" })
  expect(await within(productRegion).findByRole("alert")).toHaveTextContent("产品资料暂时无法读取")
  expect(await screen.findByText("当前可见 1 条知识")).toBeVisible()
  expect(await screen.findByText("当前页有 1 份素材")).toBeVisible()
  await user.click(within(productRegion).getByRole("button", { name: "重新加载产品资料" }))
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/products", expect.any(Object))
})

it("permission-gates every source and editor link", async () => {
  const fetchMock = vi.fn().mockResolvedValue(json({ results: [] }))
  await renderCompany(fetchMock, ["knowledge.read"])

  expect(await screen.findByText("你没有查看产品资料的权限。")).toBeVisible()
  expect(screen.getByText("你没有查看素材的权限。")).toBeVisible()
  expect(screen.queryByRole("link", { name: /产品/ })).not.toBeInTheDocument()
  expect(await screen.findByRole("link", { name: "查看知识库" })).toHaveAttribute("href", "/knowledge")
  expect(screen.getByText(/如需补充，请联系管理员/)).toBeVisible()
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it.each([
  { read: "products.read", action: "查看产品库", path: "/products" },
  { read: "knowledge.read", action: "查看知识库", path: "/knowledge" },
  { read: "assets.read", action: "查看素材库", path: "/assets" },
])("uses read-only wording for $read without implying mutation authority", async ({ read, action, path }) => {
  const fetchMock = vi.fn((requestPath: string) => requestPath === "/api/v1/knowledge/concepts"
    ? Promise.resolve(json({ results: [] }))
    : Promise.resolve(page([])))
  await renderCompany(fetchMock, [read])

  expect(await screen.findByRole("link", { name: action })).toHaveAttribute("href", path)
  expect(screen.queryByRole("link", { name: /补充|管理/ })).not.toBeInTheDocument()
  expect(screen.getByText(/如需补充，请联系管理员/)).toBeVisible()
})

it("updates source actions when the current user's permissions change", async () => {
  const fetchMock = vi.fn((path: string) => path === "/api/v1/knowledge/concepts"
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
