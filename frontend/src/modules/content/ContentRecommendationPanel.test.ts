import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import ContentRecommendationPanel from "./ContentRecommendationPanel.vue"

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("asks AI for three directions and emits only the selected ready brief", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const recommendation = {
    id: "rec-1", job_id: "job-rec", status: "READY", provider_mode: "FAKE_OFFLINE",
    selected_option_id: null, selected_brief_id: null, created_at: "", updated_at: "",
    options: [1, 2, 3].map((position) => ({
      id: `opt-${position}`, position, product_id: "product-1",
      market_code: ["ID", "ZA", "VN"][position - 1], language: ["id", "en", "vi"][position - 1],
      customer_profile: `Buyer ${position}`, channel_codes: ["LINKEDIN"],
      theme: `Direction ${position}`, rationale: `Reason ${position}`,
      evidence: [{ fact_id: `fact-${position}` }], missing_information: [], selected_at: null,
    })),
  }
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/content-recommendations" && options?.method !== "POST") {
      return new Response(JSON.stringify({ results: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/content-recommendations" && options?.method === "POST") {
      return new Response(JSON.stringify({ recommendation_id: "rec-1", job_id: "job-rec", status: "QUEUED", generation_mode: "FAKE_OFFLINE", generation_label: "Fake / 离线演示推荐" }), { status: 202, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/content-recommendations/rec-1") {
      return new Response(JSON.stringify(recommendation), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/options/opt-2/select") && options?.method === "POST") {
      return new Response(JSON.stringify({ recommendation_id: "rec-1", option_id: "opt-2", brief_id: "brief-2", brief_status: "READY" }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  const view = render(ContentRecommendationPanel, { props: { canManage: true } })

  await user.click(await screen.findByRole("button", { name: "让 AI 推荐推广方向" }))
  expect(await screen.findAllByRole("button", { name: "选择这个方向" })).toHaveLength(3)
  expect(screen.getByText("Fake / 离线演示推荐")).toBeVisible()
  await user.click(screen.getAllByRole("button", { name: "选择这个方向" })[1])
  await user.click(screen.getByRole("button", { name: "生成这组内容" }))

  expect(view.emitted("brief-ready")).toEqual([["brief-2"]])
  expect(fetchMock.mock.calls.filter(([path]) => String(path).includes("/select"))).toHaveLength(1)
})
