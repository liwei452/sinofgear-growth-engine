import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import AIModelSettingsPage from "./AIModelSettingsPage.vue"

const configured = {
  provider: "deepseek",
  model: "deepseek-chat",
  configured: true,
  enabled: true,
  daily_budget_micros: 500_000,
  daily_spent_micros: 1_200,
  daily_reserved_micros: 0,
  price_table_version: "deepseek-usd-2026-08-18",
  last_tested_at: null,
  last_success_at: null,
  last_error_code: "",
}

async function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  client.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "owner" },
    organization: { id: "org-1", name: "齿轮工厂", slug: "factory" },
    membership: { id: "member-1", role: "ADMINISTRATOR", permissions: ["credentials.manage"] },
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/settings/ai-model", component: AIModelSettingsPage },
      { path: "/settings", component: { template: "<p>设置中心</p>" } },
    ],
  })
  await router.push("/settings/ai-model")
  render(AIModelSettingsPage, { global: { plugins: [[VueQueryPlugin, { queryClient: client }], router] } })
  await router.isReady()
  return client
}

beforeEach(() => {
  document.cookie = "csrftoken=test-token"
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0"
})

it("renders safe configured state without exposing the stored key", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(configured), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })))
  await renderPage()

  expect(await screen.findByRole("heading", { name: "AI 模型" })).toBeInTheDocument()
  expect(screen.getByLabelText("Provider")).toHaveValue("deepseek")
  expect(screen.getByLabelText("模型")).toHaveValue("deepseek-chat")
  expect(screen.getByLabelText("API Key")).toHaveValue("")
  expect(screen.queryByDisplayValue("fixture-secret-key")).not.toBeInTheDocument()
  expect(await screen.findByText("已启用真实模型")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "测试连接" })).toBeEnabled()
  expect(screen.getByText("$0.500000 / 天")).toBeInTheDocument()
  expect(document.body.textContent).not.toContain("fixture-secret-key")
})

it("saves a replacement key and clears it from the DOM after mutation", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...configured, configured: false, enabled: false }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify(configured), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
  vi.stubGlobal("fetch", fetchMock)
  await renderPage()

  await fireEvent.update(await screen.findByLabelText("API Key"), "fixture-secret-key")
  await fireEvent.click(screen.getByRole("button", { name: "保存配置" }))

  await waitFor(() => expect(screen.getByLabelText("API Key")).toHaveValue(""))
  const [, request] = fetchMock.mock.calls[1] as [string, RequestInit][]
  expect(JSON.parse(String(request.body))).toMatchObject({
    provider: "deepseek",
    model: "deepseek-chat",
    api_key: "fixture-secret-key",
  })
  expect(document.body.textContent).not.toContain("fixture-secret-key")
})

it("shows a safe invalid-key recovery state after connection testing", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(configured), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      code: "invalid_key",
      message: "连接失败，请检查密钥。",
      recovery_action: "请更新密钥后重试。",
    }), { status: 400, headers: { "Content-Type": "application/json" } }))
  vi.stubGlobal("fetch", fetchMock)
  await renderPage()

  await fireEvent.click(await screen.findByRole("button", { name: "测试连接" }))

  expect(await screen.findByRole("status")).toHaveTextContent("连接失败，请检查密钥")
  expect(document.body.textContent).not.toMatch(/bearer\s|fixture-secret-key/i)
})

it("accepts the API's empty 204 response when deleting a configured key", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(configured), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ...configured,
      configured: false,
      enabled: false,
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
  vi.stubGlobal("fetch", fetchMock)
  vi.spyOn(window, "confirm").mockReturnValue(true)
  await renderPage()

  await fireEvent.click(await screen.findByRole("button", { name: "删除密钥" }))

  expect(await screen.findByRole("status")).toHaveTextContent("密钥已删除")
  expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: "DELETE" })
})
