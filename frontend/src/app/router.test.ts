import { QueryClient } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { defineComponent, h } from "vue"
import { createMemoryHistory, RouterView } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import { createAppRouter, safeRedirect } from "./router"

const Login = defineComponent({ name: "LoginStub", template: "<p>登录页面</p>" })
const Shell = defineComponent({ name: "ShellStub", template: "<router-view />" })
const Stub = (name: string, label: string) => defineComponent({
  name,
  template: `<p>${label}</p>`,
})
const Root = defineComponent({ setup: () => () => h(RouterView) })

function makeComponents() {
  return {
    Login,
    Shell,
    Dashboard: Stub("DashboardStub", "首页"),
    Missions: Stub("MissionsStub", "增长任务"),
    MissionDetail: Stub("MissionDetailStub", "任务详情"),
    Company: Stub("CompanyStub", "公司"),
    Settings: Stub("SettingsStub", "设置中心"),
    AIModelSettings: Stub("AIModelSettingsStub", "AI 模型"),
    MapsDiscovery: Stub("MapsDiscoveryStub", "地图获客"),
    Products: Stub("ProductsStub", "产品库"),
    Knowledge: Stub("KnowledgeStub", "知识库"),
    Assets: Stub("AssetsStub", "素材库"),
    PlatformAccounts: Stub("AccountsStub", "平台账户"),
    RoleHome: Stub("RoleHomeStub", "首页"),
    Attribution: Stub("AttributionStub", "数据归因"),
    Placeholder: Stub("PlaceholderStub", "占位"),
  }
}

function queryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function setUser(client: QueryClient, role: string, permissions: string[]) {
  client.setQueryData(["auth", "me"], {
    user: { id: 1, username: "u" },
    organization: { id: "o1", name: "Org", slug: "org" },
    membership: { id: "m1", role, status: "ACTIVE", permissions },
  })
}

function router(client = queryClient(), initialPath?: string) {
  const history = createMemoryHistory()
  if (initialPath) history.push(initialPath)
  return createAppRouter(client, { history, components: makeComponents() })
}

afterEach(() => vi.unstubAllGlobals())

describe("growth-mission routing", () => {
  it("mounts mission, assets, and attribution routes", async () => {
    const client = queryClient()
    setUser(client, "OPERATOR", ["missions.read", "assets.read"])
    const appRouter = router(client)
    render(Root, { global: { plugins: [appRouter] } })

    await appRouter.push("/missions")
    expect(await screen.findByText("增长任务")).toBeInTheDocument()
    await appRouter.push("/assets")
    expect(await screen.findByText("素材库")).toBeInTheDocument()
    await appRouter.push("/attribution")
    expect(await screen.findByText("数据归因")).toBeInTheDocument()
  })

  it("redirects legacy workflow paths to the mission surfaces", async () => {
    const client = queryClient()
    setUser(client, "OPERATOR", ["missions.read", "agents.approve", "assets.read"])
    const appRouter = router(client)
    render(Root, { global: { plugins: [appRouter] } })

    for (const path of ["/promotion", "/opportunities", "/content-factory", "/reviews", "/publishing-calendar"]) {
      await appRouter.push(path)
      expect(appRouter.currentRoute.value.name).toBe("missions")
    }

    await appRouter.push("/content")
    expect(appRouter.currentRoute.value.name).toBe("assets")

    await appRouter.push("/analytics?range=7")
    expect(appRouter.currentRoute.value.name).toBe("attribution")

    await appRouter.push("/agent-approvals")
    expect(appRouter.currentRoute.value.name).toBe("home")
    expect(appRouter.currentRoute.value.query.view).toBe("approvals")
  })

  it("sends a non-administrator home for an administrator-only route", async () => {
    const client = queryClient()
    setUser(client, "OPERATOR", ["products.read"])
    const appRouter = router(client)

    await appRouter.push("/products")
    expect(appRouter.currentRoute.value.name).toBe("home")
    expect(appRouter.currentRoute.value.query.blocked).toBe("administrator")
  })

  it("keeps a missing granular permission on the administrator settings page", async () => {
    const client = queryClient()
    setUser(client, "ADMINISTRATOR", [])
    const appRouter = router(client)

    await appRouter.push("/products")
    expect(appRouter.currentRoute.value.name).toBe("settings")
    expect(appRouter.currentRoute.value.query.blocked).toBe("products.read")
  })

  it.each([401, 403])("redirects status %s to login with the local target", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })))
    const appRouter = router()

    await appRouter.push("/analytics?range=7")
    expect(appRouter.currentRoute.value.name).toBe("login")
    expect(appRouter.currentRoute.value.query.redirect).toBe("/attribution?range=7")
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
