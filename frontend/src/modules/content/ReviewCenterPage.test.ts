import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import "../../styles/tokens.css"
import ReviewCenterPage from "./ReviewCenterPage.vue"

const currentUser = (permissions: string[]): CurrentUser => ({
  user: { id: 1, username: "reviewer" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "CUSTOM", status: "ACTIVE", permissions },
})
const campaign = { id: "campaign-1", name: "德国获客", description: "", status: "ACTIVE", version: 1, product_ids: [], created_at: "", updated_at: "" }
const master = (status = "IN_REVIEW", isCurrentHead = true) => ({
  id: "master-1", brief_id: "brief-1", brief_version: 1, generation_job_id: "job-1", ai_run_id: "run-1",
  lineage_id: "lineage-1", previous_version_id: null, version: 1,
  payload: { title: "精密齿轮解决方案", body: "面向德国工业采购的可靠齿轮。", cta: "立即询价", concept_codes: ["HELICAL_GEAR"] },
  provenance: { ai_run_id: "run-1", internal: { token: "never-render" } }, status,
  is_current_head: isCurrentHead,
  created_by_id: 1, created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
})
const platformContent = (status = "DRAFT") => ({
  id: "platform-content-1", master_content_id: "master-1", master_version: 1, platform_id: "platform-1",
  lineage_id: "platform-lineage-1", previous_version_id: null, version: 1,
  payload: { ...master().payload, platform_code: "LINKEDIN" }, provenance: {}, status,
  is_current_head: true,
  created_by_id: 1, created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
})
const brief = {
  id: "brief-1", campaign_id: "campaign-1", previous_version_id: null, version: 1, status: "READY",
  target_country: "德国", customer_type: "采购", content_objective: "询盘", cta: "询价",
  landing_page_url: "https://example.com", language: "de", prohibited_claims: [], selling_points: [],
  advantages: [], keywords: [], product_ids: ["product-1"], asset_ids: [], platform_ids: ["platform-1"],
  concept_links: [], created_by: 1, reviewed_by: 2, reviewed_at: "", created_at: "", updated_at: "",
}

function page<T>(results: T[]) { return { next: null, previous: null, results } }
function common(path: string) {
  if (path === "/api/v1/campaigns") return page([campaign])
  if (path === "/api/v1/platforms") return { results: [
    { id: "platform-1", code: "LINKEDIN", name: "LinkedIn", capabilities: ["PUBLISH"] },
    { id: "platform-2", code: "YOUTUBE", name: "YouTube", capabilities: ["PUBLISH"] },
  ] }
  if (path === "/api/v1/content-briefs/brief-1") return brief
  if (path === "/api/v1/ai-runs/run-1") return {
    id: "run-1", job_id: "job-1", job_attempt: 1, status: "SUCCEEDED",
    prompt: { purpose: "CONTENT_GENERATE", code: "content-default", version: 3, provider: "openai", model: "gpt-safe" },
    provider: "openai", model: "gpt-safe", confidence: "0.9200", human_correction: null, reviewer: null,
    created_at: "", started_at: "2026-08-09T00:00:00Z", finished_at: "2026-08-09T00:00:03Z", reviewed_at: null,
    input_snapshot: {
      Authorization: "never-render",
      ontology_snapshot: { concept_versions: [{ code: "DIN" }, { code: "PACKAGING_MACHINERY" }] },
    }, output_json: { title: "safe" }, error: null, provider_metadata: {},
  }
  return page([])
}

function renderPage(permissions: string[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser(permissions))
  return render(ReviewCenterPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
}

afterEach(() => { vi.unstubAllGlobals(); document.cookie = "csrftoken=; Max-Age=0; path=/" })

it("uses the shared SinofGear blue token for the selected review tab", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(
    path.startsWith("/api/v1/master-contents") ? page([]) : common(path),
  ), { status: 200, headers: { "Content-Type": "application/json" } })))
  renderPage(["content.read"])

  const selected = await screen.findByRole("tab", { name: "通用文案" })
  expect(getComputedStyle(selected).borderBottomColor).toBe("var(--sg-brand)")
  expect(getComputedStyle(document.documentElement).getPropertyValue("--sg-brand").trim()).toBe("#005ba8")
})

it("shows plain content fields and a safe, collapsed AI audit summary", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(
    path.startsWith("/api/v1/master-contents") ? page([master()]) : common(path),
  ), { status: 200, headers: { "Content-Type": "application/json" } })))
  const user = userEvent.setup()
  renderPage(["content.read", "jobs.read"])
  await user.click(await screen.findByRole("button", { name: "查看并确认" }))
  const reviewDialog = within(screen.getByRole("dialog"))

  expect(reviewDialog.getByRole("heading", { name: "精密齿轮解决方案" })).toBeInTheDocument()
  expect(reviewDialog.getByText("面向德国工业采购的可靠齿轮。")).toBeInTheDocument()
  expect(reviewDialog.getByText("HELICAL_GEAR")).toBeInTheDocument()
  expect(screen.queryByText(/never-render/)).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "查看AI生成记录" }))
  expect(await screen.findByText("gpt-safe")).toBeInTheDocument()
  expect(screen.getByText("已完成")).toBeInTheDocument()
  expect(screen.queryByText("SUCCEEDED")).not.toBeInTheDocument()
  expect(screen.getByText("DIN")).toBeInTheDocument()
  expect(screen.getByText("PACKAGING_MACHINERY")).toBeInTheDocument()
  expect(screen.getByText("content-default · v3")).toBeInTheDocument()
  expect(screen.queryByText(/Authorization|never-render/)).not.toBeInTheDocument()
})

it("uses beginner review language and consequence-oriented approval", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(
    path.startsWith("/api/v1/master-contents") ? page([master()]) : common(path),
  ), { status: 200, headers: { "Content-Type": "application/json" } })))
  const user = userEvent.setup()
  renderPage(["content.read", "content.review"])

  expect(await screen.findByText("等待确认")).toBeVisible()
  expect(screen.queryByText("IN_REVIEW")).not.toBeInTheDocument()
  await user.click(await screen.findByRole("button", { name: "查看并确认" }))
  expect(screen.getByRole("button", { name: "批准发布" })).toBeVisible()
})

it("creates a platform revision with the exact schema and immutable platform code", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let revisionBody: unknown
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/revisions") && options?.method === "POST") {
      revisionBody = JSON.parse(String(options.body))
      return new Response(JSON.stringify({ ...platformContent(), id: "platform-content-2", version: 2, previous_version_id: "platform-content-1" }), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    const body = path.startsWith("/api/v1/platform-contents") ? page([platformContent()])
      : path.startsWith("/api/v1/master-contents") ? page([]) : common(path)
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["content.read", "content.manage"])
  await user.click(await screen.findByRole("tab", { name: "渠道文案" }))
  await user.selectOptions(screen.getByLabelText("内容状态"), "DRAFT")
  await user.click(await screen.findByRole("button", { name: "查看并确认" }))
  await user.click(screen.getByRole("button", { name: "创建修改版" }))
  expect(screen.getByDisplayValue("LINKEDIN")).toBeDisabled()
  await user.clear(screen.getByLabelText("正文（必填）"))
  await user.type(screen.getByLabelText("正文（必填）"), "修改后的平台正文")
  await user.click(screen.getByRole("button", { name: "保存修改版" }))

  await waitFor(() => expect(revisionBody).toEqual({ payload: {
    title: "精密齿轮解决方案", body: "修改后的平台正文", cta: "立即询价",
    concept_codes: ["HELICAL_GEAR"], platform_code: "LINKEDIN",
  } }))
  expect(await screen.findByText("已创建第 2 版。")).toBeInTheDocument()
})

it("requires a rejection reason and sends the guarded review action", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let rejectionBody: unknown
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/reject") && options?.method === "POST") {
      rejectionBody = JSON.parse(String(options.body))
      return new Response(JSON.stringify({ ...master(), status: "REJECTED" }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(path.startsWith("/api/v1/master-contents") ? page([master()]) : common(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["content.read", "content.review"])
  await user.click(await screen.findByRole("button", { name: "查看并确认" }))
  await user.click(screen.getByRole("button", { name: "驳回" }))
  await user.click(screen.getByRole("button", { name: "确认驳回" }))
  expect(screen.getByRole("alert")).toHaveTextContent("请填写驳回原因")
  expect(rejectionBody).toBeUndefined()
  await user.type(screen.getByLabelText("驳回原因（必填）"), "需要补充数据来源")
  await user.click(screen.getByRole("button", { name: "确认驳回" }))
  await waitFor(() => expect(rejectionBody).toEqual({ comment: "需要补充数据来源" }))
})

it("generates only platforms selected by the source brief", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let generated: unknown
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/generate-platform-content") && options?.method === "POST") {
      generated = JSON.parse(String(options.body))
      return new Response(JSON.stringify(platformContent("IN_REVIEW")), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(path.startsWith("/api/v1/master-contents") ? page([master("APPROVED")]) : common(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["content.read", "content.manage"])
  await user.selectOptions(await screen.findByLabelText("内容状态"), "APPROVED")
  await user.click(await screen.findByRole("button", { name: "查看并确认" }))
  await user.click(screen.getByRole("button", { name: "生成渠道版本" }))

  expect(await screen.findByRole("button", { name: "为 LinkedIn 生成" })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "为 YouTube 生成" })).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "为 LinkedIn 生成" }))
  await waitFor(() => expect(generated).toEqual({ platform_id: "platform-1" }))
})

it("refreshes the active review queue when a guarded action conflicts", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let listRequests = 0
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/approve") && options?.method === "POST") {
      return new Response(JSON.stringify({ detail: "conflict" }), { status: 409, headers: { "Content-Type": "application/json" } })
    }
    if (path.startsWith("/api/v1/master-contents")) {
      listRequests += 1
      return new Response(JSON.stringify(page([master()])), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(common(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["content.read", "content.review"])
  await user.click(await screen.findByRole("button", { name: /查看并确认/ }))
  await user.click(screen.getByRole("button", { name: /批准发布/ }))

  await waitFor(() => expect(listRequests).toBe(2))
  expect(screen.getByRole("alert")).toBeInTheDocument()
})

it("hides review mutations when permission and status guards do not both pass", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(JSON.stringify(
    path.startsWith("/api/v1/master-contents") ? page([master()]) : common(path),
  ), { status: 200, headers: { "Content-Type": "application/json" } })))
  const user = userEvent.setup()
  renderPage(["content.read"])
  await user.click(await screen.findByRole("button", { name: /查看并确认/ }))

  expect(screen.queryByRole("button", { name: /^批准发布$/ })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /^驳回$/ })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /创建修改版/ })).not.toBeInTheDocument()
})

it("trusts the server current-head flag when a successor is outside the page", async () => {
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/approve") && options?.method === "POST") {
      throw new Error("stale content must not be approved")
    }
    return new Response(JSON.stringify(
      path.startsWith("/api/v1/master-contents") ? page([master("IN_REVIEW", false)]) : common(path),
    ), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["content.read", "content.review"])

  await user.click(await screen.findByRole("button", { name: /查看并确认/ }))

  expect(screen.queryByRole("button", { name: /^批准发布$/ })).not.toBeInTheDocument()
  expect(fetchMock).not.toHaveBeenCalledWith(expect.stringMatching(/\/approve$/), expect.anything())
})

it("loads and reviews an item from the second safe cursor page", async () => {
  const second = { ...master(), id: "master-2", payload: { ...master().payload, title: "第二页待审内容" } }
  const fetchMock = vi.fn(async (path: string) => {
    if (path.startsWith("/api/v1/master-contents?status=IN_REVIEW&cursor=two")) {
      return new Response(JSON.stringify(page([second])), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.startsWith("/api/v1/master-contents")) {
      return new Response(JSON.stringify({ next: "/api/v1/master-contents?status=IN_REVIEW&cursor=two", previous: null, results: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify(common(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderPage(["content.read", "content.review"])

  await user.click(await screen.findByRole("button", { name: "加载更多待审内容" }))
  await user.click(await screen.findByRole("button", { name: "查看并确认" }))

  expect(within(screen.getByRole("dialog")).getByRole("heading", { name: "第二页待审内容" })).toBeInTheDocument()
})

it("resets accumulated cursor pages when review filters change", async () => {
  const second = { ...master(), id: "master-old-page-2", payload: { ...master().payload, title: "旧筛选第二页" } }
  const filtered = { ...master("DRAFT"), id: "master-draft", payload: { ...master().payload, title: "草稿筛选结果" } }
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path.includes("status=DRAFT")) return new Response(JSON.stringify(page([filtered])), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path.includes("cursor=two")) return new Response(JSON.stringify(page([second])), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path.startsWith("/api/v1/master-contents")) return new Response(JSON.stringify({ next: "/api/v1/master-contents?status=IN_REVIEW&cursor=two", previous: null, results: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(common(path)), { status: 200, headers: { "Content-Type": "application/json" } })
  }))
  const user = userEvent.setup()
  renderPage(["content.read"])
  await user.click(await screen.findByRole("button", { name: "加载更多待审内容" }))
  expect(await screen.findByText("旧筛选第二页")).toBeInTheDocument()

  await user.selectOptions(screen.getByLabelText("内容状态"), "DRAFT")

  expect(await screen.findByText("草稿筛选结果")).toBeInTheDocument()
  expect(screen.queryByText("旧筛选第二页")).not.toBeInTheDocument()
})

it("recovers campaign and platform filter options after first-page errors", async () => {
  const attempts = new Map<string, number>()
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path === "/api/v1/campaigns" || path === "/api/v1/platforms") {
      const attempt = (attempts.get(path) ?? 0) + 1
      attempts.set(path, attempt)
      if (attempt === 1) return new Response(JSON.stringify({ detail: "temporary" }), {
        status: 503, headers: { "Content-Type": "application/json" },
      })
      const results = path.endsWith("campaigns")
        ? [{ ...campaign, id: "campaign-recovered", name: "恢复的活动" }]
        : [{ id: "platform-recovered", code: "RECOVERED", name: "恢复的平台", capabilities: [] }]
      return new Response(JSON.stringify({ next: null, previous: null, results }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    return new Response(JSON.stringify(
      path.startsWith("/api/v1/master-contents") ? page([]) : common(path),
    ), { status: 200, headers: { "Content-Type": "application/json" } })
  }))
  const user = userEvent.setup()
  renderPage(["content.read"])

  await user.click(await screen.findByRole("button", { name: "重新加载活动" }))
  await user.click(screen.getByRole("button", { name: "重新加载平台" }))

  expect(await screen.findByRole("option", { name: "恢复的活动" })).toBeInTheDocument()
  await user.click(screen.getByRole("tab", { name: "渠道文案" }))
  expect(await screen.findByRole("option", { name: "恢复的平台" })).toBeInTheDocument()
  expect(attempts).toEqual(new Map([
    ["/api/v1/campaigns", 2], ["/api/v1/platforms", 2],
  ]))
})
