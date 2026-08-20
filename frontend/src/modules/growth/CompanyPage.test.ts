import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import CompanyPage from "./CompanyPage.vue"

afterEach(() => vi.unstubAllGlobals())

it("loads company provenance and persists human verification", async () => {
  document.cookie = "csrftoken=company-page-test-token"
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }],
  })
  const factId = "10000000-0000-4000-8000-000000001403"
  const facts = [{
    id: factId, field_name: "accuracy_grade", field_value: "DIN 6",
    source_label: "Product library", verification_status: "NEEDS_EVIDENCE",
    source_cost_micros: 20000, created_at: "2026-08-14T08:00:00Z", updated_at: "2026-08-14T08:00:00Z",
  }]
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === "/api/v1/growth/company-facts") {
      return new Response(JSON.stringify(facts), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/verify")) {
      return new Response(JSON.stringify({ id: factId, verification_status: "VERIFIED" }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(CompanyPage, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })

  expect(await screen.findByText("Product library")).toBeInTheDocument()
  expect(screen.getByRole("region", { name: "公司事实" })).toBeInTheDocument()
  expect(screen.getByRole("region", { name: "内容准备" })).toBeInTheDocument()
  expect(screen.getByRole("region", { name: "渠道准备" })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "确认 DIN 6" }))
  await waitFor(() => expect(screen.getByText("已确认", { selector: "span" })).toBeInTheDocument())
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/verify"))).toBe(true)
})

it("does not present an initial company-fact read failure as an empty fact library", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("unavailable", { status: 503 })))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }] })

  render(CompanyPage, { global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }], router] } })

  expect(await screen.findByRole("alert")).toHaveTextContent("公司事实暂时无法读取")
  expect(screen.queryByText("还没有已保存的公司事实")).not.toBeInTheDocument()
})

it("suppresses retained company facts when a refresh fails", async () => {
  let requests = 0
  vi.stubGlobal("fetch", vi.fn(async () => {
    requests += 1
    if (requests === 1) return new Response(JSON.stringify([{
      id: "10000000-0000-4000-8000-000000001404", field_name: "accuracy_grade", field_value: "DIN 6",
      source_label: "Product library", verification_status: "VERIFIED", source_cost_micros: 0,
      created_at: "2026-08-14T08:00:00Z", updated_at: "2026-08-14T08:00:00Z",
    }]), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response("unavailable", { status: 503 })
  }))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }] })

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(CompanyPage, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })
  expect(await screen.findByText("DIN 6")).toBeInTheDocument()
  await queryClient.invalidateQueries({ queryKey: ["growth", "company-facts"] })

  expect(await screen.findByRole("alert")).toHaveTextContent("公司事实暂时无法读取")
  expect(screen.queryByText("DIN 6")).not.toBeInTheDocument()
})
