import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import AutomaticDiscoveryCard from "./AutomaticDiscoveryCard.vue"
import type { DiscoverySummary } from "./api"


const discovery: DiscoverySummary = {
  enabled: true,
  source_label: "欧盟与英国官方采购数据",
  schedule_label: "每天自动查找",
  product_scope_label: "齿轮、传动与驱动部件",
  next_run_at: null,
  last_run: null,
  available_sources: [
    { code: "TED", label: "TED 欧盟采购公告", status: "ACTIVE" },
    { code: "UK_CONTRACTS_FINDER", label: "英国 Contracts Finder", status: "ACTIVE" },
    { code: "GOOGLE_PLACES", label: "Google Maps 官方企业发现", status: "KEY_REQUIRED" },
  ],
}

function renderCard(value = discovery) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(AutomaticDiscoveryCard, {
    props: { discovery: value },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

it("runs official customer discovery and explains the result", async () => {
  document.cookie = "csrftoken=discovery-card-token"
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(String(input)).toBe("/api/v1/growth/discovery/run")
    expect(init?.method).toBe("POST")
    return new Response(JSON.stringify({
      status: "SUCCEEDED",
      finished_at: "2026-08-15T04:00:00Z",
      found_count: 3,
      new_company_count: 2,
      new_signal_count: 2,
      duplicate_count: 1,
      skipped_count: 0,
      message: "发现 2 条新采购信号，等待你审核。",
    }), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  renderCard()

  await userEvent.click(screen.getByRole("button", { name: "立即查找" }))

  expect(await screen.findByRole("status")).toHaveTextContent(
    "发现 2 条新采购信号，等待你审核。",
  )
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it("shows Google Maps as an official key-required source and never implies intent", () => {
  renderCard()

  expect(screen.getByText("Google Maps 官方企业发现")).toBeInTheDocument()
  expect(screen.getByText("接入密钥后可用")).toBeInTheDocument()
  expect(screen.getByText(/地图只用于发现目标公司，不代表采购意向/)).toBeInTheDocument()
  expect(screen.getByText(/不会自动联系客户/)).toBeInTheDocument()
})

it("can pause the daily schedule", async () => {
  document.cookie = "csrftoken=discovery-toggle-token"
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(String(input)).toBe("/api/v1/growth/discovery/profile")
    expect(init?.method).toBe("PATCH")
    expect(JSON.parse(String(init?.body))).toEqual({ enabled: false })
    return new Response(JSON.stringify({
      ...discovery,
      enabled: false,
      schedule_label: "已暂停自动查找",
    }), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  renderCard()

  await userEvent.click(screen.getByRole("checkbox", { name: "每天自动查找" }))

  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("已暂停自动查找"))
})
