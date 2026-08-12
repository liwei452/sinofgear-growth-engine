import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import DeepSeekSettingsPage from "./DeepSeekSettingsPage.vue"

const secret = "sk-private-key-12345678"

type Configuration = {
  provider_code: string
  connection_state: string
  key_suffix: string
  credential_revision: number
  last_tested_at: string | null
  last_tested_by_id: number | null
  daily_budget_usd: string
  flash_max_output_tokens: number
  pro_max_output_tokens: number
  timeout_seconds: number
  updated_at: string | null
}

const disconnected: Configuration = {
  provider_code: "deepseek", connection_state: "NOT_CONFIGURED", key_suffix: "",
  credential_revision: 0, last_tested_at: null, last_tested_by_id: null,
  daily_budget_usd: "5.00", flash_max_output_tokens: 4096,
  pro_max_output_tokens: 8192, timeout_seconds: 60, updated_at: null,
}

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" },
  })
}

function renderPage(fetchMock: ReturnType<typeof vi.fn>, configuration = disconnected) {
  vi.stubGlobal("fetch", fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  client.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "admin" },
    organization: { id: "org-1", name: "示例组织", slug: "demo" },
    membership: { id: "member-1", role: "ADMINISTRATOR", status: "ACTIVE", permissions: ["credentials.manage"] },
  })
  return {
    ...render(DeepSeekSettingsPage, { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } }),
    client, configuration,
  }
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("requires a successful connection test before saving and never redisplays or caches the API Key", async () => {
  document.cookie = "csrftoken=csrf; path=/"
  const connected = { ...disconnected, connection_state: "CONNECTED", key_suffix: "5678", credential_revision: 1 }
  const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/test")) return response({ connection_state: "CONNECTED", recovery_code: null })
    if (init?.method === "PUT") return response(connected)
    return response(disconnected)
  })
  const { client } = renderPage(fetchMock)
  const user = userEvent.setup()

  expect(await screen.findByRole("heading", { name: "连接 DeepSeek" })).toBeInTheDocument()
  const keyInput = await screen.findByLabelText("API Key（DeepSeek 提供的访问密钥）")
  await user.click(keyInput)
  await user.paste(secret)
  expect(screen.getByRole("button", { name: "保存并启用" })).toBeDisabled()
  await user.click(screen.getByRole("button", { name: "先测试连接" }))

  expect(await screen.findByRole("status")).toHaveTextContent("连接测试成功")
  expect(keyInput).toHaveValue("")
  expect(screen.queryByDisplayValue(secret)).not.toBeInTheDocument()
  expect(JSON.stringify(client.getQueryCache().getAll().map((query) => query.state.data))).not.toContain(secret)
  expect(JSON.stringify(client.getMutationCache().getAll().map((mutation) => mutation.state.variables))).not.toContain(secret)
  const testCall = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/test"))
  expect(JSON.parse(String(testCall?.[1]?.body))).toEqual({ api_key: secret })

  await user.click(keyInput)
  await user.paste(secret)
  await user.click(screen.getByRole("button", { name: "保存并启用" }))
  expect(await screen.findByText("DeepSeek 已安全连接")).toBeInTheDocument()
  expect(screen.queryByLabelText("API Key（DeepSeek 提供的访问密钥）")).not.toBeInTheDocument()
  expect(document.body).not.toHaveTextContent(secret)
  expect(JSON.stringify(client.getQueryCache().getAll().map((query) => query.state.data))).not.toContain(secret)
  expect(JSON.stringify(client.getMutationCache().getAll().map((mutation) => mutation.state.variables))).not.toContain(secret)
})

it("wipes replacement secrets on Escape, backdrop close, reset, and a failed replacement", async () => {
  document.cookie = "csrftoken=csrf; path=/"
  const connected = { ...disconnected, connection_state: "CONNECTED", key_suffix: "1234", credential_revision: 2 }
  const fetchMock = vi.fn(async (_path: string, init?: RequestInit) => {
    if (String(_path).endsWith("/test") || init?.method === "PUT") return response({ recovery_code: "provider_unavailable" }, 400)
    return response(connected)
  })
  renderPage(fetchMock, connected)
  const user = userEvent.setup()
  expect(await screen.findByText("DeepSeek 已安全连接")).toBeInTheDocument()
  const opener = screen.getByRole("button", { name: "更换 API Key" })

  await user.click(opener)
  await user.click(screen.getByLabelText("API Key（DeepSeek 提供的访问密钥）"))
  await user.paste("sk-escape-key-12345678")
  await user.keyboard("{Escape}")
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(opener).toHaveFocus()

  await user.click(opener)
  await user.click(screen.getByLabelText("API Key（DeepSeek 提供的访问密钥）"))
  await user.paste("sk-backdrop-key-12345678")
  await user.click(screen.getByTestId("operation-modal-backdrop"))
  await user.click(opener)
  expect(screen.queryByDisplayValue("sk-backdrop-key-12345678")).not.toBeInTheDocument()
  await user.click(screen.getByLabelText("API Key（DeepSeek 提供的访问密钥）"))
  await user.paste("sk-reset-key-12345678")
  await user.click(screen.getByRole("button", { name: "清空" }))
  expect(screen.queryByDisplayValue("sk-reset-key-12345678")).not.toBeInTheDocument()

  await user.click(screen.getByLabelText("API Key（DeepSeek 提供的访问密钥）"))
  await user.paste(secret)
  await user.click(screen.getByRole("button", { name: "先测试连接" }))
  const alert = await screen.findByRole("alert")
  expect(screen.getByLabelText(/API Key/)).toHaveFocus()
  expect(alert).toHaveTextContent("连接没有成功")
  expect(alert).not.toHaveTextContent("provider_unavailable")
  expect(screen.getByText("尾号 1234")).toBeInTheDocument()
  expect(document.body).not.toHaveTextContent(secret)
})

it("disables duplicate submissions and announces progress to screen readers", async () => {
  document.cookie = "csrftoken=csrf; path=/"
  let finish!: (value: Response) => void
  const pending = new Promise<Response>((resolve) => { finish = resolve })
  const fetchMock = vi.fn(async (path: string) => path.endsWith("/test") ? pending : response(disconnected))
  renderPage(fetchMock)
  const user = userEvent.setup()
  await screen.findByLabelText("API Key（DeepSeek 提供的访问密钥）")
  await user.click(screen.getByLabelText("API Key（DeepSeek 提供的访问密钥）"))
  await user.paste(secret)
  await user.click(screen.getByRole("button", { name: "先测试连接" }))

  expect(screen.getByRole("button", { name: "正在测试…" })).toBeDisabled()
  expect(screen.getByRole("status")).toHaveTextContent("正在安全测试连接")
  await user.click(screen.getByRole("button", { name: "正在测试…" }))
  expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/test"))).toHaveLength(1)
  finish(response({ connection_state: "CONNECTED", recovery_code: null }))
  expect(await screen.findByText("连接测试成功，请重新输入同一个 API Key 后保存。" )).toBeInTheDocument()
})

it("retests the stored key and deletes only after an explicit confirmation", async () => {
  document.cookie = "csrftoken=csrf; path=/"
  const connected = { ...disconnected, connection_state: "CONNECTED", key_suffix: "1234", credential_revision: 2 }
  const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/test")) return response({ connection_state: "CONNECTED", recovery_code: null })
    if (init?.method === "DELETE") return response(disconnected)
    return response(connected)
  })
  renderPage(fetchMock, connected)
  const user = userEvent.setup()
  await screen.findByText("DeepSeek 已安全连接")
  await user.click(screen.getByRole("button", { name: "重新测试" }))
  expect(await screen.findByRole("status")).toHaveTextContent("现有连接可用")
  expect(JSON.parse(String(fetchMock.mock.calls.find(([path]) => String(path).endsWith("/test"))?.[1]?.body))).toEqual({})

  await user.click(screen.getByRole("button", { name: "删除连接" }))
  const dialog = screen.getByRole("dialog", { name: "确认删除 DeepSeek 连接" })
  expect(within(dialog).getByText(/删除后，AI 任务将暂停/)).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false)
  await user.click(within(dialog).getByRole("button", { name: "确认删除" }))
  expect(await screen.findByText("DeepSeek 尚未连接")).toBeInTheDocument()
})

it("uses responsive cards without fixed overflow at a 390px viewport", async () => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 })
  renderPage(vi.fn(async () => response(disconnected)))
  const page = await screen.findByTestId("deepseek-settings-page")
  await screen.findByText("日常任务自动使用快速方案")
  expect(page).toHaveClass("ai-settings-page")
  expect(page.querySelector(".ai-settings-grid")).toBeInTheDocument()
  expect(screen.getByText("日常任务自动使用快速方案")).toBeInTheDocument()
  expect(screen.getByText("复杂任务自动使用增强分析")).toBeInTheDocument()
  expect(screen.getByText("用量将在任务运行后显示于审计")).toBeInTheDocument()
})

it("ignores an in-flight save after the organization changes and clears all sensitive UI state", async () => {
  document.cookie = "csrftoken=csrf; path=/"
  let finishSave!: (value: Response) => void
  const pendingSave = new Promise<Response>((resolve) => { finishSave = resolve })
  const connectedA = { ...disconnected, connection_state: "CONNECTED", key_suffix: "1111", credential_revision: 1 }
  const connectedB = { ...disconnected, connection_state: "CONNECTED", key_suffix: "2222", credential_revision: 2 }
  let switched = false
  const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/test")) return response({ connection_state: "CONNECTED", recovery_code: null })
    if (init?.method === "PUT") return pendingSave
    return response(switched ? connectedB : disconnected)
  })
  const { client } = renderPage(fetchMock)
  const user = userEvent.setup()
  const input = await screen.findByLabelText(/API Key/)
  await user.type(input, secret)
  await user.click(screen.getByRole("button", { name: /先测试连接/ }))
  await screen.findByText(/连接测试成功/)
  await user.type(input, secret)
  await user.click(screen.getByRole("button", { name: /保存并启用/ }))

  client.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "admin" },
    organization: { id: "org-2", name: "组织二", slug: "two" },
    membership: { id: "member-2", role: "ADMINISTRATOR", status: "ACTIVE", permissions: ["credentials.manage"] },
  })
  switched = true
  client.setQueryData(["ai-provider-configuration", "org-2"], connectedB)
  finishSave(response(connectedA))

  await waitFor(() => expect(screen.getByText("尾号 2222")).toBeInTheDocument())
  expect(client.getQueryData(["ai-provider-configuration", "org-2"])).toEqual(connectedB)
  expect(document.body).not.toHaveTextContent(secret)
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
})

it("ignores an in-flight delete after permission loss and immediately hides administrator controls", async () => {
  document.cookie = "csrftoken=csrf; path=/"
  let finishDelete!: (value: Response) => void
  const pendingDelete = new Promise<Response>((resolve) => { finishDelete = resolve })
  const connected = { ...disconnected, connection_state: "CONNECTED", key_suffix: "1234", credential_revision: 2 }
  const fetchMock = vi.fn(async (_path: string, init?: RequestInit) => init?.method === "DELETE" ? pendingDelete : response(connected))
  const { client } = renderPage(fetchMock, connected)
  const user = userEvent.setup()
  await screen.findByText("尾号 1234")
  await user.click(screen.getByRole("button", { name: /删除连接/ }))
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: /确认删除/ }))
  client.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "admin" }, organization: { id: "org-1", name: "示例组织", slug: "demo" },
    membership: { id: "member-1", role: "OPERATOR", status: "ACTIVE", permissions: [] },
  })
  finishDelete(response(disconnected))
  await waitFor(() => expect(screen.queryByTestId("deepseek-settings-page")).not.toBeInTheDocument())
  expect(client.getQueryData(["ai-provider-configuration", "org-1"])).toBeUndefined()
})

it("edits connected limits only inside the secure key flow and persists the server response", async () => {
  document.cookie = "csrftoken=csrf; path=/"
  const connected = { ...disconnected, connection_state: "CONNECTED", key_suffix: "1234", credential_revision: 2 }
  const updated = { ...connected, daily_budget_usd: "9.50", timeout_seconds: 90 }
  const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/test")) return response({ connection_state: "CONNECTED", recovery_code: null })
    if (init?.method === "PUT") return response(updated)
    return response(connected)
  })
  renderPage(fetchMock, connected)
  const user = userEvent.setup()
  await screen.findByText("尾号 1234")
  expect(screen.getByLabelText(/每天最多使用/)).toBeDisabled()
  await user.click(screen.getByRole("button", { name: "修改限制" }))
  const dialog = screen.getByRole("dialog", { name: /修改 DeepSeek 设置/ })
  await user.clear(within(dialog).getByLabelText(/每天最多使用/))
  await user.type(within(dialog).getByLabelText(/每天最多使用/), "9.50")
  await user.clear(within(dialog).getByLabelText(/单次等待时间/))
  await user.type(within(dialog).getByLabelText(/单次等待时间/), "90")
  await user.type(within(dialog).getByLabelText(/API Key/), secret)
  await user.click(within(dialog).getByRole("button", { name: /先测试连接/ }))
  await screen.findByText(/连接测试成功/)
  await user.type(within(dialog).getByLabelText(/API Key/), secret)
  await user.click(within(dialog).getByRole("button", { name: /测试并保存设置/ }))
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT")
  expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({ api_key: secret, daily_budget_usd: "9.50", timeout_seconds: 90 })
  expect(await screen.findByDisplayValue("9.50")).toBeDisabled()
})

it("traps focus in both dialogs and restores the exact opener on every close path", async () => {
  const connected = { ...disconnected, connection_state: "CONNECTED", key_suffix: "1234", credential_revision: 2 }
  renderPage(vi.fn(async () => response(connected)), connected)
  const user = userEvent.setup()
  await screen.findByText("尾号 1234")
  const settingsOpener = screen.getByRole("button", { name: "修改限制" })
  settingsOpener.focus()
  await user.click(settingsOpener)
  const settingsDialog = screen.getByRole("dialog", { name: /修改 DeepSeek 设置/ })
  expect(within(settingsDialog).getByRole("heading")).toHaveFocus()
  await user.tab({ shift: true })
  expect(within(settingsDialog).getByRole("button", { name: "取消" })).toHaveFocus()
  await user.tab()
  expect(within(settingsDialog).getByLabelText(/每天最多使用/)).toHaveFocus()
  await fireEvent.keyDown(document, { key: "Escape" })
  expect(settingsOpener).toHaveFocus()

  const deleteOpener = screen.getByRole("button", { name: /删除连接/ })
  await user.click(deleteOpener)
  const deleteDialog = screen.getByRole("dialog", { name: /确认删除/ })
  expect(within(deleteDialog).getByRole("heading")).toHaveFocus()
  await user.tab({ shift: true })
  expect(within(deleteDialog).getByRole("button", { name: /保留连接/ })).toHaveFocus()
  await user.click(within(deleteDialog).getByRole("button", { name: /保留连接/ }))
  expect(deleteOpener).toHaveFocus()
})
