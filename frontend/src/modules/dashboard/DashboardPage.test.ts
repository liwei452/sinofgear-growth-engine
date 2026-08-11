import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import DashboardPage from "./DashboardPage.vue"

const lead = {
  id: "lead-1",
  company_name: "北方传动",
  company_domain: "beifang.example",
  country_hint: "CN",
  status: "ANALYZED",
  high_value_eligible: true,
  latest_score: 88,
  latest_score_band: "HIGH",
  version: 2,
  created_at: "2026-08-10T08:00:00Z",
  updated_at: "2026-08-11T08:00:00Z",
}

const runningJob = {
  job_id: "job-running",
  type: "SOURCE_IMPORT",
  status: "RUNNING",
  progress: 40,
  attempt: 1,
  max_attempts: 3,
  created_at: "2026-08-11T08:00:00Z",
  finished_at: null,
  error: null,
  result_reference: null,
}

const completedJob = {
  ...runningJob,
  job_id: "job-complete",
  status: "SUCCEEDED",
  progress: 100,
  finished_at: "2026-08-11T08:05:00Z",
}

const userWith = (permissions: string[]): CurrentUser => ({
  user: { id: 1, username: "operator" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "OPERATOR", status: "ACTIVE", permissions },
})

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function successfulFetch(path: string): Promise<Response> {
  if (path.startsWith("/api/v1/lead-candidates")) {
    return Promise.resolve(json({ next: null, previous: null, results: [lead] }))
  }
  if (path === "/api/v1/jobs?status=SUCCEEDED") {
    return Promise.resolve(json({ next: null, previous: null, results: [completedJob] }))
  }
  if (path === "/api/v1/jobs?status=RUNNING") {
    return Promise.resolve(json({ next: null, previous: null, results: [runningJob] }))
  }
  if (path === "/api/v1/jobs?status=QUEUED" || path === "/api/v1/jobs?status=RETRY_QUEUED") {
    return Promise.resolve(json({ next: null, previous: null, results: [] }))
  }
  throw new Error(`Unexpected request: ${path}`)
}

async function renderDashboard(
  fetchMock: ReturnType<typeof vi.fn> = vi.fn(successfulFetch),
  permissions = ["leads.read", "jobs.read"],
) {
  vi.stubGlobal("fetch", fetchMock)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: DashboardPage },
      { path: "/lead-radar", component: { template: "<p>客户机会页</p>" } },
    ],
  })
  router.push("/")
  await router.isReady()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(permissions))
  const view = render(DashboardPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient }], router] },
  })
  return { ...view, queryClient, router }
}

afterEach(() => vi.unstubAllGlobals())

it("renders three decision-cockpit regions from organization-scoped live data", async () => {
  const { queryClient } = await renderDashboard()

  expect(await screen.findByRole("heading", { name: "今天有 1 件事需要你决定" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "需要你决定" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "AI 正在帮你工作" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "最近结果" })).toBeVisible()
  expect(await screen.findByRole("heading", { name: "判断北方传动是否值得联系" })).toBeVisible()
  expect(await screen.findByText("正在筛选公开线索")).toBeVisible()
  expect(await screen.findByText("公开线索筛选已完成")).toBeVisible()
  expect(await screen.findByText("已完成 40%")).toBeVisible()
  expect(await screen.findByText("当前展示的完成任务")).toBeVisible()
  expect(screen.queryByText("SOURCE_IMPORT")).not.toBeInTheDocument()
  expect(screen.queryByText("RUNNING")).not.toBeInTheDocument()
  expect(document.body).not.toHaveTextContent(/LeadCandidate|LeadInsight|SourceSignal|AIRun|Ontology/)
  expect(queryClient.getQueryState(["dashboard", "org-1", "decisions"])).toBeDefined()
  for (const status of ["QUEUED", "RUNNING", "RETRY_QUEUED"]) {
    expect(queryClient.getQueryState(["dashboard", "org-1", "active-jobs", status])).toBeDefined()
  }
  expect(queryClient.getQueryState(["dashboard", "org-1", "recent-results"])).toBeDefined()
})

it("leads with decisions and explains what the user should do", async () => {
  await renderDashboard()

  expect(await screen.findByRole("heading", { name: /今天有 1 件事需要你决定/ })).toBeVisible()
  expect(screen.getByRole("region", { name: "需要你决定" })).toBeVisible()
  expect(screen.getByRole("region", { name: "AI 正在帮你工作" })).toBeVisible()
  expect(screen.getByRole("region", { name: "最近结果" })).toBeVisible()
  expect(screen.getByText(/现在确认可让后续跟进继续/)).toBeVisible()
})

it("does not invent counts when the lead source is unavailable", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/lead-candidates")) return Promise.resolve(json({ detail: "unavailable" }, 503))
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock)

  expect(await screen.findByText("客户机会暂时没有加载成功。")).toBeVisible()
  expect(screen.queryByText("发现 2 个高意向潜客")).not.toBeInTheDocument()
  expect(screen.queryByRole("heading", { name: /今天有 \d+ 件事需要你决定/ })).not.toBeInTheDocument()
})

it("uses an at-least count when the decision source has another page", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/lead-candidates")) {
      return Promise.resolve(json({ next: "/api/v1/lead-candidates?cursor=next", previous: null, results: [lead] }))
    }
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock)

  expect(await screen.findByRole("heading", { name: "今天至少有 1 件事需要你决定" })).toBeVisible()
})

it("labels a paged result metric as the work currently shown", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/jobs?status=SUCCEEDED") {
      return Promise.resolve(json({ next: "/api/v1/jobs?cursor=next", previous: null, results: [completedJob] }))
    }
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock)

  expect(await screen.findByText("当前展示的完成任务")).toBeVisible()
  expect(screen.getByText("当前展示的 1 项工作已完成，可以查看对应工作区的结果。")).toBeVisible()
})

it("passes cancelable signals to every dashboard data request", async () => {
  const fetchMock = vi.fn(successfulFetch)
  await renderDashboard(fetchMock)

  await screen.findByRole("heading", { name: "判断北方传动是否值得联系" })
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/v1\/lead-candidates/), expect.objectContaining({ signal: expect.anything() }))
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs?status=QUEUED", expect.objectContaining({ signal: expect.anything() }))
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs?status=RUNNING", expect.objectContaining({ signal: expect.anything() }))
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs?status=RETRY_QUEUED", expect.objectContaining({ signal: expect.anything() }))
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs?status=SUCCEEDED", expect.objectContaining({ signal: expect.anything() }))
  })
})

it("finds an older active job through status-filtered endpoints despite twenty newer terminal jobs", async () => {
  const newerTerminalJobs = Array.from({ length: 20 }, (_, index) => ({
    ...completedJob,
    job_id: `newer-terminal-${index}`,
  }))
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/jobs") {
      return Promise.resolve(json({ next: null, previous: null, results: newerTerminalJobs }))
    }
    if (path === "/api/v1/jobs?status=RUNNING") {
      return Promise.resolve(json({ next: null, previous: null, results: [runningJob] }))
    }
    if (path === "/api/v1/jobs?status=QUEUED" || path === "/api/v1/jobs?status=RETRY_QUEUED") {
      return Promise.resolve(json({ next: null, previous: null, results: [] }))
    }
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock)

  expect(await screen.findByText("正在筛选公开线索")).toBeVisible()
  expect(screen.queryByText("当前没有正在执行的 AI 工作。")).not.toBeInTheDocument()
  expect(fetchMock).not.toHaveBeenCalledWith("/api/v1/jobs", expect.any(Object))
})

it("keeps successful active statuses and other regions usable when one active-status query fails", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/jobs?status=RUNNING") return Promise.resolve(json({ detail: "unavailable" }, 503))
    if (path === "/api/v1/jobs?status=QUEUED") {
      return Promise.resolve(json({
        next: null,
        previous: null,
        results: [{ ...runningJob, job_id: "job-queued", status: "QUEUED" }],
      }))
    }
    return successfulFetch(path)
  })
  const user = userEvent.setup()
  await renderDashboard(fetchMock)

  const activityRegion = await screen.findByRole("region", { name: "AI 正在帮你工作" })
  expect(await within(activityRegion).findByRole("alert")).toHaveTextContent("部分 AI 工作状态暂时无法确认")
  expect(await within(activityRegion).findByText("正在筛选公开线索")).toBeVisible()
  expect(await screen.findByText("判断北方传动是否值得联系")).toBeVisible()
  expect(await screen.findByText("公开线索筛选已完成")).toBeVisible()

  await user.click(within(activityRegion).getByRole("button", { name: "重新加载未确认状态" }))
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs?status=RUNNING", expect.any(Object))
})

it("does not request or imply data the current user cannot read", async () => {
  const fetchMock = vi.fn()
  await renderDashboard(fetchMock, [])

  expect(await screen.findByText("你没有查看客户机会的权限。")).toBeVisible()
  expect(screen.getByText("你没有查看 AI 任务的权限。")).toBeVisible()
  expect(fetchMock).not.toHaveBeenCalled()
})

it("guides first use toward adding public clues when every panel is empty", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/lead-candidates") || path.startsWith("/api/v1/jobs")) {
      return Promise.resolve(json({ next: null, previous: null, results: [] }))
    }
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock)

  expect(await screen.findByText("还没有等待判断的客户机会。先添加公开线索，AI 才能帮你整理下一步。")).toBeVisible()
  expect(screen.getAllByRole("link", { name: "前往客户机会" })[0]).toHaveAttribute("href", "/lead-radar")
})
