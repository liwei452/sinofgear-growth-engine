import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "../auth/auth"
import BufferManagementPanel from "./BufferManagementPanel.vue"
import type { Platform, SocialAccount } from "./api"

const platforms: Platform[] = [
  { id: "platform-linkedin", code: "linkedin", name: "LinkedIn", capabilities: ["PUBLISH"] },
  { id: "platform-facebook", code: "facebook", name: "Facebook", capabilities: ["PUBLISH"] },
  { id: "platform-instagram", code: "instagram", name: "Instagram", capabilities: ["PUBLISH"] },
]

const accounts: SocialAccount[] = [
  {
    id: "account-linkedin",
    platform_id: "platform-linkedin",
    display_name: "Global LinkedIn",
    publish_mode: "API_AUTO",
    status: "ACTIVE",
    provider: "BUFFER",
    effective_capabilities: ["PUBLISH"],
    credential_configured: true,
    connection_state: "CONNECTED",
    disconnected_at: null,
    last_probe_at: "2026-08-20T10:00:00Z",
    last_refresh_at: "2026-08-20T10:00:00Z",
    lifecycle_error_code: "",
    provider_channel_display_id: "••••8042",
    provider_last_sync_at: "2026-08-20T10:05:00Z",
    reauthorization_required_at: null,
    is_locked: false,
    is_queue_paused: false,
  },
  {
    id: "account-facebook",
    platform_id: "platform-facebook",
    display_name: "Factory Facebook",
    publish_mode: "API_AUTO",
    status: "ACTIVE",
    provider: "BUFFER",
    effective_capabilities: ["PUBLISH"],
    credential_configured: true,
    connection_state: "CONNECTED",
    disconnected_at: null,
    last_probe_at: null,
    last_refresh_at: null,
    lifecycle_error_code: "",
    provider_channel_display_id: "••••1199",
    provider_last_sync_at: "2026-08-20T10:05:00Z",
    reauthorization_required_at: null,
    is_locked: true,
    is_queue_paused: true,
  },
]

const connected = {
  id: "connection-1",
  provider: "BUFFER",
  configured: true,
  external_id: "••••org9",
  display_name: "SinofGear Buffer",
  connection_state: "CONNECTED",
  last_probe_at: "2026-08-20T10:00:00Z",
  last_sync_at: "2026-08-20T10:05:00Z",
  reauthorization_required_at: null,
  disconnected_at: null,
  lifecycle_error_code: "",
  channel_count: 2,
  active_channel_count: 2,
}

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function renderPanel(fetchMock: ReturnType<typeof vi.fn>, role = "ADMINISTRATOR", permissions = ["publishing.read", "credentials.manage"]) {
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    user: { id: 1, username: "admin" },
    organization: { id: "organization-1", name: "SinofGear", slug: "sinofgear" },
    membership: { id: "membership-1", role, status: "ACTIVE", permissions },
  })
  return render(BufferManagementPanel, {
    props: { accounts, platforms },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

afterEach(() => vi.unstubAllGlobals())

it("shows only safe Buffer connection and channel fields to administrators", async () => {
  const fetchMock = vi.fn(() => Promise.resolve(response(connected)))
  renderPanel(fetchMock)

  expect(await screen.findByRole("heading", { name: "Buffer 连接概览" })).toBeInTheDocument()
  expect(screen.getByText("SinofGear Buffer")).toBeInTheDocument()
  expect(screen.getByText("••••org9")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "轮换 API Key" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "测试连接" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "同步渠道" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "断开连接" })).toBeInTheDocument()

  const linkedIn = screen.getByRole("article", { name: "LinkedIn 渠道 Global LinkedIn" })
  expect(within(linkedIn).getByText("渠道 ID ••••8042")).toBeInTheDocument()
  expect(within(linkedIn).getByText("可自动发布")).toBeInTheDocument()
  const facebook = screen.getByRole("article", { name: "Facebook 渠道 Factory Facebook" })
  expect(within(facebook).getByText("渠道已锁定")).toBeInTheDocument()
  expect(within(facebook).getByText("Buffer 队列已暂停")).toBeInTheDocument()
  expect(within(facebook).getByText("不可自动发布")).toBeInTheDocument()
  expect(document.body.textContent).not.toContain("credential_reference")
  expect(document.body.textContent).not.toContain("provider_metadata")
  expect(document.body.textContent).not.toContain("connector_metadata")
})

it("does not expose Buffer controls or API Key inputs without administrator permission", async () => {
  const fetchMock = vi.fn()
  renderPanel(fetchMock, "READ_ONLY", ["publishing.read"])

  expect(screen.queryByRole("heading", { name: "Buffer 连接概览" })).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Buffer API Key")).not.toBeInTheDocument()
  expect(fetchMock).not.toHaveBeenCalled()
})

it("connects from an explicit unconfigured state and clears the API Key immediately", async () => {
  document.cookie = "csrftoken=test; path=/"
  let connectedAfterPost = false
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/v1/provider-connections/buffer" && init?.method === "POST") {
      connectedAfterPost = true
      return Promise.resolve(response(connected, 201))
    }
    if (path === "/api/v1/provider-connections/buffer") {
      return Promise.resolve(connectedAfterPost
        ? response(connected)
        : response({ code: "BUFFER_CONNECTION_NOT_FOUND", message: "尚未配置 Buffer。" }, 404))
    }
    return Promise.resolve(response({ results: [] }))
  })
  renderPanel(fetchMock)

  expect((await screen.findAllByText("未配置")).length).toBeGreaterThan(0)
  await userEvent.click(await screen.findByRole("button", { name: "连接 Buffer" }))
  await userEvent.type(screen.getByLabelText("Buffer 组织 ID"), "buffer-org-1")
  const keyInput = screen.getByLabelText("Buffer API Key")
  expect(keyInput).toHaveAttribute("type", "password")
  await userEvent.type(keyInput, "private-key-value")
  await userEvent.click(screen.getByRole("button", { name: "保存连接" }))

  expect(await screen.findByText("Buffer 已连接。" )).toBeInTheDocument()
  expect(screen.queryByDisplayValue("private-key-value")).not.toBeInTheDocument()
  const connectCall = fetchMock.mock.calls.find(([path, init]) => path === "/api/v1/provider-connections/buffer" && init?.method === "POST")
  expect(JSON.parse(connectCall?.[1]?.body as string)).toEqual({ api_key: "private-key-value", organization_id: "buffer-org-1" })
  expect(JSON.stringify(document.defaultView?.localStorage)).not.toContain("private-key-value")
})

it("clears a rotated API Key after a safe provider error and shows recovery advice", async () => {
  document.cookie = "csrftoken=test; path=/"
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/v1/provider-connections/buffer" && init?.method === "PATCH") {
      return Promise.resolve(response({ code: "BUFFER_PROVIDER_UNAVAILABLE", message: "Buffer 暂时不可用。" }, 503))
    }
    return Promise.resolve(response(connected))
  })
  renderPanel(fetchMock)

  await userEvent.click(await screen.findByRole("button", { name: "轮换 API Key" }))
  await userEvent.type(screen.getByLabelText("新的 Buffer API Key"), "rotate-private-key")
  await userEvent.click(screen.getByRole("button", { name: "确认轮换" }))

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("服务暂时不可用，请稍后重试。")
  expect(alert).toHaveTextContent("稍后重新测试连接；若持续失败，请检查 Buffer 服务状态。")
  expect(screen.queryByDisplayValue("rotate-private-key")).not.toBeInTheDocument()
  expect(alert).not.toHaveTextContent("rotate-private-key")
})

it("requires the explicit disconnect warning and refreshes the connection after actions", async () => {
  document.cookie = "csrftoken=test; path=/"
  let disconnected = false
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path.endsWith("/disconnect") && init?.method === "POST") {
      disconnected = true
      return Promise.resolve(response({ ...connected, configured: false, connection_state: "DISCONNECTED" }))
    }
    return Promise.resolve(response(disconnected
      ? { ...connected, configured: false, connection_state: "DISCONNECTED" }
      : connected))
  })
  renderPanel(fetchMock)

  await userEvent.click(await screen.findByRole("button", { name: "断开连接" }))
  expect(screen.getByText("断开后将停用通过 Buffer 同步的发布渠道，但不会删除历史发布记录。")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "确认断开" }))

  expect(await screen.findByText("Buffer 已断开。" )).toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([path]) => path === "/api/v1/provider-connections/buffer").length).toBeGreaterThan(1)
  await waitFor(() => expect(screen.getAllByText("已断开").length).toBeGreaterThan(0))
})
