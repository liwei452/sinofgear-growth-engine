import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import DashboardPage from "./DashboardPage.vue"

const decisions = [
  { id: "p1", type: "PROMOTION_PLAN", title: "确认德国市场推广方案", explanation: "依据已确认产品资料生成。", priority: 90, version: 2, actions: ["APPROVE", "REQUEST_ADJUSTMENT", "REJECT"] },
  { id: "p2", type: "CONTENT_APPROVAL", title: "5 条内容已经准备好", explanation: "内容来自已确认的产品资料。", priority: 80, version: 1, actions: ["APPROVE"] },
  { id: "p3", type: "LEAD_HANDOFF", title: "发现 2 个值得联系的客户", explanation: "公开信息显示明确采购需求。", priority: 70, version: 4, actions: ["APPROVE", "REJECT"] },
]
const cockpit = {
  decisions,
  active_work: [
    { job_id: "j1", label: "正在生成平台内容", status: "RUNNING", progress: 65, progress_is_determinate: true },
    { job_id: "j2", label: "正在分析公开线索", status: "QUEUED", progress: 0, progress_is_determinate: false },
  ],
  recent_outcomes: [{ kind: "PUBLISHING", label: "内容发布", value: "4", detail: "最近 30 天真实完成记录" }],
  generated_at: "2026-08-12T12:00:00Z",
}
const currentUser: CurrentUser = {
  user: { id: 1, username: "operator" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "m1", role: "OPERATOR", status: "ACTIVE", permissions: ["director.read", "director.decide"] },
}
const json = (data: unknown, status = 200): Response => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } })

async function renderDashboard(fetchMock = vi.fn().mockResolvedValue(json(cockpit))) {
  vi.stubGlobal("fetch", fetchMock)
  document.cookie = "csrftoken=test-token; path=/"
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/", component: DashboardPage }] })
  router.push("/")
  await router.isReady()
  const view = render(DashboardPage, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })
  return { ...view, queryClient, fetchMock }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("loads one organization-scoped cockpit and renders only truthful user-facing data", async () => {
  const { queryClient, fetchMock } = await renderDashboard()

  expect(await screen.findByRole("heading", { level: 1, name: "今天有 3 件事需要你决定" })).toBeVisible()
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
  expect(screen.getByRole("heading", { name: "确认德国市场推广方案" })).toBeVisible()
  expect(screen.getByText("正在生成平台内容")).toBeVisible()
  expect(screen.getByRole("progressbar", { name: "正在分析公开线索的进度" })).not.toHaveAttribute("aria-valuenow")
  expect(screen.getByText("内容发布")).toBeVisible()
  expect(screen.getByText("4")).toBeVisible()
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/director/cockpit", expect.objectContaining({ signal: expect.anything() }))
  expect(queryClient.getQueryState(["director", "org-1", "cockpit"])).toBeDefined()
  expect(document.body).not.toHaveTextContent(/PROMOTION_PLAN|RUNNING|director\.read|PromptVersion|AIRun|provider_error|p1|j1/)
})

it("shows useful loading, empty, and recoverable error states", async () => {
  let resolve!: (response: Response) => void
  const fetchMock = vi.fn().mockImplementation(() => new Promise<Response>((done) => { resolve = done }))
  await renderDashboard(fetchMock)
  expect(screen.getByRole("status")).toHaveTextContent("正在整理")
  resolve(json({ ...cockpit, decisions: [], active_work: [], recent_outcomes: [] }))
  expect(await screen.findByRole("heading", { level: 1, name: "今天没有需要你决定的事" })).toBeVisible()
  expect(screen.getByText("AI 当前没有正在执行的工作。完成产品资料后，新的工作会出现在这里。")).toBeVisible()
  expect(screen.getByText("还没有可汇报的真实结果。开始推广后，系统会在这里汇总已记录的数据。")).toBeVisible()
})

it("keeps the page usable after an error and retries locally", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(json({ detail: "provider exploded" }, 503))
    .mockResolvedValueOnce(json(cockpit))
  const user = userEvent.setup()
  await renderDashboard(fetchMock)
  expect(await screen.findByRole("alert")).toHaveTextContent("今天的工作暂时没有加载成功")
  expect(document.body).not.toHaveTextContent("provider exploded")
  await user.click(screen.getByRole("button", { name: "重新加载" }))
  expect(await screen.findByRole("heading", { name: "确认德国市场推广方案" })).toBeVisible()
})

it("confirms approval, disables only its card, then refreshes", async () => {
  let finish!: (response: Response) => void
  const fetchMock = vi.fn((path: string, options?: RequestInit) => {
    if (options?.method === "POST") return new Promise<Response>((resolve) => { finish = resolve })
    return Promise.resolve(json(cockpit))
  })
  vi.spyOn(window, "confirm").mockReturnValue(true)
  const user = userEvent.setup()
  await renderDashboard(fetchMock)
  const first = (await screen.findByRole("heading", { name: "确认德国市场推广方案" })).closest("article")!
  const second = screen.getByRole("heading", { name: "5 条内容已经准备好" }).closest("article")!
  await user.click(within(first).getByRole("button", { name: "批准" }))
  expect(window.confirm).toHaveBeenCalledWith("确认批准“确认德国市场推广方案”吗？")
  expect(within(first).getAllByRole("button").every((button) => button.hasAttribute("disabled"))).toBe(true)
  expect(within(second).getByRole("button", { name: "批准" })).toBeEnabled()
  finish(json({ id: "p1", status: "APPROVED", version: 3 }))
  await waitFor(() => expect(fetchMock.mock.calls.filter(([path]) => path === "/api/v1/director/cockpit")).toHaveLength(2))
})

it.each([
  ["要求调整", "请说明需要怎样调整", "REQUEST_ADJUSTMENT"],
  ["拒绝", "请说明拒绝原因", "REJECT"],
])("requires a Chinese reason for %s", async (buttonName, dialogTitle, action) => {
  const user = userEvent.setup()
  const { fetchMock } = await renderDashboard()
  const first = (await screen.findByRole("heading", { name: "确认德国市场推广方案" })).closest("article")!
  await user.click(within(first).getByRole("button", { name: buttonName }))
  const dialog = screen.getByRole("dialog", { name: dialogTitle })
  await user.click(within(dialog).getByRole("button", { name: "提交" }))
  expect(within(dialog).getByRole("alert")).toHaveTextContent("请用中文填写原因")
  await user.type(within(dialog).getByLabelText("原因"), "请补充交付周期和适用设备。")
  await user.click(within(dialog).getByRole("button", { name: "提交" }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/director/proposals/p1/decisions",
    expect.objectContaining({ body: expect.stringContaining(`"action":"${action}"`) }),
  ))
})

it("explains a version conflict and refreshes the cockpit", async () => {
  const fetchMock = vi.fn((path: string, options?: RequestInit) => options?.method === "POST"
    ? Promise.resolve(json({ code: "director_version_conflict", detail: "stale", current_version: 3 }, 409))
    : Promise.resolve(json(cockpit)))
  vi.spyOn(window, "confirm").mockReturnValue(true)
  const user = userEvent.setup()
  await renderDashboard(fetchMock)
  await user.click((await screen.findByRole("heading", { name: "确认德国市场推广方案" })).closest("article")!.querySelector("button")!)
  expect(await screen.findByRole("alert")).toHaveTextContent("这件事刚刚发生了变化")
  await waitFor(() => expect(fetchMock.mock.calls.filter(([path]) => path === "/api/v1/director/cockpit")).toHaveLength(2))
})
