import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import type { PublishTask } from "./api"
import PublishMonitoringPanel from "./PublishMonitoringPanel.vue"

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  }))
}

function task(status: PublishTask["status"], overrides: Partial<PublishTask> = {}): PublishTask {
  return {
    id: `task-${status.toLowerCase()}`,
    platform_content_id: "content-linkedin",
    social_account_id: "account-linkedin",
    connector_code: "BUFFER",
    status,
    provider_submission_id: "",
    scheduled_at: "2026-08-21T08:00:00Z",
    provider_call_started_at: null,
    last_reconciled_at: null,
    created_at: "2026-08-21T07:00:00Z",
    finished_at: null,
    last_error: null,
    reconciliation_error_code: "",
    allowed_actions: {
      retry: { allowed: false, reason_code: "STATUS_NOT_RETRYABLE" },
      reconcile: { allowed: false, reason_code: "STATUS_NOT_RECONCILABLE" },
      confirm_published: { allowed: false, reason_code: "STATUS_NOT_RESOLVABLE" },
      confirm_not_published: { allowed: false, reason_code: "STATUS_NOT_RESOLVABLE" },
    },
    resolution_evidence: {
      ambiguous: false,
      candidate_count: null,
      latest_outcome: null,
      observed_at: null,
      query_window_end: null,
      query_window_ended: false,
      snapshot_valid: false,
      truncated: null,
    },
    ...overrides,
  } as PublishTask
}

function fetchFor(tasks: PublishTask[], operation?: (path: string, init?: RequestInit) => Promise<Response>) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (init?.method === "POST" && operation) return operation(path, init)
    if (path.includes("/publish-tasks/monitor")) {
      const group = new URL(path, "http://localhost").searchParams.get("group")
      const grouped = (group ? tasks.filter(item => {
        if (group === "ATTENTION") return item.status === "NEEDS_ATTENTION"
        if (group === "PROVIDER") return ["SUBMITTED", "SUBMISSION_UNKNOWN"].includes(item.status)
        if (group === "FAILED") return item.status === "FAILED"
        if (group === "COMPLETED") return item.status === "SUCCEEDED"
        return ["SCHEDULED", "QUEUED", "RUNNING"].includes(item.status)
      }) : tasks).sort((left, right) => {
        const priority = (status: PublishTask["status"]) => {
          if (status === "NEEDS_ATTENTION") return 0
          if (["SUBMITTED", "SUBMISSION_UNKNOWN"].includes(status)) return 1
          if (status === "FAILED") return 2
          if (["SCHEDULED", "QUEUED", "RUNNING"].includes(status)) return 3
          return 4
        }
        return priority(left.status) - priority(right.status)
      })
      return response({
        summary: {
          attention_count: tasks.filter(item => item.status === "NEEDS_ATTENTION").length,
          provider_pending_count: tasks.filter(item => ["SUBMITTED", "SUBMISSION_UNKNOWN"].includes(item.status)).length,
          failed_count: tasks.filter(item => item.status === "FAILED").length,
          waiting_count: tasks.filter(item => ["SCHEDULED", "QUEUED", "RUNNING"].includes(item.status)).length,
          today_succeeded_count: tasks.filter(item => item.status === "SUCCEEDED").length,
        },
        next: null,
        previous: null,
        results: grouped.map(item => ({
          ...item,
          platform_code: "LINKEDIN",
          platform_name: "LinkedIn",
          social_account_display_name: "Global LinkedIn",
          content_title: "Reliable custom gear supply",
          content_excerpt: "Evidence-backed manufacturing facts for qualified industrial buyers.",
        })),
      })
    }
    return response({})
  })
}

function renderPanel(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock)
  document.cookie = "csrftoken=test; path=/"
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(PublishMonitoringPanel, {
    props: { organizationId: "org" },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
  return { queryClient }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it("prioritizes actionable tasks and filters them from compact summaries", async () => {
  renderPanel(fetchFor([
    task("SUCCEEDED"),
    task("FAILED", { id: "task-failed" }),
    task("SUBMISSION_UNKNOWN", { id: "task-unknown" }),
    task("NEEDS_ATTENTION", { id: "task-attention" }),
  ]))

  expect(await screen.findByRole("button", { name: "需要人工处理 1" })).toBeVisible()
  expect(screen.getByRole("button", { name: "等待 Provider 确认 1" })).toBeVisible()
  expect(screen.getByRole("button", { name: "明确失败 1" })).toBeVisible()
  expect(screen.getByRole("button", { name: "今日发布成功 1" })).toBeVisible()

  const cards = screen.getAllByRole("article")
  expect(cards[0]).toHaveTextContent("需要人工确认")
  expect(cards[1]).toHaveTextContent("提交结果未知，系统正在安全对账")
  expect(cards[3]).toHaveTextContent("已确认发布")

  await userEvent.click(screen.getByRole("button", { name: "明确失败 1" }))
  expect(screen.getAllByRole("article")).toHaveLength(1)
  expect(screen.getByRole("article")).toHaveTextContent("发布失败")
})

it("uses one bounded monitor request and server-side group filtering", async () => {
  const fetchMock = fetchFor([task("FAILED")])
  renderPanel(fetchMock)

  await screen.findByRole("article")
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/publish-tasks/monitor?page_size=50")
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes("platform-contents"))).toBe(false)
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes("social-accounts"))).toBe(false)

  await userEvent.click(screen.getByRole("button", { name: "明确失败 1" }))
  await vi.waitFor(() => {
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes("group=FAILED"))).toBe(true)
  })
})

it("shows operations only from allowed_actions and reconciles without publishing", async () => {
  const operation = vi.fn(() => response(task("SUBMISSION_UNKNOWN")))
  const fetchMock = fetchFor([task("SUBMISSION_UNKNOWN", {
    allowed_actions: {
      ...task("SUBMISSION_UNKNOWN").allowed_actions,
      reconcile: { allowed: true, reason_code: null },
    },
  })], operation)
  renderPanel(fetchMock)

  expect(await screen.findByRole("button", { name: "查询 Buffer 状态" })).toBeVisible()
  expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "查询 Buffer 状态" }))

  expect(operation).toHaveBeenCalledWith(
    "/api/v1/publish-tasks/task-submission_unknown/reconcile",
    expect.objectContaining({ method: "POST" }),
  )
  expect(fetchMock.mock.calls.some(([path]) => String(path).includes("createPost"))).toBe(false)
  expect(await screen.findByText("等待下一次确认")).toBeVisible()
})

it("requires a second confirmation before retrying an allowed failed task", async () => {
  const operation = vi.fn(() => response(task("QUEUED")))
  renderPanel(fetchFor([task("FAILED", {
    allowed_actions: {
      ...task("FAILED").allowed_actions,
      retry: { allowed: true, reason_code: null },
    },
  })], operation))

  const user = userEvent.setup()
  await user.click(await screen.findByRole("button", { name: "重试发布" }))
  expect(operation).not.toHaveBeenCalled()
  expect(screen.getByRole("dialog")).toHaveTextContent("重新执行当前发布任务")
  await user.click(screen.getByRole("button", { name: "确认重试" }))
  expect(operation).toHaveBeenCalledWith(
    "/api/v1/publish-tasks/task-failed/retry",
    expect.objectContaining({ method: "POST" }),
  )
})

it("validates a native Buffer Post ID before requesting server verification", async () => {
  const operation = vi.fn(() => response(task("SUCCEEDED", {
    provider_submission_id: "buffer-post-8421",
  })))
  renderPanel(fetchFor([task("NEEDS_ATTENTION", {
    allowed_actions: {
      ...task("NEEDS_ATTENTION").allowed_actions,
      confirm_published: { allowed: true, reason_code: null },
    },
  })], operation))

  const user = userEvent.setup()
  await user.click(await screen.findByRole("button", { name: "确认已经发布" }))
  await user.type(screen.getByLabelText("Buffer Post ID"), "https://buffer.com/post/8421")
  expect(screen.getByRole("button", { name: "查询并确认发布" })).toBeDisabled()
  expect(screen.getByText("请输入原生 Buffer Post ID，不要粘贴链接。")).toBeVisible()

  await user.clear(screen.getByLabelText("Buffer Post ID"))
  await user.type(screen.getByLabelText("Buffer Post ID"), "buffer-post-8421")
  await user.click(screen.getByRole("button", { name: "查询并确认发布" }))
  expect(operation).toHaveBeenCalledWith(
    "/api/v1/publish-tasks/task-needs_attention/resolve",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ resolution: "CONFIRM_PUBLISHED", provider_post_id: "buffer-post-8421" }),
    }),
  )
})

it("requires strict displayed no-match evidence and explicit operator confirmation", async () => {
  const operation = vi.fn(() => response(task("FAILED")))
  const strictEvidence = {
    ambiguous: false,
    candidate_count: 0,
    latest_outcome: "NO_MATCH",
    observed_at: "2026-08-21T08:00:00Z",
    query_window_end: "2026-08-21T07:00:00Z",
    query_window_ended: true,
    snapshot_valid: true,
    truncated: false as const,
  }
  renderPanel(fetchFor([
    task("NEEDS_ATTENTION", {
      id: "task-strict",
      allowed_actions: {
        ...task("NEEDS_ATTENTION").allowed_actions,
        confirm_not_published: { allowed: true, reason_code: null },
      },
      resolution_evidence: strictEvidence,
    }),
    task("NEEDS_ATTENTION", {
      id: "task-truncated",
      allowed_actions: {
        ...task("NEEDS_ATTENTION").allowed_actions,
        confirm_not_published: { allowed: true, reason_code: null },
      },
      resolution_evidence: { ...strictEvidence, truncated: null },
    }),
  ], operation))

  const cards = await screen.findAllByRole("article")
  expect(within(cards[0]).getByRole("button", { name: "确认没有发布" })).toBeVisible()
  expect(within(cards[1]).queryByRole("button", { name: "确认没有发布" })).not.toBeInTheDocument()

  const user = userEvent.setup()
  await user.click(within(cards[0]).getByRole("button", { name: "确认没有发布" }))
  const dialog = screen.getByRole("dialog")
  expect(within(dialog).getByText("候选帖子数量").parentElement).toHaveTextContent("候选帖子数量0")
  expect(within(dialog).getByText("查询窗口已结束").parentElement).toHaveTextContent("查询窗口已结束是")
  expect(within(dialog).getByText("查询被截断").parentElement).toHaveTextContent("查询被截断否")
  expect(within(dialog).getByText("证据快照有效").parentElement).toHaveTextContent("证据快照有效是")
  expect(within(dialog).getByRole("button", { name: "确认关闭任务" })).toBeDisabled()
  await user.click(within(dialog).getByRole("checkbox", { name: "我确认 Buffer 查询窗口已结束且没有找到对应帖子。" }))
  await user.click(within(dialog).getByRole("button", { name: "确认关闭任务" }))
  expect(operation).toHaveBeenCalledWith(
    "/api/v1/publish-tasks/task-strict/resolve",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ resolution: "CONFIRM_NOT_PUBLISHED" }),
    }),
  )
})
