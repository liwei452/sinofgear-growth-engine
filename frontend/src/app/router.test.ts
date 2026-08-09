import { QueryClient } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { defineComponent, h } from "vue"
import { createMemoryHistory, RouterView } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import { createAppRouter, safeRedirect } from "./router"

const Login = defineComponent({ name: "LoginStub", template: "<p>登录页面</p>" })
const Shell = defineComponent({ name: "ShellStub", template: "<router-view />" })
const Dashboard = defineComponent({ name: "DashboardStub", template: "<p>首页内容</p>" })
const Products = defineComponent({ name: "ProductsStub", template: "<p>真实产品库</p>" })
const Knowledge = defineComponent({ name: "KnowledgeStub", template: "<p>真实知识库</p>" })
const ContentFactory = defineComponent({ name: "ContentFactoryStub", template: "<p>真实内容工厂</p>" })
const Reviews = defineComponent({ name: "ReviewsStub", template: "<p>真实审核中心</p>" })
const Placeholder = defineComponent({ name: "PlaceholderStub", template: "<p>占位内容</p>" })
const Root = defineComponent({ setup: () => () => h(RouterView) })

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

function queryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function router(client = queryClient(), initialPath?: string) {
  const history = createMemoryHistory()
  if (initialPath) history.push(initialPath)
  return createAppRouter(client, {
    history,
    components: { Login, Shell, Dashboard, Products, Knowledge, ContentFactory, Reviews, Placeholder },
  })
}

afterEach(() => vi.unstubAllGlobals())

describe("protected routing", () => {
  it("does not mount protected content while the session request is loading", async () => {
    const pending = deferred<Response>()
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(pending.promise))
    const appRouter = router(queryClient(), "/products")
    render(Root, { global: { plugins: [appRouter] } })
    const navigation = appRouter.isReady()

    expect(screen.queryByText("真实产品库")).not.toBeInTheDocument()

    pending.resolve(new Response(JSON.stringify({
      user: { id: 1, username: "operator" },
      organization: { id: "org-1", name: "示例组织", slug: "demo" },
      membership: { id: "member-1", role: "OPERATOR", status: "ACTIVE" },
    }), { status: 200, headers: { "Content-Type": "application/json" } }))
    await navigation
    expect(await screen.findByText("真实产品库")).toBeInTheDocument()
  })

  it("mounts distinct real product and knowledge route components", async () => {
    const client = queryClient()
    client.setQueryData(["auth", "me"], { user: {}, organization: {}, membership: { permissions: [] } })
    const appRouter = router(client)
    render(Root, { global: { plugins: [appRouter] } })
    await appRouter.push("/products")
    expect(await screen.findByText("真实产品库")).toBeInTheDocument()
    await appRouter.push("/knowledge")
    expect(await screen.findByText("真实知识库")).toBeInTheDocument()
  })

  it("mounts distinct content factory and review center route components", async () => {
    const client = queryClient()
    client.setQueryData(["auth", "me"], { user: {}, organization: {}, membership: { permissions: [] } })
    const appRouter = router(client)
    render(Root, { global: { plugins: [appRouter] } })

    await appRouter.push("/content-factory")
    expect(await screen.findByText("真实内容工厂")).toBeInTheDocument()
    await appRouter.push("/reviews")
    expect(await screen.findByText("真实审核中心")).toBeInTheDocument()
    expect(screen.queryByText("占位内容")).not.toBeInTheDocument()
  })

  it.each([401, 403])("redirects status %s to login with the local target", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })))
    const appRouter = router()

    await appRouter.push("/analytics?range=7")

    expect(appRouter.currentRoute.value.name).toBe("login")
    expect(appRouter.currentRoute.value.query.redirect).toBe("/analytics?range=7")
  })
})

describe("safeRedirect", () => {
  it("keeps a normal in-app path including query and hash", () => {
    expect(safeRedirect("/products?source=home#top")).toBe("/products?source=home#top")
  })

  it.each([
    "https://evil.example/steal",
    "//evil.example/steal",
    "\\evil.example\\steal",
    "/safe\nLocation:https://evil.example",
    "products",
    ["/products", "//evil.example"],
    undefined,
  ])("drops an unsafe redirect value %#", (value) => {
    expect(safeRedirect(value)).toBe("/")
  })
})
