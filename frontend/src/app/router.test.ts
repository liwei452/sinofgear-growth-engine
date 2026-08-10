import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { defineComponent, h } from "vue"
import { createMemoryHistory, RouterView } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import PromotionTransitionPage from "../modules/promotion/PromotionTransitionPage.vue"
import { createAppRouter, safeRedirect } from "./router"

const Login = defineComponent({ name: "LoginStub", template: "<p>登录页面</p>" })
const Shell = defineComponent({ name: "ShellStub", template: "<router-view />" })
const Dashboard = defineComponent({ name: "DashboardStub", template: "<p>首页内容</p>" })
const Products = defineComponent({ name: "ProductsStub", template: "<p>真实产品库</p>" })
const Knowledge = defineComponent({ name: "KnowledgeStub", template: "<p>真实知识库</p>" })
const ContentFactory = defineComponent({ name: "ContentFactoryStub", template: "<p>真实内容工厂</p>" })
const Reviews = defineComponent({ name: "ReviewsStub", template: "<p>真实审核中心</p>" })
const Promotion = PromotionTransitionPage
const Assets = defineComponent({ name: "AssetsStub", template: "<p>真实素材库</p>" })
const PublishingCalendar = defineComponent({ name: "PublishingStub", template: "<p>真实发布日历</p>" })
const PlatformAccounts = defineComponent({ name: "AccountsStub", template: "<p>真实平台账户</p>" })
const Analytics = defineComponent({ name: "AnalyticsStub", template: "<p>真实数据看板</p>" })
const LeadRadar = defineComponent({ name: "LeadRadarStub", template: "<p>真实客户机会</p>" })
const CompanyProfile = defineComponent({ name: "CompanyProfileStub", template: "<p>真实公司资料</p>" })
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
    components: { Login, Shell, Dashboard, Promotion, Products, Knowledge, ContentFactory, Reviews, Assets, PublishingCalendar, PlatformAccounts, Analytics, LeadRadar, CompanyProfile },
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

  it("mounts all four distinct publishing operations workspaces", async () => {
    const client = queryClient()
    client.setQueryData(["auth", "me"], { user: {}, organization: {}, membership: { permissions: [] } })
    const appRouter = router(client)
    render(Root, { global: { plugins: [appRouter] } })
    for (const [path, label] of [["/assets", "真实素材库"], ["/publishing-calendar", "真实发布日历"], ["/platform-accounts", "真实平台账户"], ["/analytics", "真实数据看板"]]) {
      await appRouter.push(path)
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
  })

  it("mounts the authenticated customer-opportunity route with its plain-language title", async () => {
    const client = queryClient()
    client.setQueryData(["auth", "me"], { user: {}, organization: {}, membership: { permissions: ["leads.read"] } })
    const appRouter = router(client)
    render(Root, { global: { plugins: [appRouter] } })

    await appRouter.push("/lead-radar")

    expect(await screen.findByText("真实客户机会")).toBeInTheDocument()
    expect(appRouter.currentRoute.value.meta.title).toBe("客户机会")
  })

  it("mounts the production promotion transition and links authorized users to the content factory", async () => {
    const client = queryClient()
    client.setQueryData(["auth", "me"], { user: {}, organization: {}, membership: { permissions: ["campaigns.read"] } })
    const appRouter = router(client)
    render(Root, { global: { plugins: [[VueQueryPlugin, { queryClient: client }], appRouter] } })

    await appRouter.push("/promotion")
    expect(await screen.findByRole("heading", { name: "推广" })).toBeInTheDocument()
    expect(screen.getByText("推广工作区正在准备中")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "前往 AI 内容工厂" })).toHaveAttribute("href", "/content-factory")
    expect(screen.queryByRole("link", { name: "查看下一步建议" })).not.toBeInTheDocument()
    expect(appRouter.currentRoute.value.meta.title).toBe("推广")
  })

  it("explains the promotion transition without offering an unauthorized content-factory action", async () => {
    const client = queryClient()
    client.setQueryData(["auth", "me"], { user: {}, organization: {}, membership: { permissions: [] } })
    const appRouter = router(client)
    render(Root, { global: { plugins: [[VueQueryPlugin, { queryClient: client }], appRouter] } })

    await appRouter.push("/promotion")

    expect(await screen.findByText("你当前没有使用内容工厂的权限；如需开展推广，请联系管理员。")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "前往 AI 内容工厂" })).not.toBeInTheDocument()
  })

  it("mounts the real company profile route", async () => {
    const client = queryClient()
    client.setQueryData(["auth", "me"], { user: {}, organization: {}, membership: { permissions: [] } })
    const appRouter = router(client)
    render(Root, { global: { plugins: [appRouter] } })

    await appRouter.push("/company-profile")
    expect(await screen.findByText("真实公司资料")).toBeInTheDocument()
    expect(appRouter.currentRoute.value.meta.title).toBe("公司资料")
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
