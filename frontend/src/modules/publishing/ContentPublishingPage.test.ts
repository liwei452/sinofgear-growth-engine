import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import ContentPublishingPage from "./ContentPublishingPage.vue"

const platformContent = {
  id: "content-1",
  master_content_id: "master-1",
  master_version: 1,
  platform_id: "linkedin",
  lineage_id: "lineage-1",
  previous_version_id: null,
  version: 1,
  status: "IN_REVIEW",
  is_current_head: true,
  publish_package_id: null,
  created_by_id: 1,
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
  provenance: { source: "approved facts" },
  payload: {
    schema_version: 2,
    platform_code: "LINKEDIN",
    language: "en",
    title: "Gear reliability",
    body: "Verified efficiency data.",
    cta: "Contact us",
    landing_page_url: "https://example.test",
    hashtags: [],
    evidence_fact_ids: ["fact-1"],
  },
}

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(
    typeof body === "string" ? body : JSON.stringify(body),
    { status, headers: { "Content-Type": "application/json" } },
  ))
}

function currentUser(
  permissions = ["publishing.read", "content.review"],
  role = "OPERATOR",
) {
  return {
    user: { id: 1, username: "operator" },
    organization: { id: "org", name: "Org", slug: "org" },
    membership: { id: "member", role, status: "ACTIVE", permissions },
  }
}

function standardFetch(
  input: RequestInfo | URL,
  options: {
    master?: unknown[]
    platform?: unknown[]
    tasks?: unknown[]
    permissions?: string[]
    role?: string
  } = {},
) {
  const path = String(input)
  if (path.includes("/master-contents")) return response({ next: null, previous: null, results: options.master ?? [] })
  if (path.includes("/platform-contents")) return response({ next: null, previous: null, results: options.platform ?? [platformContent] })
  if (path.includes("/publish-tasks")) return response({ next: null, previous: null, results: options.tasks ?? [] })
  if (path.includes("/platforms")) return response({ results: [{ id: "linkedin", code: "LINKEDIN", name: "LinkedIn", capabilities: [] }] })
  return response(currentUser(options.permissions, options.role))
}

async function renderPage(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/content-factory", component: ContentPublishingPage },
      { path: "/promotion", component: { template: "<div />" } },
      { path: "/missions", component: { template: "<div />" } },
      { path: "/platform-accounts", component: { template: "<div />" } },
    ],
  })
  await router.push("/content-factory")
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(ContentPublishingPage, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })
  await router.isReady()
  return { queryClient }
}

afterEach(() => vi.unstubAllGlobals())

it("uses three primary stages and keeps the operational status as a secondary filter", async () => {
  await renderPage(vi.fn((input: RequestInfo | URL) => standardFetch(input)))

  await screen.findByRole("tab", { name: "待处理 1" })
  const primaryTabs = screen.getAllByRole("tab")
  expect(primaryTabs).toHaveLength(3)
  expect(screen.getByRole("tab", { name: "待处理 1" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "计划中 0" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "已完成 0" })).toBeVisible()
  expect(screen.getByRole("button", { name: "待人工审核 1" })).toBeVisible()
  expect(screen.queryByRole("tab", { name: /待人工审核/ })).not.toBeInTheDocument()
})

it("opens platform evidence without treating review content as published", async () => {
  await renderPage(vi.fn((input: RequestInfo | URL) => standardFetch(input)))
  await userEvent.setup().click(await screen.findByRole("button", { name: /查看内容/ }))

  expect(screen.getByRole("dialog")).toHaveTextContent("LinkedIn")
  expect(screen.getByRole("dialog")).toHaveTextContent("证据")
  expect(screen.getByRole("dialog")).not.toHaveTextContent("已发布")
})

it("keeps conflicting account outcomes in their correct primary groups", async () => {
  await renderPage(vi.fn((input: RequestInfo | URL) => standardFetch(input, {
    platform: [{ ...platformContent, status: "APPROVED" }],
    tasks: [
      { id: "task-success", platform_content_id: "content-1", social_account_id: "account-a", connector_code: "OFFICIAL_API", status: "SUCCEEDED", provider_submission_id: "published-a" },
      { id: "task-unknown", platform_content_id: "content-1", social_account_id: "account-b", connector_code: "BUFFER", status: "SUBMISSION_UNKNOWN", provider_submission_id: "pending-b" },
    ],
  })))

  const user = userEvent.setup()
  await user.click(await screen.findByRole("tab", { name: "计划中 1" }))
  await user.click(screen.getByRole("button", { name: "已提交 1" }))
  expect(await screen.findByText("账号：account-b")).toBeVisible()
  expect(screen.getByText("平台提交状态待确认；请勿重复发布")).toBeVisible()
  expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument()

  await user.click(screen.getByRole("tab", { name: "已完成 1" }))
  expect(await screen.findByText("账号：account-a")).toBeVisible()
  expect(screen.getByText("平台已确认发布")).toBeVisible()
})

it("loads cursor pages and supports roving keyboard navigation across three primary tabs", async () => {
  const user = userEvent.setup()
  await renderPage(vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    if (path.includes("/master-contents?cursor=next")) {
      return response({ next: null, previous: null, results: [{ ...platformContent, id: "master-2", status: "DRAFT" }] })
    }
    if (path.includes("/master-contents")) {
      return response({ next: "/api/v1/master-contents?cursor=next", previous: null, results: [] })
    }
    return standardFetch(input, { platform: [] })
  }))

  const pending = await screen.findByRole("tab", { name: "待处理 1" })
  pending.focus()
  await user.keyboard("{ArrowRight}")
  expect(screen.getByRole("tab", { name: "计划中 0" })).toHaveFocus()
  await user.keyboard("{End}")
  expect(screen.getByRole("tab", { name: "已完成 0" })).toHaveFocus()
  await user.click(pending)
  await user.click(screen.getByRole("button", { name: "AI 草稿 1" }))
  expect(await screen.findByText("Gear reliability")).toBeVisible()
})

it("moves approved review content into the planned group", async () => {
  const user = userEvent.setup()
  let approved = false
  document.cookie = "csrftoken=test-token"
  await renderPage(vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.includes("/platform-contents/content-1/approve") && init?.method === "POST") {
      approved = true
      return response({ ...platformContent, status: "APPROVED" })
    }
    return standardFetch(input, {
      platform: [{ ...platformContent, status: approved ? "APPROVED" : "IN_REVIEW" }],
    })
  }))

  await user.click(await screen.findByRole("button", { name: /查看内容/ }))
  await user.click(screen.getByRole("button", { name: "通过" }))
  await user.click(await screen.findByRole("tab", { name: "计划中 1" }))
  expect(screen.getByRole("button", { name: "准备发布 1" })).toBeVisible()
  expect(await screen.findByText("Gear reliability")).toBeVisible()
})

it("keeps error and unknown submission copy attached to the underlying status", async () => {
  await renderPage(vi.fn((input: RequestInfo | URL) => standardFetch(input, {
    platform: [{ ...platformContent, status: "APPROVED" }],
    tasks: [
      { id: "failed", platform_content_id: "content-1", social_account_id: "failed-account", connector_code: "OFFICIAL_API", status: "FAILED", provider_submission_id: null },
      { id: "canceled", platform_content_id: "content-1", social_account_id: "canceled-account", connector_code: "OFFICIAL_API", status: "CANCELED", provider_submission_id: null },
      { id: "unknown", platform_content_id: "content-1", social_account_id: "unknown-account", connector_code: "BUFFER", status: "SUBMISSION_UNKNOWN", provider_submission_id: "pending" },
    ],
  })))

  const user = userEvent.setup()
  const needsAttention = await screen.findByRole("button", { name: "需要处理 2" })
  expect(screen.getByRole("tabpanel", { name: /^待处理/ })).toBeVisible()
  expect(document.getElementById("publishing-panel-PLANNED")).toHaveProperty("hidden", true)
  await user.click(needsAttention)
  expect(await screen.findByText("平台发布失败；请人工检查后处理")).toBeVisible()
  expect(screen.getByText("发布任务已取消；尚未发布")).toBeVisible()

  await user.click(screen.getByRole("tab", { name: "计划中 1" }))
  await user.click(screen.getByRole("button", { name: "已提交 1" }))
  expect(await screen.findByText("平台提交状态待确认；请勿重复发布")).toBeVisible()
})

it("offers permission-aware next actions in empty primary stages", async () => {
  await renderPage(vi.fn((input: RequestInfo | URL) => standardFetch(input, {
    master: [],
    platform: [],
    tasks: [],
    role: "ADMINISTRATOR",
    permissions: ["publishing.read", "content.manage", "content.review", "missions.read", "credentials.manage"],
  })))

  expect(await screen.findByRole("link", { name: "生成内容" })).toHaveAttribute("href", "/promotion")
  expect(screen.getByRole("link", { name: "前往审核" })).toHaveAttribute("href", "/missions")

  await userEvent.setup().click(screen.getByRole("tab", { name: "计划中 0" }))
  expect(screen.getByRole("link", { name: "创建社媒计划" })).toHaveAttribute("href", "/promotion")
  expect(screen.getByRole("link", { name: "配置平台账户" })).toHaveAttribute("href", "/platform-accounts")
})

it("does not present a task-read failure as a published outcome", async () => {
  await renderPage(vi.fn((input: RequestInfo | URL) => {
    if (String(input).includes("/publish-tasks")) return response("unavailable", 503)
    return standardFetch(input, { platform: [{ ...platformContent, status: "APPROVED" }] })
  }))

  expect(await screen.findByRole("alert")).toHaveTextContent("内容或发布状态暂时无法读取")
  expect(screen.queryByText("平台已确认发布")).not.toBeInTheDocument()
})

it("suppresses retained published tasks when their refresh fails", async () => {
  let taskRequests = 0
  const { queryClient } = await renderPage(vi.fn((input: RequestInfo | URL) => {
    if (String(input).includes("/publish-tasks")) {
      taskRequests += 1
      if (taskRequests === 1) {
        return response({
          next: null,
          previous: null,
          results: [{ id: "published", platform_content_id: "content-1", social_account_id: "account-a", connector_code: "OFFICIAL_API", status: "SUCCEEDED", provider_submission_id: "published-a" }],
        })
      }
      return response("unavailable", 503)
    }
    return standardFetch(input, { platform: [{ ...platformContent, status: "APPROVED" }] })
  }))

  await userEvent.setup().click(await screen.findByRole("tab", { name: "已完成 1" }))
  expect(await screen.findByText("平台已确认发布")).toBeVisible()
  await queryClient.invalidateQueries({ queryKey: ["publishing-workspace", "tasks"] })
  expect(await screen.findByRole("alert")).toHaveTextContent("内容或发布状态暂时无法读取")
  expect(screen.queryByText("平台已确认发布")).not.toBeInTheDocument()
})
