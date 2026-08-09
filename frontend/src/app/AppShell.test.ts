import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { fireEvent, render, screen } from "@testing-library/vue"
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
  membership: { id: "member-1", role: "OPERATOR", status: "ACTIVE" },
}

async function renderShell(initialPath = "/") {
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
        ],
      },
    ],
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser)
  const result = render(Root, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()
  return { ...result, router, queryClient }
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("shows grouped Chinese navigation, organization, user, and active item", async () => {
  await renderShell("/products")

  for (const label of [
    "首页", "产品库", "知识库", "素材库", "AI 内容工厂", "审核中心",
    "发布日历", "平台账号", "数据看板",
  ]) {
    expect(screen.getByRole("link", { name: label })).toBeInTheDocument()
  }
  expect(screen.getByText("示例组织")).toBeInTheDocument()
  expect(screen.getByText("operator")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "产品库" })).toHaveAttribute("aria-current", "page")
  expect(screen.getByRole("heading", { name: "产品库" })).toBeInTheDocument()
  expect(screen.getByText("这个入口已经准备好，具体业务能力将在后续阶段接入。")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "返回首页" })).toHaveAttribute("href", "/")
})

it("opens and closes the narrow-screen navigation with button and Escape", async () => {
  const user = userEvent.setup()
  await renderShell()
  const sidebar = screen.getByTestId("app-sidebar")

  expect(screen.getByRole("button", { name: "打开导航" })).toHaveAttribute("aria-expanded", "false")
  await user.click(screen.getByRole("button", { name: "打开导航" }))
  expect(screen.getByRole("button", { name: "关闭导航" })).toHaveAttribute("aria-expanded", "true")
  expect(sidebar).toHaveClass("app-sidebar-open")
  await fireEvent.keyDown(window, { key: "Escape" })
  expect(screen.getByRole("button", { name: "打开导航" })).toHaveAttribute("aria-expanded", "false")
})

it("logs out through the API, clears the session, and returns to login", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  const { queryClient } = await renderShell()

  await user.click(screen.getByRole("button", { name: "退出登录" }))

  expect(await screen.findByText("登录页面")).toBeInTheDocument()
  expect(queryClient.getQueryData(["auth", "me"])).toBeUndefined()
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/auth/logout",
    expect.objectContaining({ method: "POST", credentials: "include" }),
  )
})
