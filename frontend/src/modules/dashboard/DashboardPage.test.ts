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

const masterReview = {
  id: "master-review", brief_id: "brief-1", brief_version: 1, generation_job_id: "job-content",
  ai_run_id: "run-content", lineage_id: "lineage-master", previous_version_id: null, version: 1,
  payload: { title: "确认德国推广通用文案", body: "待确认正文", cta: "询价", concept_codes: [] },
  provenance: {}, status: "IN_REVIEW", is_current_head: true, created_by_id: 1,
  created_at: "2026-08-08T08:00:00Z", updated_at: "2026-08-08T08:00:00Z",
}

const platformReview = {
  id: "platform-review", master_content_id: "master-review", master_version: 1, platform_id: "platform-1",
  lineage_id: "lineage-platform", previous_version_id: null, version: 1,
  payload: { title: "确认 LinkedIn 推广文案", body: "待确认渠道正文", cta: "询价", concept_codes: [], platform_code: "LINKEDIN" },
  provenance: {}, status: "IN_REVIEW", is_current_head: true, created_by_id: 1,
  created_at: "2026-08-09T08:00:00Z", updated_at: "2026-08-09T08:00:00Z",
}

const analyticsSummary = {
  count: 2, total_clicks: 37, next: null, previous: null,
  results: [
    { date: "2026-08-11", campaign_id: "campaign-1", platform_id: "platform-1", country: "DE", product_id: "product-1", clicks: 25 },
    { date: "2026-08-10", campaign_id: "campaign-1", platform_id: "platform-2", country: "US", product_id: "product-1", clicks: 12 },
  ],
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
  if (path.startsWith("/api/v1/master-contents?status=IN_REVIEW")) return Promise.resolve(json({ next: null, previous: null, results: [masterReview] }))
  if (path.startsWith("/api/v1/platform-contents?status=IN_REVIEW")) return Promise.resolve(json({ next: null, previous: null, results: [platformReview] }))
  if (path.startsWith("/api/v1/analytics/channel-summary")) return Promise.resolve(json(analyticsSummary))
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
  permissions = ["leads.read", "leads.review", "jobs.read", "content.read", "content.review", "tracking.read"],
) {
  vi.stubGlobal("fetch", fetchMock)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: DashboardPage },
      { path: "/lead-radar", component: { template: "<p>客户机会页</p>" } },
      { path: "/reviews", component: { template: "<p>审核中心页</p>" } },
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

  expect(await screen.findByRole("heading", { name: "今天有 3 件事需要你决定" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "需要你决定" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "AI 正在帮你工作" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "最近结果" })).toBeVisible()
  expect(await screen.findByRole("heading", { name: "判断北方传动是否值得联系" })).toBeVisible()
  expect(await screen.findByText("正在筛选公开线索")).toBeVisible()
  expect(await screen.findByRole("heading", { name: "确认德国推广通用文案" })).toBeVisible()
  expect(await screen.findByRole("heading", { name: "确认 LinkedIn 推广文案" })).toBeVisible()
  expect(await screen.findByText("已完成 40%")).toBeVisible()
  expect(await screen.findByText("推广内容获得的点击")).toBeVisible()
  expect(await screen.findByText("37 次")).toBeVisible()
  expect(screen.queryByText("SOURCE_IMPORT")).not.toBeInTheDocument()
  expect(screen.queryByText("RUNNING")).not.toBeInTheDocument()
  expect(document.body).not.toHaveTextContent(/LeadCandidate|LeadInsight|SourceSignal|AIRun|Ontology/)
  expect(queryClient.getQueryState(["dashboard", "org-1", "decisions"])).toBeDefined()
  expect(queryClient.getQueryState(["dashboard", "org-1", "master-reviews"])).toBeDefined()
  expect(queryClient.getQueryState(["dashboard", "org-1", "platform-reviews"])).toBeDefined()
  for (const status of ["QUEUED", "RUNNING", "RETRY_QUEUED"]) {
    expect(queryClient.getQueryState(["dashboard", "org-1", "active-jobs", status])).toBeDefined()
  }
  expect(queryClient.getQueryState(["dashboard", "org-1", "recent-results"])).toBeDefined()
})

it("leads with decisions and explains what the user should do", async () => {
  await renderDashboard()

  expect(await screen.findByRole("heading", { name: /今天有 3 件事需要你决定/ })).toBeVisible()
  expect(screen.getByRole("region", { name: "需要你决定" })).toBeVisible()
  expect(screen.getByRole("region", { name: "AI 正在帮你工作" })).toBeVisible()
  expect(screen.getByRole("region", { name: "最近结果" })).toBeVisible()
  expect(screen.getByText(/现在确认可让后续跟进继续/)).toBeVisible()
})

it("keeps real content decisions without inventing a lead count when the lead source is unavailable", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/lead-candidates")) return Promise.resolve(json({ detail: "unavailable" }, 503))
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock)

  expect(await screen.findByText("部分待决定内容暂时没有加载成功。已加载的内容仍可处理。")).toBeVisible()
  expect(screen.getByRole("heading", { name: "今天有 2 件事需要你决定" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "确认德国推广通用文案" })).toBeVisible()
  expect(screen.queryByText("发现 2 个高意向潜客")).not.toBeInTheDocument()
  expect(screen.queryByText("北方传动")).not.toBeInTheDocument()
})

it("uses an at-least count when any decision source has another page", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/lead-candidates")) {
      return Promise.resolve(json({ next: "/api/v1/lead-candidates?cursor=next", previous: null, results: [lead] }))
    }
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock)

  expect(await screen.findByRole("heading", { name: "今天至少有 3 件事需要你决定" })).toBeVisible()
})

it("uses real effect metrics instead of successful job counts", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/analytics/channel-summary")) return Promise.resolve(json({ ...analyticsSummary, total_clicks: 91 }))
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock)

  expect(await screen.findByText("91 次")).toBeVisible()
  expect(screen.getByText("来自当前组织已记录的推广效果。")).toBeVisible()
  expect(fetchMock).not.toHaveBeenCalledWith("/api/v1/jobs?status=SUCCEEDED", expect.anything())
  expect(screen.queryByText("公开线索筛选已完成")).not.toBeInTheDocument()
})

it("requests the required bounded date range for recent analytics", async () => {
  const fetchMock = vi.fn(successfulFetch)
  await renderDashboard(fetchMock)

  await screen.findByText("37 次")
  const request = fetchMock.mock.calls.find(([path]) => String(path).startsWith("/api/v1/analytics/channel-summary"))
  const url = new URL(String(request?.[0]), "https://dashboard.test")
  expect(url.searchParams.get("start")).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  expect(url.searchParams.get("end")).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  expect(url.searchParams.get("limit")).toBe("5")
  expect(url.searchParams.get("offset")).toBe("0")
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
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/v1\/master-contents\?status=IN_REVIEW/), expect.objectContaining({ signal: expect.anything() }))
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/v1\/platform-contents\?status=IN_REVIEW/), expect.objectContaining({ signal: expect.anything() }))
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/v1\/analytics\/channel-summary/), expect.objectContaining({ signal: expect.anything() }))
  })
})

it("ranks decisions across lead and content work and renders only the top three", async () => {
  const lowLead = { ...lead, id: "lead-low", company_name: "低优先客户", latest_score: 12, latest_score_band: "LOW" }
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/lead-candidates")) return Promise.resolve(json({ next: null, previous: null, results: [lowLead, lead] }))
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock)

  const region = await screen.findByRole("region", { name: "需要你决定" })
  await within(region).findByRole("heading", { name: "判断北方传动是否值得联系" })
  const cards = within(region).getAllByText(/优先级 \d/).map((label) => label.closest("article")!)
  expect(cards).toHaveLength(3)
  expect(cards[0]).toHaveTextContent("北方传动")
  expect(cards[1]).toHaveTextContent("确认德国推广通用文案")
  expect(cards[2]).toHaveTextContent("确认 LinkedIn 推广文案")
  expect(region).not.toHaveTextContent("低优先客户")
})

it("aborts old organization requests and never paints their late results", async () => {
  let oldScope = true
  const oldRequests: Array<{ path: string; signal?: AbortSignal }> = []
  const oldResponses: Array<{ path: string; resolve: (response: Response) => void }> = []
  const fetchMock = vi.fn((path: string, options?: RequestInit) => {
    if (!oldScope || path.startsWith("/api/v1/jobs")) {
      if (path.startsWith("/api/v1/lead-candidates")) return Promise.resolve(json({ next: null, previous: null, results: [{ ...lead, id: "lead-new", company_name: "新组织客户" }] }))
      if (path.startsWith("/api/v1/master-contents?status=IN_REVIEW")) return Promise.resolve(json({ next: null, previous: null, results: [] }))
      if (path.startsWith("/api/v1/platform-contents?status=IN_REVIEW")) return Promise.resolve(json({ next: null, previous: null, results: [] }))
      if (path.startsWith("/api/v1/analytics/channel-summary")) return Promise.resolve(json({ count: 0, total_clicks: 6, next: null, previous: null, results: [] }))
      return successfulFetch(path)
    }
    oldRequests.push({ path, signal: options?.signal ?? undefined })
    return new Promise<Response>((resolve) => oldResponses.push({ path, resolve }))
  })
  const view = await renderDashboard(fetchMock)
  await waitFor(() => expect(oldRequests).toHaveLength(4))

  oldScope = false
  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, {
    ...userWith(["leads.read", "leads.review", "jobs.read", "content.read", "content.review", "tracking.read"]),
    organization: { id: "org-2", name: "另一组织", slug: "other" },
  })

  await waitFor(() => expect(oldRequests.every((request) => request.signal?.aborted)).toBe(true))
  expect(await screen.findByRole("heading", { name: "判断新组织客户是否值得联系" })).toBeVisible()
  for (const pending of oldResponses) {
    if (pending.path.startsWith("/api/v1/lead-candidates")) pending.resolve(json({ next: null, previous: null, results: [{ ...lead, company_name: "旧组织延迟客户" }] }))
    else if (pending.path.startsWith("/api/v1/analytics")) pending.resolve(json({ ...analyticsSummary, total_clicks: 999 }))
    else pending.resolve(json({ next: null, previous: null, results: [masterReview] }))
  }
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(screen.queryByText(/旧组织延迟客户|999 次/)).not.toBeInTheDocument()
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
  expect(await screen.findByText("37 次")).toBeVisible()

  await user.click(within(activityRegion).getByRole("button", { name: "重新加载未确认状态" }))
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs?status=RUNNING", expect.any(Object))
})

it("does not request or imply data the current user cannot read", async () => {
  const fetchMock = vi.fn()
  await renderDashboard(fetchMock, [])

  expect(await screen.findByText("你没有可在这里处理的客户机会或待确认内容。")).toBeVisible()
  expect(screen.getByText("你没有查看 AI 任务的权限。")).toBeVisible()
  expect(fetchMock).not.toHaveBeenCalled()
})

it("hides cached decisions immediately when review permissions are withdrawn", async () => {
  const view = await renderDashboard()
  expect(await screen.findByRole("heading", { name: "判断北方传动是否值得联系" })).toBeVisible()

  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(["leads.read", "content.read"]))

  expect(await screen.findByText("你没有可在这里处理的客户机会或待确认内容。")).toBeVisible()
  expect(screen.queryByRole("heading", { name: "判断北方传动是否值得联系" })).not.toBeInTheDocument()
  expect(screen.queryByRole("heading", { name: "确认德国推广通用文案" })).not.toBeInTheDocument()
})

it("guides first use toward adding public clues when every panel is empty", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path.startsWith("/api/v1/lead-candidates") || path.startsWith("/api/v1/jobs") || path.startsWith("/api/v1/master-contents") || path.startsWith("/api/v1/platform-contents")) {
      return Promise.resolve(json({ next: null, previous: null, results: [] }))
    }
    if (path.startsWith("/api/v1/analytics/channel-summary")) return Promise.resolve(json({ count: 0, total_clicks: 0, next: null, previous: null, results: [] }))
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock)

  expect(await screen.findByText("当前没有等待你决定的客户机会或待确认内容。")).toBeVisible()
  expect(screen.getAllByRole("link", { name: "前往客户机会" })[0]).toHaveAttribute("href", "/lead-radar")
})
