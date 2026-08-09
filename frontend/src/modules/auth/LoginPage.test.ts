import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { defineComponent, h } from "vue"
import { createMemoryHistory, createRouter, RouterView } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import LoginPage from "./LoginPage.vue"

const Destination = defineComponent({ template: "<p>目标页面</p>" })
const Root = defineComponent({ setup: () => () => h(RouterView) })
const authenticatedUser = {
  user: { id: 1, username: "operator" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "OPERATOR", status: "ACTIVE", permissions: [] },
}

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
  const pending = new Promise<Response>((resolve) => { finish = resolve })
  vi.stubGlobal("fetch", vi.fn((path: string) => path === "/api/v1/auth/login"
    ? pending
    : Promise.resolve(new Response(JSON.stringify(authenticatedUser), {
      status: 200, headers: { "Content-Type": "application/json" },
    }))))
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
  vi.stubGlobal("fetch", vi.fn(async (path: string) => path === "/api/v1/auth/login"
    ? new Response(null, { status: 204 })
    : new Response(JSON.stringify(authenticatedUser), {
      status: 200, headers: { "Content-Type": "application/json" },
    })))
  const { router } = await renderLogin(initialPath)
  const user = await completeForm()

  await user.click(screen.getByRole("button", { name: "登录" }))

  expect(await screen.findByText("目标页面")).toBeInTheDocument()
  expect(router.currentRoute.value.fullPath).toBe(expected)
})

it("removes every previous-session query before login and seeds a freshly fetched identity", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const nextUser = {
    user: { id: 2, username: "new-user" },
    organization: { id: "org-b", name: "组织 B", slug: "org-b" },
    membership: { id: "member-b", role: "CUSTOM", status: "ACTIVE", permissions: ["products.read"] },
  }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(nextUser), {
      status: 200, headers: { "Content-Type": "application/json" },
    }))
  vi.stubGlobal("fetch", fetchMock)
  const { queryClient } = await renderLogin()
  queryClient.setQueryData(["auth", "me"], { organization: { id: "org-a" } })
  queryClient.setQueryData(["products", "org-a", "list"], { results: [{ id: "secret-a" }] })
  queryClient.setQueryData(["knowledge", "org-a", "concepts"], [{ id: "secret-a" }])
  const user = await completeForm()

  await user.click(screen.getByRole("button", { name: "登录" }))

  expect(await screen.findByText("目标页面")).toBeInTheDocument()
  expect(queryClient.getQueryData(["products", "org-a", "list"])).toBeUndefined()
  expect(queryClient.getQueryData(["knowledge", "org-a", "concepts"])).toBeUndefined()
  expect(queryClient.getQueryData(["auth", "me"])).toEqual(nextUser)
  expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
    "/api/v1/auth/login", "/api/v1/auth/me",
  ])
})

it("clears previous-session queries before a failed direct re-login", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })))
  const { queryClient } = await renderLogin()
  queryClient.setQueryData(["products", "org-a", "list"], { results: [{ id: "secret-a" }] })
  const user = await completeForm()

  await user.click(screen.getByRole("button", { name: "登录" }))

  expect(await screen.findByRole("alert")).toBeInTheDocument()
  expect(queryClient.getQueryData(["products", "org-a", "list"])).toBeUndefined()
})
