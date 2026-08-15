import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, within } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import SettingsCenterPage from "./SettingsCenterPage.vue"

afterEach(() => vi.unstubAllGlobals())

async function renderSettings(role: string, permissions: string[], accounts: unknown[] = []) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ results: accounts }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }))))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "owner" },
    organization: { id: "org-1", name: "真实工厂", slug: "factory" },
    membership: { id: "member-1", role, status: "ACTIVE", permissions },
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/settings", component: SettingsCenterPage },
      { path: "/:pathMatch(.*)*", component: { template: "<p>目标页面</p>" } },
    ],
  })
  await router.push("/settings")
  render(SettingsCenterPage, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })
  await router.isReady()
}

it("shows only real permission-backed destinations and truthful unconfigured states", async () => {
  await renderSettings("OPERATOR", ["products.read", "assets.read", "publishing.read"])

  expect(screen.getByRole("heading", { name: "设置中心" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "公司资料" })).toHaveAttribute("href", "/company")
  expect(screen.getByRole("link", { name: "产品库" })).toHaveAttribute("href", "/products")
  expect(screen.getByRole("link", { name: "素材与资料理解" })).toHaveAttribute("href", "/assets")
  expect(screen.getByRole("link", { name: "渠道账户" })).toHaveAttribute("href", "/platform-accounts")
  expect(screen.getByRole("link", { name: "发布日历" })).toHaveAttribute("href", "/publishing-calendar")
  expect(await screen.findByText("尚未添加渠道账户；手工发布包仍可用")).toBeInTheDocument()
  expect(screen.getByText("真实 AI Provider 尚未配置")).toBeInTheDocument()

  const crm = screen.getByRole("region", { name: "CRM与通知" })
  expect(within(crm).getByText("尚未配置")).toBeInTheDocument()
  expect(within(crm).queryByRole("button")).not.toBeInTheDocument()
  expect(within(crm).queryByRole("link")).not.toBeInTheDocument()
  expect(screen.queryByRole("heading", { name: "高级管理" })).not.toBeInTheDocument()
  expect(screen.queryByText(/secret|api[_ -]?key/i)).not.toBeInTheDocument()
})

it("summarizes saved channel accounts without claiming a real connection", async () => {
  await renderSettings("OPERATOR", ["publishing.read"], [
    { id: "manual", platform_id: "linkedin", display_name: "LinkedIn", publish_mode: "MANUAL", status: "ACTIVE", effective_capabilities: ["PUBLISH"], credential_configured: false },
    { id: "api", platform_id: "tiktok", display_name: "TikTok", publish_mode: "API_AUTO", status: "ACTIVE", effective_capabilities: ["PUBLISH"], credential_configured: true },
    { id: "old", platform_id: "facebook", display_name: "Facebook", publish_mode: "API_AUTO", status: "INACTIVE", effective_capabilities: ["PUBLISH"], credential_configured: true },
  ])

  const channels = screen.getByRole("region", { name: "渠道与发布" })
  expect(await within(channels).findByText("2 个有效渠道账户，其中 1 个已配置接口凭据")).toBeInTheDocument()
  expect(within(channels).queryByText(/发布成功|已连接/)).not.toBeInTheDocument()
})

it("shows administrator-only advanced destinations without inventing provider status", async () => {
  await renderSettings("ADMINISTRATOR", [
    "knowledge.read", "tracking.read", "products.read", "assets.read", "publishing.read",
  ])

  const advanced = screen.getByRole("region", { name: "高级管理" })
  expect(within(advanced).getByRole("link", { name: "知识库" })).toHaveAttribute("href", "/knowledge")
  expect(within(advanced).getByRole("link", { name: "高级数据" })).toHaveAttribute("href", "/admin/analytics")
  expect(within(advanced).getByText("Provider 管理尚未配置")).toBeInTheDocument()
  expect(within(advanced).queryByRole("button", { name: /配置 Provider/ })).not.toBeInTheDocument()
})
