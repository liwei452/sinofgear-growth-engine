import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import SettingsCenterPage from "./SettingsCenterPage.vue"

afterEach(() => vi.unstubAllGlobals())

async function renderSettings(role: string, permissions: string[], accounts: unknown[] = [], providerStatus = {
  mode: "FAKE_OFFLINE", provider_label: "Fake / 离线演示", model: "fake-v1",
  configured: false, real_requests_enabled: false,
}) {
  vi.stubGlobal("fetch", vi.fn((path: string) => Promise.resolve(new Response(JSON.stringify(
    path === "/api/v1/ai/provider-status" ? providerStatus : { results: accounts },
  ), {
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
  expect(screen.getAllByTestId("settings-primary-group")).toHaveLength(4)
  expect(screen.queryByRole("button", { name: "展开高级设置" })).not.toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "查看资料与事实" })).not.toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "渠道账户" })).not.toBeInTheDocument()
  expect(screen.getByRole("link", { name: "内容审核与发布" })).toHaveAttribute("href", "/content-factory")
  expect(await screen.findByText("尚未添加渠道账户；手工发布包仍可用")).toBeInTheDocument()
  expect(await screen.findByText("当前不能生成待确认事实")).toBeInTheDocument()

  const crm = screen.getByRole("region", { name: "通知与 CRM" })
  expect(within(crm).getByText("尚未配置")).toBeInTheDocument()
  expect(within(crm).queryByRole("button")).not.toBeInTheDocument()
  expect(within(crm).queryByRole("link")).not.toBeInTheDocument()
  expect(screen.queryByRole("heading", { name: "高级管理" })).not.toBeInTheDocument()
  expect(screen.queryByText(/secret|api[_ -]?key/i)).not.toBeInTheDocument()
})

it("keeps advanced settings collapsed until an administrator requests them", async () => {
  await renderSettings("ADMINISTRATOR", ["knowledge.read", "missions.read"])

  const user = userEvent.setup()
  const toggle = screen.getByRole("button", { name: "展开高级设置" })
  expect(toggle).toHaveAttribute("aria-expanded", "false")
  expect(screen.queryByRole("region", { name: "高级管理" })).not.toBeInTheDocument()
  await user.click(toggle)
  expect(toggle).toHaveAttribute("aria-expanded", "true")
  expect(screen.getByRole("region", { name: "高级管理" })).toBeInTheDocument()
})

it("shows the business consequence of a configured product provider without exposing technical details", async () => {
  await renderSettings("OPERATOR", [], [], {
    mode: "CONFIGURED_AI", provider_label: "DeepSeek 官方 API", model: "deepseek-chat",
    configured: true, real_requests_enabled: true,
  })

  expect(await screen.findByText("可生成待确认事实")).toBeInTheDocument()
  expect(document.body.textContent).not.toMatch(/deepseek|api[_ -]?key|secret|bearer/i)
})

it("summarizes saved channel accounts without claiming a real connection", async () => {
  await renderSettings("OPERATOR", ["publishing.read"], [
    { id: "manual", platform_id: "linkedin", display_name: "LinkedIn", publish_mode: "MANUAL", status: "ACTIVE", effective_capabilities: ["PUBLISH"], credential_configured: false },
    { id: "api", platform_id: "tiktok", display_name: "TikTok", publish_mode: "API_AUTO", status: "ACTIVE", effective_capabilities: ["PUBLISH"], credential_configured: true },
    { id: "old", platform_id: "facebook", display_name: "Facebook", publish_mode: "API_AUTO", status: "INACTIVE", effective_capabilities: ["PUBLISH"], credential_configured: true },
  ])

  const channels = screen.getByRole("region", { name: "推广与发布连接" })
  expect(await within(channels).findByText("2 个有效渠道账户，其中 1 个已配置接口凭据")).toBeInTheDocument()
  expect(within(channels).queryByText(/发布成功|已连接/)).not.toBeInTheDocument()
})

it("shows administrator-only advanced destinations without inventing provider status", async () => {
  await renderSettings("ADMINISTRATOR", [
    "knowledge.read", "tracking.read", "missions.read", "products.read", "assets.read", "publishing.read",
  ])

  await userEvent.setup().click(screen.getByRole("button", { name: "展开高级设置" }))
  const advanced = screen.getByRole("region", { name: "高级管理" })
  expect(within(advanced).getByRole("link", { name: "AI 模型" })).toHaveAttribute("href", "/settings/ai-model")
  expect(within(advanced).getByRole("link", { name: "知识库" })).toHaveAttribute("href", "/knowledge")
  expect(within(advanced).getByRole("link", { name: "数据归因" })).toHaveAttribute("href", "/attribution")
  expect(within(advanced).getByText("真实模型与预算仅由管理员管理")).toBeInTheDocument()
  expect(within(advanced).queryByRole("button", { name: /配置 Provider/ })).not.toBeInTheDocument()
})
