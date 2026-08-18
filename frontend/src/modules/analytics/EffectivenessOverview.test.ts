import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import EffectivenessOverview from "./EffectivenessOverview.vue"

const emptyWorkspace = {
  target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
  outreach_drafts: [], opportunity_reviews: [], crm_handoffs: [], reactivations: [],
  channel_packages: [], publish_batches: [], metric_receipts: [], field_provenance: [], connectors: [],
}

async function renderOverview() {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(emptyWorkspace), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/analytics", component: EffectivenessOverview },
      { path: "/content-factory", component: { template: "<p>内容</p>" } },
      { path: "/promotion", component: { template: "<p>社媒</p>" } },
    ],
  })
  await router.push("/analytics")
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(EffectivenessOverview, { global: { plugins: [[VueQueryPlugin, { queryClient: client }], router] } })
  await router.isReady()
}

afterEach(() => vi.unstubAllGlobals())

it("keeps the executive page concise and opens manual entry only on demand", async () => {
  const user = userEvent.setup()
  await renderOverview()

  expect(await screen.findByRole("heading", { name: "经营效果" })).toBeInTheDocument()
  expect(await screen.findByText("有效客户")).toBeInTheDocument()
  expect(screen.getByText("已批准内容")).toBeInTheDocument()
  expect(screen.getByText("已发布内容")).toBeInTheDocument()
  expect(screen.getByText("有效询盘")).toBeInTheDocument()
  expect(screen.queryByRole("form", { name: "手工回填渠道结果" })).not.toBeInTheDocument()
  expect(screen.queryByRole("heading", { name: "账户获客漏斗" })).not.toBeInTheDocument()
  expect(screen.getAllByText("无数据")).toHaveLength(4)

  const openEntry = screen.getByRole("button", { name: "录入数据" })
  await user.click(openEntry)
  expect(screen.getByRole("form", { name: "手工回填渠道结果" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "关闭录入数据" })).toHaveFocus()
  await user.keyboard("{Escape}")
  expect(screen.queryByRole("form", { name: "手工回填渠道结果" })).not.toBeInTheDocument()
  expect(openEntry).toHaveFocus()
})
