import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, within } from "@testing-library/vue"
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
  permissions = ["leads.read", "jobs.read", "products.read", "knowledge.read", "assets.read"],
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
  expect(queryClient.getQueryState(["dashboard", "org-1", "active-jobs"])).toBeDefined()
  expect(queryClient.getQueryState(["dashboard", "org-1", "recent-results"])).toBeDefined()
})

it("keeps the other regions usable when one summary query fails", async () => {
  const fetchMock = vi.fn((path: string) => path === "/api/v1/jobs"
    ? Promise.resolve(json({ detail: "unavailable" }, 503))
    : successfulFetch(path))
  const user = userEvent.setup()
  await renderDashboard(fetchMock)

  const runningRegion = await screen.findByRole("region", { name: "AI 正在执行" })
  expect(await within(runningRegion).findByRole("alert")).toHaveTextContent("AI 执行情况暂时无法加载")
  expect(await screen.findByText("北方传动")).toBeVisible()
  expect(await screen.findByText("公开线索筛选已完成")).toBeVisible()
  expect(await screen.findByText("还缺可用素材")).toBeVisible()

  await user.click(within(runningRegion).getByRole("button", { name: "重新加载执行情况" }))
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/jobs", expect.any(Object))
})

it("does not request or imply data the current user cannot read", async () => {
  const fetchMock = vi.fn()
  await renderDashboard(fetchMock, [])

  expect(await screen.findByText("你没有查看客户机会的权限。")).toBeVisible()
  expect(screen.getByText("你没有查看 AI 任务的权限。")).toBeVisible()
  expect(screen.getByText("当前权限下无法检查公司资料完整度。")).toBeVisible()
  expect(fetchMock).not.toHaveBeenCalled()
})
