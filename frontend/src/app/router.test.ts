import { QueryClient } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { defineComponent, h } from "vue"
import { createMemoryHistory, RouterView } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import { createAppRouter, safeRedirect } from "./router"

const Login = defineComponent({ name: "LoginStub", template: "<p>Login</p>" })
const Shell = defineComponent({ name: "ShellStub", template: "<router-view />" })
const Stub = (name: string, label: string) => defineComponent({ name, template: `<p>${label}</p>` })
const Root = defineComponent({ setup: () => () => h(RouterView) })

function makeComponents() {
  return {
    Login,
    Shell,
    Dashboard: Stub("DashboardStub", "Dashboard"),
    Promotion: Stub("PromotionStub", "Promotion"),
    Opportunities: Stub("OpportunitiesStub", "Opportunities"),
    ContentPublishing: Stub("ContentPublishingStub", "Content publishing"),
    Results: Stub("ResultsStub", "Results"),
    Missions: Stub("MissionsStub", "Missions"),
    MissionDetail: Stub("MissionDetailStub", "Mission detail"),
    Company: Stub("CompanyStub", "Company"),
    Help: Stub("HelpStub", "Help"),
    Settings: Stub("SettingsStub", "Settings"),
    AIModelSettings: Stub("AIModelSettingsStub", "AI model"),
    MapsDiscovery: Stub("MapsDiscoveryStub", "Maps discovery"),
    Products: Stub("ProductsStub", "Products"),
    Knowledge: Stub("KnowledgeStub", "Knowledge"),
    Assets: Stub("AssetsStub", "Assets"),
    PlatformAccounts: Stub("AccountsStub", "Platform accounts"),
    RoleHome: Stub("RoleHomeStub", "Home"),
    Attribution: Stub("AttributionStub", "Attribution"),
    Placeholder: Stub("PlaceholderStub", "Placeholder"),
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

describe("business-outcome routing", () => {
  it("mounts the five business workspaces without changing mission deep links", async () => {
    const client = queryClient()
    setUser(client, "OPERATOR", ["missions.read", "leads.manage", "publishing.read"])
    const appRouter = router(client)
    render(Root, { global: { plugins: [appRouter] } })

    await appRouter.push("/promotion")
    expect(appRouter.currentRoute.value.name).toBe("promotion")
    await appRouter.push("/opportunities")
    expect(appRouter.currentRoute.value.name).toBe("opportunities")
    await appRouter.push("/content-factory")
    expect(appRouter.currentRoute.value.name).toBe("content-publishing")
    await appRouter.push("/analytics")
    expect(appRouter.currentRoute.value.name).toBe("results")
    await appRouter.push("/missions/mission-1")
    expect(appRouter.currentRoute.value.name).toBe("mission-detail")
  })

  it("preserves existing module routes", async () => {
    const client = queryClient()
    setUser(client, "OPERATOR", ["missions.read", "assets.read"])
    const appRouter = router(client)
    render(Root, { global: { plugins: [appRouter] } })

    await appRouter.push("/missions")
    expect(await screen.findByText("Missions")).toBeInTheDocument()
    await appRouter.push("/assets")
    expect(await screen.findByText("Assets")).toBeInTheDocument()
    await appRouter.push("/attribution")
    expect(await screen.findByText("Attribution")).toBeInTheDocument()
  })

  it("keeps administrator and granular permission guards for existing deep links", async () => {
    const operatorClient = queryClient()
    setUser(operatorClient, "OPERATOR", ["products.read"])
    const operatorRouter = router(operatorClient)
    await operatorRouter.push("/products")
    expect(operatorRouter.currentRoute.value.name).toBe("home")
    expect(operatorRouter.currentRoute.value.query.blocked).toBe("administrator")

    const administratorClient = queryClient()
    setUser(administratorClient, "ADMINISTRATOR", [])
    const administratorRouter = router(administratorClient)
    await administratorRouter.push("/products")
    expect(administratorRouter.currentRoute.value.name).toBe("settings")
    expect(administratorRouter.currentRoute.value.query.blocked).toBe("products.read")
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
    "https://evil.example/steal", "//evil.example/steal", "\\evil.example\\steal",
    "/safe\nLocation:https://evil.example", "products", ["/products", "//evil.example"], undefined,
  ])("drops an unsafe redirect value %#", (value) => {
    expect(safeRedirect(value)).toBe("/")
  })
})
