import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { defineComponent, h } from "vue"
import { createMemoryHistory, createRouter, RouterView } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../modules/auth/auth"
import AppShell from "./AppShell.vue"

const Page = defineComponent({ template: "<h1>首页内容</h1>" })
const Root = defineComponent({ setup: () => () => h(RouterView) })

function useViewport() {
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
    matches: false,
    media: "(max-width: 860px)",
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

async function renderShell({
  role = "OPERATOR",
  permissions = ["missions.read", "leads.read", "content.read"],
} = {}) {
  useViewport()
  const history = createMemoryHistory()
  const router = createRouter({
    history,
    routes: [
      {
        path: "/",
        component: AppShell,
        children: [{ path: "", component: Page, meta: { title: "今日待办" } }],
      },
    ],
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "operator" },
    organization: { id: "org-1", name: "示例组织", slug: "demo" },
    membership: { id: "m1", role, status: "ACTIVE", permissions },
  })
  render(Root, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })
  await router.isReady()
  return { router, queryClient }
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("shows the five ordinary destinations and hides legacy module links", async () => {
  await renderShell()

  expect(screen.getByRole("link", { name: "今日待办" })).toHaveAttribute("href", "/")
  expect(screen.getByRole("link", { name: "增长任务" })).toHaveAttribute("href", "/missions")
  expect(screen.getByRole("link", { name: "客户与商机" })).toHaveAttribute("href", "/opportunities")
  expect(screen.getByRole("link", { name: "内容与素材" })).toHaveAttribute("href", "/content")
  expect(screen.getByRole("link", { name: "数据归因" })).toHaveAttribute("href", "/attribution")
  expect(screen.queryByRole("link", { name: "Agent 工作台" })).not.toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "审核中心" })).not.toBeInTheDocument()
})

it("shows system configuration only to administrators with credential access", async () => {
  await renderShell({
    role: "ADMINISTRATOR",
    permissions: ["missions.read", "leads.read", "content.read", "credentials.manage"],
  })

  expect(screen.getByRole("link", { name: "系统配置" })).toHaveAttribute("href", "/settings")
})

it("opens the user menu and exposes logout", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
  const user = userEvent.setup()
  await renderShell()

  await user.click(screen.getByRole("button", { name: "打开用户菜单" }))
  expect(screen.getByRole("menu")).toBeInTheDocument()
  expect(screen.getByRole("menuitem", { name: "退出登录" })).toBeInTheDocument()
})
