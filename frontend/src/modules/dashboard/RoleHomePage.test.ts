import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import RoleHomePage from "./RoleHomePage.vue"

afterEach(() => vi.unstubAllGlobals())

it("renders executive attribution for read-only users", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify([]), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }))))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "reader" },
    organization: { id: "org-1", name: "Org", slug: "org" },
    membership: { id: "m1", role: "READ_ONLY", status: "ACTIVE", permissions: ["missions.read"] },
  })
  render(RoleHomePage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByRole("heading", { name: "数据归因" })).toBeVisible()
})
