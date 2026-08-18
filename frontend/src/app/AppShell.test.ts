import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { defineComponent, h } from "vue"
import { createMemoryHistory, createRouter, RouterView } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import AppShell from "./AppShell.vue"
import { currentUserQueryOptions } from "../modules/auth/auth"
import PlaceholderPage from "../shared/components/PlaceholderPage.vue"

const Page = defineComponent({ template: "<h1>首页内容</h1>" })
const Login = defineComponent({ template: "<p>登录页面</p>" })
const Root = defineComponent({ setup: () => () => h(RouterView) })
const currentUser = {
  user: { id: 1, username: "operator" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "OPERATOR", status: "ACTIVE", permissions: ["products.read"] },
}

function useViewport(narrow: boolean) {
  const mediaQuery = {
    matches: narrow,
    media: "(max-width: 860px)",
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue(mediaQuery))
  return mediaQuery
}

async function renderShell(
  initialPath = "/",
  { narrow = false, permissions = currentUser.membership.permissions } = {},
) {
  const mediaQuery = useViewport(narrow)
  const history = createMemoryHistory()
  history.push(initialPath)
  const router = createRouter({
    history,
    routes: [
      { path: "/login", component: Login },
      {
        path: "/",
        component: AppShell,
        children: [
          { path: "", component: Page, meta: { title: "首页" } },
          { path: "products", component: PlaceholderPage, meta: { title: "产品库" } },
          { path: ":pathMatch(.*)*", component: PlaceholderPage, meta: { title: "功能" } },
        ],
      },
    ],
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    ...currentUser,
    membership: { ...currentUser.membership, permissions },
  })
  const result = render(Root, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()
  return { ...result, router, queryClient, mediaQuery }
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("groups navigation by task and hides entries the role cannot use", async () => {
  await renderShell("/")

  for (const label of ["今天", "产品库", "公司资料", "设置中心"]) {
    expect(screen.getByRole("link", { name: label })).toBeInTheDocument()
  }
  for (const internalLabel of ["客户机会", "Agent 工作台", "内容工厂", "经营效果", "知识库", "素材库", "平台账户"]) {
    expect(screen.queryByRole("link", { name: internalLabel })).not.toBeInTheDocument()
  }
  expect(screen.getByText("示例组织")).toBeInTheDocument()
  expect(screen.getByText("operator")).toBeInTheDocument()
})

it("exposes agent, social, and effectiveness workspaces to an authorized operator", async () => {
  await renderShell("/", {
    permissions: ["agents.run", "publishing.read", "metrics.read"],
  })

  expect(screen.getByRole("link", { name: "Agent 工作台" })).toHaveAttribute(
    "href",
    "/agent-workspace",
  )
  expect(screen.getByRole("link", { name: "社媒运营" })).toHaveAttribute("href", "/promotion")
  expect(screen.getByRole("link", { name: "经营效果" })).toHaveAttribute("href", "/analytics")
})

it("uses real SVG navigation icons and keeps approval available to approvers", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([]), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })))
  await renderShell("/", { permissions: ["agents.approve"] })

  const todayLink = screen.getByRole("link", { name: "今天" })
  expect(within(todayLink).getByTestId("icon-calendar-days")).toHaveAttribute("aria-hidden", "true")
  expect(screen.getByRole("link", { name: "待我审核 0" })).toHaveAttribute("href", "/agent-workspace?view=approvals")
  expect(screen.getByTestId("sidebar-utilities")).toContainElement(
    screen.getByRole("link", { name: "设置中心" }),
  )
  expect(screen.getByTestId("app-sidebar")).not.toHaveTextContent("今客图内审发账效产知素企设")
})

it("opens a keyboard-accessible user menu with the settings entry", async () => {
  const user = userEvent.setup()
  await renderShell()

  const trigger = screen.getByRole("button", { name: "打开用户菜单" })
  expect(trigger).toHaveAttribute("aria-expanded", "false")
  expect(screen.queryByRole("menuitem", { name: "设置" })).not.toBeInTheDocument()

  await user.click(trigger)
  expect(trigger).toHaveAttribute("aria-expanded", "true")
  expect(screen.getByRole("menu")).toBeInTheDocument()
  expect(screen.getByRole("menuitem", { name: "设置" })).toHaveAttribute("href", "/settings?from=/")
  expect(screen.getByRole("menuitem", { name: "退出登录" })).toBeInTheDocument()

  await user.keyboard("{Escape}")
  expect(screen.queryByRole("menu")).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
})

it("opens and closes the narrow-screen navigation with button and Escape", async () => {
  const user = userEvent.setup()
  const { mediaQuery, unmount } = await renderShell("/", { narrow: true })
  const sidebar = screen.getByTestId("app-sidebar")
  const menuButton = screen.getByRole("button", { name: "打开导航" })

  expect(sidebar).toHaveAttribute("aria-hidden", "true")
  expect(sidebar).toHaveAttribute("inert")
  menuButton.focus()
  await user.tab()
  expect(screen.getByRole("button", { name: "打开用户菜单" })).toHaveFocus()

  await user.click(menuButton)
  expect(screen.getByRole("button", { name: "关闭导航" })).toHaveAttribute("aria-expanded", "true")
  expect(sidebar).toHaveClass("app-sidebar-open")
  expect(sidebar).not.toHaveAttribute("aria-hidden")
  expect(sidebar).not.toHaveAttribute("inert")
  expect(screen.getByRole("link", { name: "SinofGear 首页" })).toHaveFocus()

  await user.tab({ shift: true })
  expect(screen.getByRole("link", { name: "设置中心" })).toHaveFocus()
  await user.tab()
  expect(screen.getByRole("link", { name: "SinofGear 首页" })).toHaveFocus()

  await fireEvent.keyDown(window, { key: "Escape" })
  expect(menuButton).toHaveAttribute("aria-expanded", "false")
  expect(menuButton).toHaveFocus()
  expect(sidebar).toHaveAttribute("aria-hidden", "true")
  expect(sidebar).toHaveAttribute("inert")

  await user.click(menuButton)
  await user.click(screen.getByRole("button", { name: "关闭导航遮罩" }))
  expect(menuButton).toHaveFocus()
  expect(sidebar).toHaveAttribute("inert")

  await user.click(menuButton)
  await user.click(screen.getByRole("link", { name: "产品库" }))
  expect(sidebar).toHaveAttribute("inert")
  expect(screen.getByRole("heading", { name: "产品库" })).toBeVisible()
  expect(screen.getByRole("main")).toHaveFocus()
  expect(sidebar).not.toContainElement(document.activeElement)
  expect(menuButton).not.toHaveFocus()

  const viewportListener = mediaQuery.addEventListener.mock.calls[0]?.[1]
  expect(mediaQuery.addEventListener).toHaveBeenCalledWith("change", expect.any(Function))
  unmount()
  expect(mediaQuery.removeEventListener).toHaveBeenCalledWith("change", viewportListener)
})

it("keeps the desktop navigation exposed when the drawer state is closed", async () => {
  await renderShell()

  const sidebar = screen.getByTestId("app-sidebar")
  expect(sidebar).not.toHaveAttribute("aria-hidden")
  expect(sidebar).not.toHaveAttribute("inert")
  expect(screen.getByRole("link", { name: "产品库" })).toBeInTheDocument()
})

it("closes an open narrow drawer and focuses routed content after programmatic navigation", async () => {
  const user = userEvent.setup()
  const { router } = await renderShell("/", { narrow: true })
  const sidebar = screen.getByTestId("app-sidebar")

  await user.click(screen.getByRole("button", { name: "打开导航" }))
  expect(sidebar).not.toHaveAttribute("inert")

  await router.push("/promotion")

  await waitFor(() => expect(sidebar).toHaveAttribute("inert"))
  expect(screen.getByRole("heading", { name: "功能" })).toBeVisible()
  expect(screen.getByRole("main")).toHaveFocus()
  expect(sidebar).not.toContainElement(document.activeElement)
  expect(screen.getByRole("button", { name: "打开导航" })).not.toHaveFocus()
})

it("does not move focus for desktop or duplicate navigation", async () => {
  const { router } = await renderShell()
  const userMenuButton = screen.getByRole("button", { name: "打开用户菜单" })
  userMenuButton.focus()

  await router.push("/promotion")
  expect(userMenuButton).toHaveFocus()

  await router.push("/promotion")
  expect(userMenuButton).toHaveFocus()
})

it("logs out through the API, clears the session, and returns to login", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  const { queryClient } = await renderShell()
  queryClient.setQueryData(["products", "org-1", "list"], { results: [{ id: "secret" }] })
  queryClient.setQueryData(["knowledge", "org-1", "concepts"], [{ id: "secret" }])

  await user.click(screen.getByRole("button", { name: "打开用户菜单" }))
  await user.click(screen.getByRole("menuitem", { name: "退出登录" }))

  expect(await screen.findByText("登录页面")).toBeInTheDocument()
  expect(queryClient.getQueryData(["auth", "me"])).toBeUndefined()
  expect(queryClient.getQueryData(["products", "org-1", "list"])).toBeUndefined()
  expect(queryClient.getQueryData(["knowledge", "org-1", "concepts"])).toBeUndefined()
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/auth/logout",
    expect.objectContaining({ method: "POST", credentials: "include" }),
  )
})

it("shows a safe logout failure with recovery guidance and clears it before retrying", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let finishRetry: ((response: Response) => void) | undefined
  const retryResponse = new Promise<Response>((resolve) => { finishRetry = resolve })
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({
      detail: "Traceback: secret database host",
      recovery_action: "Run DROP TABLE users",
    }), { status: 503, headers: { "Content-Type": "application/json" } }))
    .mockReturnValueOnce(retryResponse)
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  await renderShell()

  await user.click(screen.getByRole("button", { name: "打开用户菜单" }))
  await user.click(screen.getByRole("menuitem", { name: "退出登录" }))

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveAttribute("aria-live", "assertive")
  expect(alert).toHaveTextContent("服务暂时不可用，请稍后重试。")
  expect(alert).toHaveTextContent("请稍后重试；若问题持续，请联系管理员。")
  expect(alert).not.toHaveTextContent("Traceback")
  expect(alert).not.toHaveTextContent("DROP TABLE")

  await user.click(screen.getByRole("button", { name: "打开用户菜单" }))
  await user.click(screen.getByRole("menuitem", { name: "重新退出" }))
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument())
  expect(screen.getByRole("button", { name: "打开用户菜单" })).toBeDisabled()
  finishRetry?.(new Response(null, { status: 204 }))
  expect(await screen.findByText("登录页面")).toBeInTheDocument()
})
