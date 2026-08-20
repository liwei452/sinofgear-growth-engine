import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import DashboardPage from "./DashboardPage.vue"

afterEach(() => vi.unstubAllGlobals())

it("shows the confidence dashboard regions instead of the old today hero", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify([]), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }))))
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

  expect(await screen.findByRole("region", { name: "今日最重要机会" })).toBeInTheDocument()
  expect(screen.getByRole("region", { name: "当前阻塞" })).toBeInTheDocument()
  expect(screen.getByRole("region", { name: "最新证据" })).toBeInTheDocument()
  expect(screen.getByRole("region", { name: "今日待办" })).toBeInTheDocument()
  expect(screen.queryByText("TODAY'S WORKSPACE")).not.toBeInTheDocument()
})
