import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import DiscoveryCandidateQueue from "./DiscoveryCandidateQueue.vue"


it("shows governed candidate evidence and sends it only to company enrichment after review", async () => {
  document.cookie = "csrftoken=candidate-review-token"
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(String(input)).toContain("/api/v1/growth/discovery/candidates/candidate-1/review")
    expect(init?.method).toBe("POST")
    expect(JSON.parse(String(init?.body))).toEqual({
      decision: "ACCEPT",
      note: "人工确认公司资料可继续补全",
    })
    return new Response(JSON.stringify({
      id: "candidate-1",
      status: "ACCEPTED",
      status_label: "待补全公司资料",
      message: "已加入公司资料补全，不会自动联系客户。",
    }), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()

  render(DiscoveryCandidateQueue, {
    props: {
      candidates: [{
        id: "candidate-1",
        company_name: "Jakarta Drives",
        country: "Indonesia",
        website: "https://jakarta.example.invalid/",
        industry: "Industrial equipment",
        status: "PENDING_REVIEW",
        status_label: "待核实",
        source_owner: "Licensed supplier",
        license_contract: "Prospecting licence 2026",
        import_format: "CSV",
        is_demo: false,
        created_at: "2026-08-15T06:00:00Z",
      }],
    },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })

  expect(screen.getByText("Jakarta Drives")).toBeInTheDocument()
  expect(screen.getByText("Licensed supplier")).toBeInTheDocument()
  expect(screen.getByText("Prospecting licence 2026")).toBeInTheDocument()
  expect(screen.getByText("尚未发现采购意向，不会自动联系")).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "加入资料补全" }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(await screen.findByRole("status")).toHaveTextContent("不会自动联系客户")
})
