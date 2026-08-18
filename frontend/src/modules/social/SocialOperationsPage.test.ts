import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, within } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import SocialOperationsPage from "./SocialOperationsPage.vue"

function workspace(connectors: unknown[] = [], channelPackages: unknown[] = []) {
  return {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], opportunity_reviews: [], crm_handoffs: [], reactivations: [],
    channel_packages: channelPackages, publish_batches: [], metric_receipts: [],
    field_provenance: [], connectors,
  }
}

async function renderPage(payload: ReturnType<typeof workspace>) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/promotion", component: SocialOperationsPage },
      { path: "/settings", component: { template: "<p>设置</p>" } },
      { path: "/reviews", component: { template: "<p>审核</p>" } },
      { path: "/publishing-calendar", component: { template: "<p>日历</p>" } },
      { path: "/platform-accounts", component: { template: "<p>账户</p>" } },
      { path: "/content-factory", component: { template: "<p>内容</p>" } },
    ],
  })
  await router.push("/promotion")
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(SocialOperationsPage, { global: { plugins: [[VueQueryPlugin, { queryClient: client }], router] } })
  await router.isReady()
}

afterEach(() => vi.unstubAllGlobals())

it("keeps all five channels visible in configuration-required mode", async () => {
  await renderPage(workspace())

  expect(await screen.findByRole("heading", { name: "社媒运营" })).toBeInTheDocument()
  expect(await screen.findByRole("heading", { name: "Facebook" })).toBeInTheDocument()
  for (const name of ["Facebook", "Instagram", "LinkedIn", "TikTok", "YouTube"]) {
    expect(screen.getByRole("heading", { name })).toBeInTheDocument()
  }
  expect(screen.getAllByText("需要管理员完成平台配置")).toHaveLength(5)
  expect(screen.getByRole("navigation", { name: "内容与发布工作区" })).toHaveTextContent("社媒运营")
  expect(screen.queryByText(/发布成功/)).not.toBeInTheDocument()
})

it("renders connected, reauthorization, review, private, and manual-package states honestly", async () => {
  await renderPage(workspace([
    { channel: "FACEBOOK", status: "CONNECTED", connection_label: "已连接", recovery_action: "", mode: "OFFICIAL" },
    { channel: "INSTAGRAM", status: "REAUTHORIZATION_REQUIRED", connection_label: "需要重新授权", recovery_action: "请重新授权", mode: "OFFICIAL" },
    { channel: "LINKEDIN", status: "WAITING_PLATFORM_REVIEW", connection_label: "等待平台审核", recovery_action: "等待 LinkedIn 审核", mode: "" },
    { channel: "TIKTOK", status: "PRIVATE_ONLY", connection_label: "仅私密上传", recovery_action: "当前应用仅支持私密内容", mode: "OFFICIAL" },
  ], [{
    id: "youtube-package", account_id: null, channel: "YOUTUBE", payload: { title: "YouTube demo" },
    status: "APPROVED", is_demo: false, data_label: "Reviewed", delivery: "MANUAL_ONLY",
    created_at: "2026-08-18T08:00:00Z", updated_at: "2026-08-18T08:00:00Z",
  }]))

  const facebook = await screen.findByRole("article", { name: "Facebook 渠道" })
  expect(within(facebook).getByText("官方账号已连接")).toBeInTheDocument()
  expect(within(screen.getByRole("article", { name: "Instagram 渠道" })).getByText("需要重新授权")).toBeInTheDocument()
  expect(within(screen.getByRole("article", { name: "LinkedIn 渠道" })).getByText("等待平台审核")).toBeInTheDocument()
  expect(within(screen.getByRole("article", { name: "TikTok 渠道" })).getByText("当前仅支持私密发布")).toBeInTheDocument()
  expect(within(screen.getByRole("article", { name: "YouTube 渠道" })).getByText("可下载手工发布包")).toBeInTheDocument()
})
