import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import LeadRadarPage from "./LeadRadarPage.vue"

const userWith = (permissions: string[], organizationId = "org-1"): CurrentUser => ({
  user: { id: 1, username: "operator" },
  organization: { id: organizationId, name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "OPERATOR", status: "ACTIVE", permissions },
})

const highLead = {
  id: "lead-high", company_name: "ABC Packaging", company_domain: "abc.example", country_hint: "DE",
  status: "ANALYZED", latest_score: 88, latest_score_band: "HIGH", high_value_eligible: false,
  version: 2, created_at: "2026-08-10T00:00:00Z", updated_at: "2026-08-10T01:00:00Z",
}

const waitingLead = {
  ...highLead, id: "lead-waiting", company_name: "", company_domain: "profile.example", country_hint: "US",
  status: "ANALYZING", latest_score: null, latest_score_band: null, high_value_eligible: null,
}

const handledLead = {
  ...highLead, id: "lead-handled", company_name: "Reviewed Company", status: "REVIEWED",
  latest_score: 91, high_value_eligible: true,
}

const lowLead = {
  ...highLead, id: "lead-low", company_name: "Low Score Company", latest_score: 31,
  latest_score_band: "LOW", high_value_eligible: false,
}

const detail = {
  id: "lead-high", company: { name: "ABC Packaging", domain: "abc.example", country_hint: "DE" },
  status: "ANALYZED", version: 2, created_at: "2026-08-10T00:00:00Z", updated_at: "2026-08-10T01:00:00Z",
  permitted_actions: ["REVIEW"], requirements: [], review_history: [], insight_history: [],
  evidence: [{
    id: "evidence-1", source_signal_id: "signal-1", platform: "LinkedIn",
    source_url: "https://example.test/post", original_text: "Need replacement helical gears",
    translated_text: "", language: "en", availability: "AVAILABLE", collection_method: "MANUAL",
    retention_class: "STANDARD", captured_at: "2026-08-10T00:00:00Z", public_published_at: null,
  }],
  latest_insight: {
    id: "insight-1", source_insight_id: null, origin: "AI", score: 88, score_band: "HIGH",
    high_value_eligible: false, explanation: "明确提出替换斜齿轮需求。", dimensions: {}, gates: {
      traceable_source: true, explicit_need_or_company_match: true, capability_evidence: false,
      audited_run: true, ontology_snapshot: true,
    },
    extracted_requirement_values: {}, ai_audit: {}, ai_confidence: "0.9000",
    company_match_confidence: "0.6000", evidence_confidence: "0.4000", review_reason: "",
    human_correction: null, reviewed_at: null, reviewed_by: null, version: 1,
    created_at: "2026-08-10T00:00:00Z",
  },
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

function list(results: unknown[], next: string | null = null, previous: string | null = null): Response {
  return json({ next, previous, results })
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function renderPage(
  fetchMock: ReturnType<typeof vi.fn>,
  permissions = ["leads.read", "sources.manage"],
  organizationId = "org-1",
) {
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(permissions, organizationId))
  return {
    ...render(LeadRadarPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } }),
    queryClient,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("explains collect then filter and labels summaries as current loaded results", async () => {
  renderPage(vi.fn(async (path: string) => path.includes("/lead-high") ? json(detail) : list([highLead])))

  expect(await screen.findByText("ABC Packaging")).toBeVisible()
  expect(screen.getByRole("heading", { name: "客户机会" })).toBeVisible()
  expect(screen.getByText("先收集指定范围内的公开线索，再由 AI 筛选值得你查看的机会。")).toBeVisible()
  expect(screen.getByRole("button", { name: "添加公开线索" })).toBeVisible()
  expect(screen.getByText("当前列表结果，不代表全部机会")).toBeVisible()
  for (const label of ["等待分析", "高价值待决定", "需要补证据", "已经处理"]) {
    expect(screen.getAllByText(label)[0]).toBeVisible()
  }
})

it("separates value, evidence sufficiency, and inferred company identity", async () => {
  const fetchMock = vi.fn(async (path: string) => path.includes("/lead-high") ? json(detail) : list([highLead]))
  const view = renderPage(fetchMock)

  expect(await screen.findByText("ABC Packaging")).toBeVisible()
  expect(screen.getAllByText("高价值机会").at(-1)).toBeVisible()
  expect(await screen.findByText("证据还不够")).toBeVisible()
  expect(screen.queryByText("已确认高价值")).not.toBeInTheDocument()
  expect(screen.getByText("ABC Packaging")).toBeVisible()
  expect(screen.getByText("待确认")).toBeVisible()
  expect(screen.getByText("高价值待决定").closest("article")).toHaveTextContent("1")
  expect(screen.getByText("需要补证据").closest("article")).toHaveTextContent("1")
  expect(await screen.findByText("公开来源：LinkedIn")).toBeVisible()
  expect(screen.getByText("明确提出替换斜齿轮需求。")).toBeVisible()

  await userEvent.click(screen.getByRole("button", { name: "查看依据" }))
  expect(view.emitted("select-candidate")).toEqual([["lead-high"]])
  expect(await screen.findByRole("heading", { name: "机会依据" })).toHaveFocus()
  await userEvent.click(screen.getByRole("button", { name: "关闭机会依据" }))
  expect(screen.getByRole("button", { name: "查看依据" })).toHaveFocus()
})

it("keeps adequate evidence separate from a low value score", async () => {
  const adequateDetail = {
    ...detail,
    id: "lead-low",
    latest_insight: {
      ...detail.latest_insight,
      score: 31,
      score_band: "LOW",
      high_value_eligible: false,
      gates: {
        traceable_source: true,
        explicit_need_or_company_match: true,
        capability_evidence: true,
        audited_run: true,
        ontology_snapshot: true,
      },
    },
  }
  renderPage(vi.fn(async (path: string) => path.includes("/lead-low")
    ? json(adequateDetail)
    : list([lowLead])), ["leads.read"], "org-low")

  expect(await screen.findByText("证据已达到判断门槛")).toBeVisible()
  expect(screen.getAllByText("当前价值较低").at(-1)).toBeVisible()
  expect(screen.queryByText("证据还不够")).not.toBeInTheDocument()
})

it("counts missing evidence independently of a low value score", async () => {
  const insufficientDetail = {
    ...detail,
    id: "lead-low",
    latest_insight: {
      ...detail.latest_insight,
      score: 31,
      score_band: "LOW",
      gates: {
        traceable_source: true,
        explicit_need_or_company_match: true,
        capability_evidence: false,
        audited_run: true,
        ontology_snapshot: true,
      },
    },
  }
  renderPage(vi.fn(async (path: string) => path.includes("/lead-low")
    ? json(insufficientDetail)
    : list([lowLead])), ["leads.read"], "org-low-evidence")

  expect(await screen.findByText("证据还不够")).toBeVisible()
  expect(screen.getByText("需要补证据").closest("article")).toHaveTextContent("1")
})

it("shows loaded evidence gates independently when no value score exists", async () => {
  const noScoreLead = {
    ...highLead, id: "lead-no-score", company_name: "Unscored Company",
    latest_score: null, latest_score_band: null, high_value_eligible: null,
  }
  const noScoreDetail = {
    ...detail,
    id: "lead-no-score",
    latest_insight: {
      ...detail.latest_insight,
      score: 0,
      score_band: "LOW",
      gates: {
        traceable_source: true,
        explicit_need_or_company_match: true,
        capability_evidence: true,
        audited_run: true,
        ontology_snapshot: true,
      },
    },
  }
  renderPage(vi.fn(async (path: string) => path.includes("/lead-no-score")
    ? json(noScoreDetail)
    : list([noScoreLead])), ["leads.read"], "org-no-score")

  expect(await screen.findByText("证据已达到判断门槛")).toBeVisible()
  expect(screen.getByText("等待判断")).toBeVisible()
})

it("distinguishes detail loading and failure from genuinely missing evidence", async () => {
  let finishDetail!: (response: Response) => void
  const pendingDetail = new Promise<Response>((resolve) => { finishDetail = resolve })
  const fetchMock = vi.fn(async (path: string) => path.includes("/lead-high")
    ? pendingDetail
    : list([highLead]))
  renderPage(fetchMock, ["leads.read"], "org-detail-error")

  expect(await screen.findByText("正在读取公开来源…")).toBeVisible()
  expect(screen.getByText("正在核对证据…")).toBeVisible()
  finishDetail(json({ detail: "private server detail" }, 500))
  expect(await screen.findByText("公开来源暂时无法加载")).toBeVisible()
  expect(screen.getByText("证据状态暂时无法加载")).toBeVisible()
  expect(screen.getByText("AI 理由暂时无法加载。")).toBeVisible()
  expect(screen.queryByText("公开来源：待补充")).not.toBeInTheDocument()
})

it("maps plain-language filters, resets pagination, and follows only safe cursors", async () => {
  const next = `${window.location.origin}/api/v1/lead-candidates?cursor=safe-next&score_band=HIGH`
  const fetchMock = vi.fn(async (path: string) => {
    if (/\/api\/v1\/lead-candidates\/[^?]+/.test(path)) return json({ ...detail, id: path.split("/").at(-1) })
    return list([highLead], next)
  })
  renderPage(fetchMock)
  const user = userEvent.setup()
  await screen.findByText("ABC Packaging")

  await user.selectOptions(screen.getByLabelText("机会价值"), "HIGH")
  await user.selectOptions(screen.getByLabelText("处理状态"), "UNREVIEWED")
  await user.type(screen.getByLabelText("公开平台"), "LinkedIn")
  await user.type(screen.getByLabelText("国家或地区"), "DE")
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/lead-candidates?score_band=HIGH&platform=LinkedIn&country=DE&review_state=UNREVIEWED",
    expect.anything(),
  ))

  await user.click(screen.getByRole("button", { name: "下一页" }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/lead-candidates?cursor=safe-next&score_band=HIGH",
    expect.anything(),
  ))
  await user.selectOptions(screen.getByLabelText("机会价值"), "WATCH")
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/lead-candidates?score_band=WATCH&platform=LinkedIn&country=DE&review_state=UNREVIEWED",
    expect.anything(),
  ))

  const unsafeFetch = vi.fn(async (path: string) => /\/api\/v1\/lead-candidates\/[^?]+/.test(path)
    ? json(detail)
    : list([highLead], "https://evil.example/api/v1/lead-candidates?cursor=stolen"))
  const unsafe = renderPage(unsafeFetch, ["leads.read"], "org-unsafe")
  await waitFor(() => expect(within(unsafe.container).getByRole("button", { name: "下一页" })).toBeDisabled())
})

it("keeps safe cursor pagination available when the current page only has pending analyses", async () => {
  const next = "/api/v1/lead-candidates?cursor=pending-next"
  const pendingLead = { ...waitingLead, status: "DISCOVERED" as const }
  const fetchMock = vi.fn(async (path: string) => {
    if (path === next) return list([highLead])
    if (path.includes("/lead-high")) return json(detail)
    if (/\/api\/v1\/lead-candidates\/[^?]+/.test(path)) {
      return json({
        ...detail,
        id: path.split("/").at(-1),
        status: "DISCOVERED",
        evidence: [],
        latest_insight: null,
      })
    }
    return list([waitingLead, pendingLead], next)
  })
  renderPage(fetchMock, ["leads.read"], "org-pending-pagination")

  expect(await screen.findByRole("heading", { name: "正在筛选公开线索" })).toBeVisible()
  const nextButton = screen.getByRole("button", { name: "下一页" })
  expect(nextButton).toBeEnabled()
  await userEvent.click(nextButton)

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(next, expect.anything()))
  expect(await screen.findByText("ABC Packaging")).toBeVisible()
})

it("keeps every organization query key scoped and refreshes the active filtered queue after import", async () => {
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/ingestion-batches") {
      return json({ job_id: "job-1", ingestion_batch_id: "batch-1", status: "QUEUED" }, 202)
    }
    if (path === "/api/v1/jobs/job-1") {
      return json({
        job_id: "job-1", organization_id: "org-filtered", type: "SOURCE_IMPORT", status: "SUCCEEDED",
        progress_current: 1, progress_total: 1, progress_message: "", attempt_count: 1, max_attempts: 3,
        available_at: "2026-08-10T00:00:00Z", started_at: "2026-08-10T00:00:00Z",
        finished_at: "2026-08-10T00:00:01Z", created_at: "2026-08-10T00:00:00Z",
        updated_at: "2026-08-10T00:00:01Z", error: null,
      })
    }
    return /\/api\/v1\/lead-candidates\/[^?]+/.test(path) ? json(detail) : list([highLead])
  })
  const view = renderPage(fetchMock, ["leads.read", "sources.manage"], "org-filtered")
  const user = userEvent.setup()
  await screen.findByText("ABC Packaging")
  await user.selectOptions(screen.getByLabelText("机会价值"), "HIGH")
  await user.click(screen.getByRole("button", { name: "添加公开线索" }))
  expect(screen.getByRole("heading", { name: "导入公开信号" })).toBeVisible()
  document.cookie = "csrftoken=token; path=/"
  await user.type(screen.getByLabelText("公开链接"), "https://example.test/post")
  await user.type(screen.getByLabelText("公开原文"), "public source text")
  await user.click(screen.getByRole("button", { name: "导入公开信号" }))
  await waitFor(() => expect(fetchMock.mock.calls.filter(([path]) => (
    path === "/api/v1/lead-candidates?score_band=HIGH"
  ))).toHaveLength(2))
  expect(screen.getByLabelText("机会价值")).toHaveValue("HIGH")

  const leadQueries = view.queryClient.getQueryCache().getAll()
    .filter((query) => query.queryKey[0] === "leads")
  expect(leadQueries.length).toBeGreaterThan(0)
  expect(leadQueries.every((query) => query.queryKey[1] === "org-filtered")).toBe(true)
})

it("lets read-only users inspect evidence but hides collection controls", async () => {
  const fetchMock = vi.fn(async (path: string) => path.includes("/lead-high") ? json(detail) : list([highLead]))
  const view = renderPage(fetchMock, ["leads.read"])
  expect(await screen.findByRole("button", { name: "查看依据" })).toBeVisible()
  expect(screen.queryByRole("button", { name: "添加公开线索" })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "查看依据" }))
  expect(view.emitted("select-candidate")).toEqual([["lead-high"]])
})

it("shows honest first-use, analyzing, and filtered-empty states", async () => {
  renderPage(vi.fn(async () => list([])), ["leads.read", "sources.manage"], "org-empty")
  expect(await screen.findByRole("heading", { name: "还没有公开线索" })).toBeVisible()
  expect(screen.getByText("添加你指定范围内的公开内容，AI 才会开始筛选机会。")).toBeVisible()

  const analyzing = renderPage(vi.fn(async (path: string) => path.includes("/lead-waiting")
    ? json({ ...detail, id: "lead-waiting", status: "ANALYZING", evidence: [], latest_insight: null })
    : list([waitingLead])), ["leads.read"], "org-analyzing")
  expect(await screen.findByRole("heading", { name: "正在筛选公开线索" })).toBeVisible()
  expect(screen.getByRole("status")).toHaveTextContent("分析完成后，值得查看的机会会出现在这里")
  await waitFor(() => expect(within(analyzing.container).getByText("需要补证据").closest("article"))
    .toHaveTextContent("等待分析"))
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()

  const filteredFetch = vi.fn(async () => list([]))
  renderPage(filteredFetch, ["leads.read"], "org-filter-empty")
  const user = userEvent.setup()
  await screen.findAllByRole("heading", { name: "还没有公开线索" })
  await user.selectOptions(screen.getAllByLabelText("机会价值").at(-1)!, "HIGH")
  expect(await screen.findByRole("heading", { name: "当前筛选没有结果" })).toBeVisible()
  expect(screen.getAllByRole("button", { name: "清除筛选" }).at(-1)).toBeVisible()
})

it("renders pending analysis copy when one detail has no latest insight", async () => {
  const pendingLead = { ...waitingLead, status: "DISCOVERED" as const }
  renderPage(vi.fn(async (path: string) => {
    if (path.includes("/lead-waiting")) {
      return json({ ...detail, id: "lead-waiting", status: "DISCOVERED", evidence: [], latest_insight: null })
    }
    if (path.includes("/lead-high")) return json(detail)
    return list([pendingLead, highLead])
  }), ["leads.read"], "org-pending-insight")

  expect(await screen.findByText("等待分析证据")).toBeVisible()
  expect(screen.getByText("等待 AI 完成分析。")).toBeVisible()
  expect(screen.getByText("需要补证据").closest("article")).toHaveTextContent("等待分析")
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it("cancels an obsolete filtered list and ignores its late result", async () => {
  const firstList = deferred<Response>()
  let initialSignal: AbortSignal | undefined
  const fetchMock = vi.fn((path: string, options?: RequestInit) => {
    if (path === "/api/v1/lead-candidates") {
      initialSignal = options?.signal as AbortSignal | undefined
      return firstList.promise
    }
    if (path === "/api/v1/lead-candidates?score_band=HIGH") return Promise.resolve(list([highLead]))
    if (path.includes("/lead-high")) return Promise.resolve(json(detail))
    return Promise.resolve(list([]))
  })
  renderPage(fetchMock, ["leads.read"], "org-filter-race")

  await userEvent.selectOptions(screen.getByLabelText("机会价值"), "HIGH")
  expect(await screen.findByText("ABC Packaging")).toBeVisible()
  expect(initialSignal?.aborted).toBe(true)

  firstList.resolve(list([waitingLead]))
  await new Promise((resolve) => { setTimeout(resolve, 0) })
  expect(screen.queryByText("profile.example")).not.toBeInTheDocument()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it("cancels obsolete organization details and ignores their late result", async () => {
  const oldDetail = deferred<Response>()
  const oldLead = { ...highLead, id: "lead-old", company_name: "Old Organization Lead" }
  const newLead = { ...highLead, id: "lead-new", company_name: "New Organization Lead" }
  let oldDetailSignal: AbortSignal | undefined
  let listCalls = 0
  const fetchMock = vi.fn((path: string, options?: RequestInit) => {
    if (path === "/api/v1/lead-candidates") {
      listCalls += 1
      return Promise.resolve(list(listCalls === 1 ? [oldLead] : [newLead]))
    }
    if (path.includes("/lead-old")) {
      oldDetailSignal = options?.signal as AbortSignal | undefined
      return oldDetail.promise
    }
    if (path.includes("/lead-new")) return Promise.resolve(json({ ...detail, id: "lead-new" }))
    return Promise.resolve(list([]))
  })
  const view = renderPage(fetchMock, ["leads.read"], "org-old")
  expect(await screen.findByText("Old Organization Lead")).toBeVisible()
  await waitFor(() => expect(oldDetailSignal).toBeDefined())

  view.queryClient.setQueryData(
    currentUserQueryOptions().queryKey,
    userWith(["leads.read"], "org-new"),
  )

  expect(await screen.findByText("New Organization Lead")).toBeVisible()
  expect(oldDetailSignal?.aborted).toBe(true)
  oldDetail.resolve(json({ ...detail, id: "lead-old", company: { name: "Obsolete Lead" } }))
  await new Promise((resolve) => { setTimeout(resolve, 0) })
  expect(screen.queryByText("Old Organization Lead")).not.toBeInTheDocument()
  expect(screen.queryByText("Obsolete Lead")).not.toBeInTheDocument()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it("limits a 50-row detail fan-out and aborts active work when unmounted", async () => {
  const manyLeads = Array.from({ length: 50 }, (_, index) => ({
    ...highLead,
    id: `lead-${index}`,
    company_name: `Company ${index}`,
  }))
  let activeDetails = 0
  let maximumActiveDetails = 0
  let abortedDetails = 0
  let detailCalls = 0
  const activeRequests: Array<{ resolve: (response: Response) => void }> = []
  const fetchMock = vi.fn((path: string, options?: RequestInit) => {
    if (path === "/api/v1/lead-candidates") return Promise.resolve(list(manyLeads))
    detailCalls += 1
    activeDetails += 1
    maximumActiveDetails = Math.max(maximumActiveDetails, activeDetails)
    const request = deferred<Response>()
    activeRequests.push({ resolve: request.resolve })
    const pending = request.promise.finally(() => { activeDetails -= 1 })
    const signal = options?.signal as AbortSignal | undefined
    signal?.addEventListener("abort", () => {
      abortedDetails += 1
      request.reject(new DOMException("Aborted", "AbortError"))
    }, { once: true })
    return pending
  })
  const view = renderPage(fetchMock, ["leads.read"], "org-concurrency")

  await screen.findByText("Company 0")
  await waitFor(() => expect(detailCalls).toBeGreaterThanOrEqual(4))
  expect(maximumActiveDetails).toBeLessThanOrEqual(4)
  activeRequests[0]?.resolve(json({ ...detail, id: "lead-0" }))
  await waitFor(() => expect(detailCalls).toBe(5))
  expect(maximumActiveDetails).toBeLessThanOrEqual(4)

  view.unmount()
  await waitFor(() => expect(abortedDetails).toBe(4))
  expect(detailCalls).toBe(5)
})

it("caps an oversized runtime page at 50 hydrated opportunities", async () => {
  const oversizedPage = Array.from({ length: 51 }, (_, index) => ({
    ...highLead,
    id: `oversized-${index}`,
    company_name: `Oversized Company ${index}`,
  }))
  let activeDetails = 0
  let maximumActiveDetails = 0
  let detailCalls = 0
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/v1/lead-candidates") return Promise.resolve(list(oversizedPage))
    detailCalls += 1
    activeDetails += 1
    maximumActiveDetails = Math.max(maximumActiveDetails, activeDetails)
    const candidateId = path.split("/").at(-1)
    return new Promise<Response>((resolve) => {
      setTimeout(() => {
        activeDetails -= 1
        resolve(json({ ...detail, id: candidateId }))
      }, 0)
    })
  })
  renderPage(fetchMock, ["leads.read"], "org-oversized-page")

  await waitFor(() => expect(detailCalls).toBe(50))
  await waitFor(() => expect(activeDetails).toBe(0))
  expect(maximumActiveDetails).toBeLessThanOrEqual(4)
  expect(screen.getByText("Oversized Company 49")).toBeVisible()
  expect(screen.queryByText("Oversized Company 50")).not.toBeInTheDocument()
})

it("announces loading and recovers from a plain-language error", async () => {
  let finish!: (response: Response) => void
  const pending = new Promise<Response>((resolve) => { finish = resolve })
  const fetchMock = vi.fn()
    .mockReturnValueOnce(pending)
    .mockResolvedValueOnce(list([handledLead]))
    .mockResolvedValueOnce(json({ ...detail, id: "lead-handled", status: "REVIEWED" }))
  renderPage(fetchMock, ["leads.read"], "org-retry")
  expect(screen.getByRole("status")).toHaveTextContent("正在加载客户机会")
  expect(screen.queryByRole("heading", { name: "当前机会概况" })).not.toBeInTheDocument()
  finish(json({ detail: "internal trace" }, 500))

  expect(await screen.findByRole("alert")).toHaveTextContent("客户机会没有加载成功")
  expect(screen.queryByRole("heading", { name: "当前机会概况" })).not.toBeInTheDocument()
  expect(screen.getByRole("alert")).not.toHaveTextContent("internal trace")
  await userEvent.click(screen.getByRole("button", { name: "重新加载" }))
  expect(await screen.findByText("Reviewed Company")).toBeVisible()
})
