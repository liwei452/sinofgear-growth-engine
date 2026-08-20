import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { defineComponent, h } from "vue"
import { createMemoryHistory, createRouter, RouterView } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../modules/auth/auth"
import AppShell from "./AppShell.vue"

const Page = defineComponent({ template: "<h1>Page content</h1>" })
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
  permissions = ["missions.read", "leads.manage", "publishing.read"],
} = {}) {
  useViewport()
  const history = createMemoryHistory()
  const router = createRouter({
    history,
    routes: [{
      path: "/",
      component: AppShell,
      children: [
        { path: "", component: Page, meta: { title: "Today" } },
        { path: "promotion", component: Page },
        { path: "opportunities", component: Page },
        { path: "content-factory", component: Page },
        { path: "analytics", component: Page },
        { path: "company", component: Page },
        { path: "help", component: Page },
        { path: "settings", component: Page },
      ],
    }],
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "operator" },
    organization: { id: "org-1", name: "Demo organization", slug: "demo" },
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

it("shows the five business destinations and utility links", async () => {
  await renderShell()

  expect(screen.getAllByRole("link").filter((link) =>
    ["\u4eca\u65e5", "\u5f00\u59cb\u63a8\u5e7f", "\u5ba2\u6237\u673a\u4f1a", "\u5185\u5bb9\u4e0e\u53d1\u5e03", "\u6548\u679c"].includes(link.textContent ?? ""),
  )).toHaveLength(5)
  expect(screen.getByRole("link", { name: "\u6211\u7684\u516c\u53f8" })).toHaveAttribute("href", "/company")
  expect(screen.getByRole("link", { name: "\u5e2e\u52a9" })).toHaveAttribute("href", "/help")
  expect(screen.getByRole("link", { name: "\u8bbe\u7f6e" })).toHaveAttribute("href", "/settings")
  expect(screen.queryByRole("link", { name: "\u589e\u957f\u4efb\u52a1" })).not.toBeInTheDocument()
})

it("opens the user menu and exposes logout", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
  const user = userEvent.setup()
  await renderShell()

  await user.click(screen.getByRole("button", { name: "\u6253\u5f00\u7528\u6237\u83dc\u5355" }))
  expect(screen.getByRole("menu")).toBeInTheDocument()
  expect(screen.getByRole("menuitem", { name: "\u9000\u51fa\u767b\u5f55" })).toBeInTheDocument()
})
