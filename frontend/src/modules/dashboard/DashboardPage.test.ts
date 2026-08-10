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
  if (path === "/api/v1/jobs") {
    return Promise.resolve(json({ next: null, previous: null, results: [runningJob] }))
  }
  if (path === "/api/v1/products") {
    return Promise.resolve(json({ next: null, previous: null, results: [{ id: "product-1" }] }))
  }
  if (path === "/api/v1/knowledge/concepts") {
    return Promise.resolve(json({ results: [{ id: "concept-1" }] }))
  }
  if (path === "/api/v1/assets") {
    return Promise.resolve(json({ next: null, previous: null, results: [] }))
  }
  throw new Error(`Unexpected request: ${path}`)
}

async function renderDashboard(
  fetchMock: ReturnType<typeof vi.fn> = vi.fn(successfulFetch),
  permissions = [
    "leads.read", "jobs.read",
    "products.read", "products.manage",
    "knowledge.read", "knowledge.create",
    "assets.read", "assets.manage",
  ],
) {
  vi.stubGlobal("fetch", fetchMock)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: DashboardPage },
      { path: "/lead-radar", component: { template: "<p>客户机会页</p>" } },
      { path: "/products", component: { template: "<p>产品页</p>" } },
      { path: "/knowledge", component: { template: "<p>知识页</p>" } },
      { path: "/assets", component: { template: "<p>素材页</p>" } },
      { path: "/content-factory", component: { template: "<p>内容页</p>" } },
      { path: "/company-profile", component: { template: "<p>公司资料页</p>" } },
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

it("renders four honest decision-inbox regions from organization-scoped live data", async () => {
  const { queryClient } = await renderDashboard()

  expect(await screen.findByRole("heading", { name: "今天需要你决定" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "AI 正在执行" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "近期结果" })).toBeVisible()
  expect(screen.getByRole("heading", { name: "公司资料还缺什么" })).toBeVisible()
  expect(await screen.findByText("北方传动")).toBeVisible()
  expect(await screen.findByText("正在筛选公开线索")).toBeVisible()
  expect(await screen.findByText("公开线索筛选已完成")).toBeVisible()
  expect(await screen.findByText("还缺可用素材")).toBeVisible()
  expect(screen.queryByText("SOURCE_IMPORT")).not.toBeInTheDocument()
  expect(screen.queryByText("RUNNING")).not.toBeInTheDocument()
  expect(queryClient.getQueryState(["dashboard", "org-1", "decisions"])).toBeDefined()
  for (const status of ["QUEUED", "RUNNING", "RETRY_QUEUED"]) {
    expect(queryClient.getQueryState(["dashboard", "org-1", "active-jobs", status])).toBeDefined()
  }
  expect(queryClient.getQueryState(["dashboard", "org-1", "recent-results"])).toBeDefined()
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
  expect(screen.queryByText("当前没有正在执行的 AI 任务。")).not.toBeInTheDocument()
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

  const runningRegion = await screen.findByRole("region", { name: "AI 正在执行" })
  expect(await within(runningRegion).findByRole("alert")).toHaveTextContent("部分 AI 执行状态暂时无法确认")
  expect(await within(runningRegion).findByText("正在筛选公开线索")).toBeVisible()
  expect(within(runningRegion).queryByText("当前没有正在执行的 AI 任务。")).not.toBeInTheDocument()
  expect(await screen.findByText("北方传动")).toBeVisible()
  expect(await screen.findByText("公开线索筛选已完成")).toBeVisible()
  expect(await screen.findByText("还缺可用素材")).toBeVisible()

  await user.click(within(runningRegion).getByRole("button", { name: "重新加载未确认状态" }))
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs?status=RUNNING", expect.any(Object))
})

it("does not request or imply data the current user cannot read", async () => {
  const fetchMock = vi.fn()
  await renderDashboard(fetchMock, [])

  expect(await screen.findByText("你没有查看客户机会的权限。")).toBeVisible()
  expect(screen.getByText("你没有查看 AI 任务的权限。")).toBeVisible()
  expect(screen.getByText("当前权限下无法检查公司资料完整度。")).toBeVisible()
  expect(fetchMock).not.toHaveBeenCalled()
})

it.each([
  { read: "products.read", action: "查看产品库", forbidden: "补充产品" },
  { read: "knowledge.read", action: "查看知识库", forbidden: "补充知识" },
  { read: "assets.read", action: "查看素材库", forbidden: "补充素材" },
])("uses read-only company-gap guidance for $read", async ({ read, action, forbidden }) => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/knowledge/concepts") return Promise.resolve(json({ results: [] }))
    if (path === "/api/v1/products" || path === "/api/v1/assets") {
      return Promise.resolve(json({ next: null, previous: null, results: [] }))
    }
    return successfulFetch(path)
  })
  await renderDashboard(fetchMock, [read])

  expect(await screen.findByRole("link", { name: action })).toBeVisible()
  expect(screen.queryByRole("link", { name: forbidden })).not.toBeInTheDocument()
  expect(screen.getByText(/如需补充，请联系管理员/)).toBeVisible()
})

it("updates company-gap actions when mutation permissions change", async () => {
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/knowledge/concepts") return Promise.resolve(json({ results: [] }))
    if (path === "/api/v1/products" || path === "/api/v1/assets") {
      return Promise.resolve(json({ next: null, previous: null, results: [] }))
    }
    return successfulFetch(path)
  })
  const readPermissions = ["products.read", "knowledge.read", "assets.read"]
  const { queryClient } = await renderDashboard(fetchMock, readPermissions)

  expect(await screen.findByRole("link", { name: "查看产品库" })).toBeVisible()
  expect(screen.getByRole("link", { name: "查看知识库" })).toBeVisible()
  expect(screen.getByRole("link", { name: "查看素材库" })).toBeVisible()

  queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith([
    ...readPermissions,
    "products.manage", "knowledge.create", "assets.manage",
  ]))

  await waitFor(() => {
    expect(screen.getByRole("link", { name: "补充产品" })).toBeVisible()
    expect(screen.getByRole("link", { name: "补充知识" })).toBeVisible()
    expect(screen.getByRole("link", { name: "补充素材" })).toBeVisible()
  })
  expect(screen.queryByRole("link", { name: /查看.+库/ })).not.toBeInTheDocument()
})
