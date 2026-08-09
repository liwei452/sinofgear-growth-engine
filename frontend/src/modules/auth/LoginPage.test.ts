import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { defineComponent, h } from "vue"
import { createMemoryHistory, createRouter, RouterView } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import LoginPage from "./LoginPage.vue"

const Destination = defineComponent({ template: "<p>目标页面</p>" })
const Root = defineComponent({ setup: () => () => h(RouterView) })

async function renderLogin(initialPath = "/login") {
  const history = createMemoryHistory()
  history.push(initialPath)
  const router = createRouter({
    history,
    routes: [
      { path: "/login", component: LoginPage },
      { path: "/", component: Destination },
      { path: "/products", component: Destination },
    ],
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const result = render(Root, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  await router.isReady()
  return { ...result, router, queryClient }
}

async function completeForm(user = userEvent.setup()) {
  await user.type(screen.getByLabelText("用户名"), "operator")
  await user.type(screen.getByLabelText("密码"), "safe-password")
  return user
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("shows a concise product promise and accessible login fields", async () => {
  await renderLogin()

  expect(screen.getByRole("heading", { name: "SinofGear 增长引擎" })).toBeInTheDocument()
  expect(screen.getByText("把内容、发布和增长数据放在一个清楚的工作台里。")).toBeInTheDocument()
  expect(screen.getByLabelText("用户名")).toHaveAttribute("autocomplete", "username")
  expect(screen.getByLabelText("密码")).toHaveAttribute("autocomplete", "current-password")
})

it("disables submission and announces progress while login is pending", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let finish!: (response: Response) => void
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((resolve) => {
    finish = resolve
  })))
  await renderLogin()
  const user = await completeForm()

  await user.click(screen.getByRole("button", { name: "登录" }))

  expect(screen.getByRole("button", { name: "正在登录…" })).toBeDisabled()
  finish(new Response(null, { status: 204 }))
  expect(await screen.findByText("目标页面")).toBeInTheDocument()
})

it("uses one generic failure message without disclosing account existence", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ detail: "Unknown username operator", stack: "secret" }),
    { status: 400, headers: { "Content-Type": "application/json" } },
  )))
  await renderLogin()
  const user = await completeForm()

  await user.click(screen.getByRole("button", { name: "登录" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("用户名或密码不正确，请重试。")
  expect(screen.queryByText(/Unknown username|secret/)).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "登录" })).toBeEnabled()
})

it.each([
  ["/login?redirect=/products", "/products"],
  ["/login?redirect=https://evil.example/steal", "/"],
  ["/login?redirect=//evil.example/steal", "/"],
])("returns only to a safe local destination from %s", async (initialPath, expected) => {
  document.cookie = "csrftoken=csrf-value; path=/"
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
  const { router } = await renderLogin(initialPath)
  const user = await completeForm()

  await user.click(screen.getByRole("button", { name: "登录" }))

  expect(await screen.findByText("目标页面")).toBeInTheDocument()
  expect(router.currentRoute.value.fullPath).toBe(expected)
})
