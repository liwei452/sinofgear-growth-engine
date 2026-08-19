import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import DashboardPage from "./DashboardPage.vue"

afterEach(() => vi.unstubAllGlobals())

it("leads with the unified today inbox and a mission creation path", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    const body = path === "/api/v1/growth/missions" ? [] : []
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
  }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: DashboardPage },
      { path: "/missions", component: { template: "<p>missions</p>" } },
      { path: "/settings", component: { template: "<p>settings</p>" } },
      { path: "/opportunities", component: { template: "<p>opportunities</p>" } },
    ],
  })
  await router.push("/")
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(DashboardPage, {
    global: { plugins: [router, [VueQueryPlugin, { queryClient }]] },
  })
  await router.isReady()

  expect(await screen.findByRole("heading", { level: 1, name: "今日待办" })).toBeVisible()
  expect(screen.getByRole("link", { name: "创建增长任务" })).toHaveAttribute("href", "/missions")
  expect(await screen.findByText("今天没有需要人工处理的事项")).toBeVisible()
})
