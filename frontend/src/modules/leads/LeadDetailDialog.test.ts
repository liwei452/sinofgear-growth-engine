import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { currentUserQueryOptions, type CurrentUser } from "../auth/auth"
import LeadDetailDialog from "./LeadDetailDialog.vue"

const userWith = (permissions: string[]): CurrentUser => ({
  user: { id: 1, username: "reviewer" },
  organization: { id: "org-1", name: "示例组织", slug: "demo" },
  membership: { id: "member-1", role: "REVIEWER", status: "ACTIVE", permissions },
})

const detail = {
  id: "lead-1",
  company: { name: "ABC Packaging", domain: "abc.example", country_hint: "DE" },
  status: "ANALYZED",
  version: 2,
  created_at: "2026-08-10T00:00:00Z",
  updated_at: "2026-08-10T01:00:00Z",
  permitted_actions: ["ANALYZE", "CONFIRM", "CORRECT", "DISMISS", "REQUEST_MORE_EVIDENCE"],
  evidence: [{
    id: "evidence-1",
    source_signal_id: "signal-1",
    platform: "LinkedIn",
    source_url: "https://example.test/post",
    original_text: "We need replacement helical gears, 200 pcs.",
    translated_text: "我们需要 200 件替换斜齿轮。",
    language: "en",
    availability: "AVAILABLE",
    collection_method: "MANUAL",
    retention_class: "STANDARD",
    captured_at: "2026-08-10T00:00:00Z",
    public_published_at: null,
  }],
  requirements: [{
    id: "requirement-1",
    requirement_code: "HELICAL_GEAR",
    requirement_label: "斜齿轮",
    capability_code: "GEAR_HOBBING",
    capability_label: "滚齿加工",
    capability_knowledge_evidence_id: "knowledge-1",
    source_evidence_id: "evidence-1",
    extracted_value: "200",
    unit: "pcs",
  }],
  review_history: [],
  insight_history: [],
  latest_insight: {
    id: "insight-1",
    source_insight_id: null,
    origin: "AI",
    score: 88,
    score_band: "HIGH",
    high_value_eligible: false,
    explanation: "为什么值得查看",
    dimensions: { intent: 28, company_fit: 20, specificity: 18, capability_fit: 14, recency: 8 },
    gates: {
      traceable_source: true,
      explicit_need_or_company_match: true,
      capability_evidence: false,
      audited_run: true,
      ontology_snapshot: true,
    },
    extracted_requirement_values: {},
    ai_audit: { ai_run_id: "run-1", status: "SUCCEEDED", prompt_code: "lead", prompt_version: 4, model: "model-1" },
    ai_confidence: "0.9000",
    company_match_confidence: "0.6000",
    evidence_confidence: "0.4000",
    review_reason: "",
    human_correction: null,
    reviewed_at: null,
    reviewed_by: null,
    version: 1,
    created_at: "2026-08-10T00:00:00Z",
  },
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
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

function renderDialog(
  permissions = ["leads.read", "leads.analyze", "leads.review", "leads.handoff"],
  fetchMock = vi.fn(async () => json(detail)),
) {
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(permissions))
  return {
    ...render(LeadDetailDialog, {
    props: { organizationId: "org-1", candidateId: "lead-1", open: true },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
    }),
    fetchMock,
    queryClient,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("orders judgment, reasons, source evidence, uncertainty, decision, and CRM export", async () => {
  renderDialog(["leads.read", "leads.analyze", "leads.review", "leads.handoff", "credentials.manage"])
  const original = await screen.findByText("We need replacement helical gears, 200 pcs.")
  const judgment = screen.getByRole("heading", { name: "AI 判断" })
  const explanation = screen.getByRole("heading", { name: "判断理由" })
  const evidence = screen.getByRole("heading", { name: "来源证据" })
  const uncertainty = screen.getByRole("heading", { name: "不确定项" })
  const decision = screen.getByRole("heading", { name: "人工决定" })
  const handoff = screen.getByRole("heading", { name: "CRM 与导出" })
  const mainSections = [judgment, explanation, evidence, uncertainty, decision, handoff]
    .map((heading) => heading.closest(".detail-section")!)
  for (let index = 0; index < mainSections.length - 1; index += 1) {
    expect(mainSections[index]?.nextElementSibling).toBe(mainSections[index + 1])
  }
  expect(mainSections.at(-1)?.nextElementSibling).toBe(screen.getByText("高级审计信息").closest("details"))
  expect(explanation.compareDocumentPosition(original) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getByRole("link", { name: "打开公开来源" })).toHaveAttribute("target", "_blank")
  expect(screen.getByRole("link", { name: "打开公开来源" })).toHaveAttribute("rel", "noopener noreferrer")
  expect(screen.getByText("高级审计信息").closest("details")).not.toHaveAttribute("open")
})

it("does not put technical AI audit data in the DOM for ordinary lead readers", async () => {
  const technical = {
    ...detail,
    latest_insight: {
      ...detail.latest_insight,
      ai_audit: {
        ai_run_id: "run-private", provider: "deepseek", model: "deepseek-v4-pro",
        routing: { reason: "private-route" }, cost: "private-cost",
      },
    },
  }
  renderDialog(["leads.read"], vi.fn(async () => json(technical)))

  await screen.findByText("ABC Packaging")
  expect(screen.queryByText("高级审计信息")).not.toBeInTheDocument()
  expect(document.body).not.toHaveTextContent(/deepseek|v4|private-route|private-cost|分析模型|服务提供方/i)
})

it("requires a reason before dismissing", async () => {
  renderDialog()
  const opener = await screen.findByRole("button", { name: "暂不跟进" })
  await userEvent.click(opener)
  expect(screen.getByRole("heading", { name: "记录人工决定" })).toHaveFocus()
  expect(screen.getByRole("button", { name: "确认暂不跟进" })).toBeDisabled()
  await userEvent.click(screen.getByRole("button", { name: "取消" }))
  expect(screen.getByRole("button", { name: "暂不跟进" })).toHaveFocus()
})

it("marks inferred identity and requirements as unconfirmed while keeping value separate from evidence", async () => {
  renderDialog()
  await screen.findByText("ABC Packaging")
  expect(screen.getByText("机会价值").closest("div")).toHaveTextContent("高价值机会")
  expect(screen.getByText("证据充分度").closest("div")).toHaveTextContent("证据还不够")
  expect(screen.getAllByText("待确认").length).toBeGreaterThanOrEqual(3)
  expect(screen.getByText("斜齿轮").closest("article")).toHaveTextContent("待确认")
})

it("renders no link for an unsafe public source URL", async () => {
  const unsafe = { ...detail, evidence: [{ ...detail.evidence[0], source_url: "javascript:alert(1)" }] }
  renderDialog(["leads.read"], vi.fn(async () => json(unsafe)))
  await screen.findByText("We need replacement helical gears, 200 pcs.")
  expect(screen.queryByRole("link", { name: "打开公开来源" })).not.toBeInTheDocument()
  expect(screen.getByText("公开来源链接不可用")).toBeVisible()
})

it("treats the refined latest insight type as nullable", async () => {
  const pending = {
    ...detail,
    status: "DISCOVERED",
    latest_insight: null,
    requirements: [],
    permitted_actions: ["ANALYZE"],
  }
  renderDialog(["leads.read", "leads.analyze"], vi.fn(async () => json(pending)))
  expect(await screen.findByText("等待判断")).toBeVisible()
  expect(screen.getByText("等待分析证据")).toBeVisible()
  expect(screen.getByText("AI 尚未给出可展示的判断说明。")).toBeVisible()
  expect(screen.getByRole("button", { name: "重新分析" })).toBeVisible()
})

it("gates analyze, review, and handoff controls independently", async () => {
  const readOnly = renderDialog(["leads.read"])
  await screen.findByText("人工决定")
  expect(screen.queryByRole("button", { name: "重新分析" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "确认值得跟进" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "交给 CRM" })).not.toBeInTheDocument()
  readOnly.unmount()

  const analyze = renderDialog(["leads.read", "leads.analyze"])
  expect(await screen.findByRole("button", { name: "重新分析" })).toBeVisible()
  expect(screen.queryByRole("button", { name: "确认值得跟进" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "交给 CRM" })).not.toBeInTheDocument()
  analyze.unmount()

  const review = renderDialog(["leads.read", "leads.review"])
  expect(await screen.findByRole("button", { name: "确认值得跟进" })).toBeVisible()
  expect(screen.queryByRole("button", { name: "重新分析" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "交给 CRM" })).not.toBeInTheDocument()
  review.unmount()

  const reviewedDetail = {
    ...detail,
    status: "REVIEWED",
    permitted_actions: ["DISMISS", "REQUEST_MORE_EVIDENCE"],
  }
  renderDialog(["leads.read", "leads.handoff"], vi.fn(async () => json(reviewedDetail)))
  expect(await screen.findByRole("button", { name: "交给 CRM" })).toBeEnabled()
  await userEvent.click(screen.getByRole("button", { name: "交给 CRM" }))
  expect(screen.getByText("CRM 尚未配置，当前不会发送客户资料。")).toBeVisible()
  expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining("handoff"), expect.anything())
})

it("keeps CRM export inside the detail modal and restores its trigger on Escape and close", async () => {
  const reviewedDetail = {
    ...detail,
    status: "REVIEWED",
    permitted_actions: ["DISMISS", "REQUEST_MORE_EVIDENCE"],
  }
  renderDialog(["leads.read", "leads.handoff"], vi.fn(async () => json(reviewedDetail)))
  const opener = await screen.findByRole("button", { name: "交给 CRM" })

  await userEvent.click(opener)

  expect(screen.getAllByRole("dialog")).toHaveLength(1)
  expect(screen.getByRole("heading", { name: "CRM 与导出" })).toHaveFocus()
  expect(screen.queryByText("We need replacement helical gears, 200 pcs.")).not.toBeInTheDocument()
  await userEvent.tab()
  expect(screen.getByRole("button", { name: "返回机会依据" })).toHaveFocus()

  await userEvent.keyboard("{Escape}")
  expect(screen.getAllByRole("dialog")).toHaveLength(1)
  expect(await screen.findByText("We need replacement helical gears, 200 pcs.")).toBeVisible()
  expect(screen.getByRole("button", { name: "交给 CRM" })).toHaveFocus()

  await userEvent.click(screen.getByRole("button", { name: "交给 CRM" }))
  await userEvent.click(screen.getByRole("button", { name: "关闭" }))
  expect(screen.getAllByRole("dialog")).toHaveLength(1)
  expect(screen.getByRole("button", { name: "交给 CRM" })).toHaveFocus()
})

it.each(["permission", "organization"] as const)(
  "returns focus to the safe detail title when the CRM view closes after a %s change",
  async (change) => {
    const reviewedDetail = {
      ...detail,
      status: "REVIEWED",
      permitted_actions: ["DISMISS", "REQUEST_MORE_EVIDENCE"],
    }
    const view = renderDialog(["leads.read", "leads.handoff"], vi.fn(async () => json(reviewedDetail)))
    await userEvent.click(await screen.findByRole("button", { name: "交给 CRM" }))
    expect(screen.getByRole("heading", { name: "CRM 与导出" })).toHaveFocus()

    if (change === "permission") {
      view.queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(["leads.read"]))
    } else {
      await view.rerender({ organizationId: "org-2" })
    }

    await waitFor(() => expect(screen.getByRole("heading", { name: "机会依据" })).toHaveFocus())
    expect(screen.queryByRole("button", { name: "返回机会依据" })).not.toBeInTheDocument()
  },
)

it("removes cached evidence and audit immediately when read permission is withdrawn", async () => {
  const view = renderDialog()
  await screen.findByText("We need replacement helical gears, 200 pcs.")
  const cancellations = vi.spyOn(view.queryClient, "cancelQueries")

  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(["leads.analyze", "leads.review"]))

  await waitFor(() => expect(screen.queryByText("We need replacement helical gears, 200 pcs.")).not.toBeInTheDocument())
  expect(screen.queryByText("高级审计信息")).not.toBeInTheDocument()
  expect(screen.getByText("当前账号不能查看机会依据")).toBeVisible()
  expect(cancellations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "detail", "lead-1"], exact: true })
  expect(cancellations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "job"] })
})

it("keeps typed review input visible but disables it when review permission is withdrawn", async () => {
  const view = renderDialog(["leads.read", "leads.review"])
  await userEvent.click(await screen.findByRole("button", { name: "确认值得跟进" }))
  await userEvent.type(screen.getByLabelText("处理原因"), "Keep this draft visible.")

  view.queryClient.setQueryData(currentUserQueryOptions().queryKey, userWith(["leads.read"]))

  expect(await screen.findByText("审核权限已撤销，当前处理内容不会提交。")).toBeVisible()
  expect(screen.getByLabelText("处理原因")).toHaveValue("Keep this draft visible.")
  expect(screen.getByRole("button", { name: "确认值得跟进" })).toBeDisabled()
})

it("shows unavailable evidence honestly and analyzes only usable evidence IDs", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const mixed = {
    ...detail,
    evidence: [
      detail.evidence[0],
      {
        ...detail.evidence[0], id: "evidence-unavailable", availability: "SOURCE_UNAVAILABLE",
        original_text: "This unavailable text must not be quoted.", source_url: "https://example.test/unavailable",
      },
    ],
  }
  const bodies: Array<Record<string, unknown>> = []
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/analyze")) {
      bodies.push(JSON.parse(options?.body as string) as Record<string, unknown>)
      return json({ job_id: "job-1", lead_candidate_id: "lead-1", status: "QUEUED" }, 202)
    }
    if (path === "/api/v1/jobs/job-1") return json({
      job_id: "job-1", status: "SUCCEEDED", type: "LEAD_ANALYZE", progress: 100, attempt: 1,
      max_attempts: 3, created_at: "2026-08-11T00:00:00Z", finished_at: "2026-08-11T00:01:00Z",
      error: null, result_reference: null,
    })
    return json(mixed)
  })
  renderDialog(["leads.read", "leads.analyze"], fetchMock)

  expect(await screen.findByText("公开来源当前不可用")).toBeVisible()
  expect(screen.queryByText("This unavailable text must not be quoted.")).not.toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "打开不可用来源" })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "重新分析" }))
  await screen.findByText("分析已完成")
  expect(bodies[0]?.evidence_ids).toEqual(["evidence-1"])
})

it("shows a safe terminal analysis recovery without raw server detail", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn(async (path: string) => {
    if (path.endsWith("/analyze")) {
      return json({ job_id: "job-terminal", lead_candidate_id: "lead-1", status: "QUEUED" }, 202)
    }
    if (path === "/api/v1/jobs/job-terminal") return json({
      job_id: "job-terminal", status: "FAILED", type: "LEAD_ANALYZE", progress: 50,
      attempt: 1, max_attempts: 3, created_at: "2026-08-12T06:00:00Z", finished_at: "2026-08-12T06:01:00Z",
      retry_count: 2, next_retry_at: null,
      error: { code: "deepseek_retry_exhausted", message: "raw provider V4 Pro model secret" },
      result_reference: null,
    })
    return json(detail)
  })
  renderDialog(["leads.read", "leads.analyze"], fetchMock)

  await userEvent.click(await screen.findByRole("button", { name: "重新分析" }))

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("多次尝试后仍未完成，系统已停止自动重试。")
  expect(alert).toHaveTextContent("请稍后手动重试；仍有问题请联系管理员。")
  expect(alert).not.toHaveTextContent(/V4|Flash|Pro|模型|raw provider/)
})

it.each([
  ["REDACTED_BY_RETENTION", "内容已按保留期限移除"],
  ["SOURCE_UNAVAILABLE", "公开来源当前不可用"],
] as const)("disables analysis when all evidence is %s", async (availability, statusCopy) => {
  const unusable = {
    ...detail,
    evidence: [{
      ...detail.evidence[0], availability, original_text: "", translated_text: "",
      source_url: "https://example.test/removed",
    }],
  }
  renderDialog(["leads.read", "leads.analyze"], vi.fn(async () => json(unusable)))

  expect(await screen.findByText(statusCopy)).toBeVisible()
  expect(screen.queryByRole("link", { name: "打开公开来源" })).not.toBeInTheDocument()
  expect(screen.getByText("没有可用于分析的公开证据。请先补充仍可访问的公开原文。")).toBeVisible()
  expect(screen.getByRole("button", { name: "重新分析" })).toBeDisabled()
})

it("submits only backend-supported correction fields with the exact version and reason", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const requests: Array<Record<string, unknown>> = []
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/lead-reviews") {
      requests.push(JSON.parse(options?.body as string) as Record<string, unknown>)
      return json({
        review_id: "review-1", lead_candidate_id: "lead-1", candidate_status: "REVIEWED",
        candidate_version: 3, insight_id: "insight-2", insight_version: 2,
      }, 201)
    }
    return json(detail)
  })
  renderDialog(["leads.read", "leads.review"], fetchMock)

  await userEvent.click(await screen.findByRole("button", { name: "纠正信息" }))
  await userEvent.clear(screen.getByLabelText("公司名称"))
  await userEvent.type(screen.getByLabelText("公司名称"), "Corrected Company")
  await userEvent.clear(screen.getByLabelText("公开域名"))
  await userEvent.type(screen.getByLabelText("公开域名"), "corrected.example")
  await userEvent.clear(screen.getByLabelText("国家或地区"))
  await userEvent.type(screen.getByLabelText("国家或地区"), "US")
  await userEvent.type(screen.getByLabelText("处理原因"), "Public company page confirms these fields.")
  await userEvent.click(screen.getByRole("button", { name: "确认纠正" }))

  await screen.findByText("处理结果已保存")
  expect(requests).toHaveLength(1)
  expect(requests[0]).toEqual({
    action: "CORRECT",
    candidate_id: "lead-1",
    correction: { company_name: "Corrected Company", company_domain: "corrected.example", country_hint: "US" },
    expected_version: 2,
    idempotency_key: expect.any(String),
    reason: "Public company page confirms these fields.",
  })
  expect(Object.keys(requests[0]?.correction as object)).toEqual(["company_name", "company_domain", "country_hint"])
})

it.each([
  {
    action: "CONFIRM", opener: "确认值得跟进", submit: "确认值得跟进",
    initial: detail, nextStatus: "REVIEWED", nextActions: ["DISMISS"], expectedFocus: "暂不跟进",
  },
  {
    action: "CORRECT", opener: "纠正信息", submit: "确认纠正",
    initial: detail, nextStatus: "REVIEWED", nextActions: ["DISMISS"], expectedFocus: "暂不跟进",
  },
  {
    action: "DISMISS", opener: "暂不跟进", submit: "确认暂不跟进",
    initial: detail, nextStatus: "DISMISSED", nextActions: ["REOPEN"], expectedFocus: "重新打开",
  },
  {
    action: "REOPEN", opener: "重新打开", submit: "确认重新打开",
    initial: { ...detail, status: "DISMISSED", permitted_actions: ["REOPEN"] },
    nextStatus: "ANALYZED", nextActions: ["CONFIRM"], expectedFocus: "确认值得跟进",
  },
] as const)("restores stable focus after a successful $action state change", async ({
  opener, submit, initial, nextStatus, nextActions, expectedFocus,
}) => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let detailReads = 0
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/lead-reviews") {
      return json({
        review_id: "review-focus", lead_candidate_id: "lead-1", candidate_status: nextStatus,
        candidate_version: 3, insight_id: null, insight_version: null,
      }, 201)
    }
    detailReads += 1
    return json(detailReads === 1 ? initial : {
      ...initial,
      status: nextStatus,
      version: 3,
      permitted_actions: nextActions,
    })
  })
  renderDialog(["leads.read", "leads.review"], fetchMock)

  await userEvent.click(await screen.findByRole("button", { name: opener }))
  if (opener === "纠正信息") {
    await userEvent.clear(screen.getByLabelText("公司名称"))
    await userEvent.type(screen.getByLabelText("公司名称"), "Corrected focus company")
  }
  await userEvent.type(screen.getByLabelText("处理原因"), `Focus recovery for ${opener}.`)
  await userEvent.click(screen.getByRole("button", { name: submit }))

  await screen.findByText("处理结果已保存")
  await waitFor(() => expect(screen.getByRole("button", { name: expectedFocus })).toHaveFocus())
})

it("preserves typed review input on 409, refetches, and resubmits against the latest version", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const reviewBodies: Array<Record<string, unknown>> = []
  let detailReads = 0
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/lead-reviews") {
      reviewBodies.push(JSON.parse(options?.body as string) as Record<string, unknown>)
      if (reviewBodies.length === 1) {
        return json({
          code: "version_conflict", message: "stale", recovery_action: "reload", current_version: 3,
        }, 409)
      }
      return json({
        review_id: "review-2", lead_candidate_id: "lead-1", candidate_status: "REVIEWED",
        candidate_version: 4, insight_id: "insight-2", insight_version: 2,
      }, 201)
    }
    detailReads += 1
    return json(detailReads === 1 ? detail : {
      ...detail,
      version: 3,
      company: { ...detail.company, domain: "coworker.example" },
    })
  })
  renderDialog(["leads.read", "leads.review"], fetchMock)

  await userEvent.click(await screen.findByRole("button", { name: "纠正信息" }))
  await userEvent.clear(screen.getByLabelText("公司名称"))
  await userEvent.type(screen.getByLabelText("公司名称"), "Conflict-safe Company")
  await userEvent.type(screen.getByLabelText("处理原因"), "Keep this exact typed reason.")
  await userEvent.click(screen.getByRole("button", { name: "确认纠正" }))

  expect(await screen.findByText("另一位同事刚刚保存了处理结果")).toBeVisible()
  expect(screen.getByLabelText("公司名称")).toHaveValue("Conflict-safe Company")
  expect(screen.getByLabelText("处理原因")).toHaveValue("Keep this exact typed reason.")
  expect(detailReads).toBe(2)
  await userEvent.click(screen.getByRole("button", { name: "按最新版本重新提交" }))
  await screen.findByText("处理结果已保存")

  expect(reviewBodies).toHaveLength(2)
  expect(reviewBodies.map((body) => body.expected_version)).toEqual([2, 3])
  expect(reviewBodies.map((body) => body.reason)).toEqual([
    "Keep this exact typed reason.", "Keep this exact typed reason.",
  ])
  expect(reviewBodies[1]?.correction).toEqual({ company_name: "Conflict-safe Company" })
  expect(reviewBodies[1]?.correction).toEqual(reviewBodies[0]?.correction)
  expect(reviewBodies[1]?.idempotency_key).not.toBe(reviewBodies[0]?.idempotency_key)
})

it("preserves a stale review draft but blocks retry when refreshed actions remove it", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let detailReads = 0
  let reviews = 0
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/lead-reviews") {
      reviews += 1
      return json({ code: "version_conflict", message: "stale", recovery_action: "reload" }, 409)
    }
    detailReads += 1
    return json(detailReads === 1 ? detail : {
      ...detail, version: 3, status: "REVIEWED", permitted_actions: ["DISMISS", "REQUEST_MORE_EVIDENCE"],
    })
  })
  renderDialog(["leads.read", "leads.review"], fetchMock)
  await userEvent.click(await screen.findByRole("button", { name: "确认值得跟进" }))
  await userEvent.type(screen.getByLabelText("处理原因"), "Preserve this decision draft.")
  await userEvent.click(screen.getByRole("button", { name: "确认值得跟进" }))

  expect(await screen.findByText("最新状态不再允许“确认值得跟进”，请保留原因并取消后重新选择。")).toBeVisible()
  expect(screen.getByLabelText("处理原因")).toHaveValue("Preserve this decision draft.")
  expect(screen.getByRole("button", { name: "按最新版本重新提交" })).toBeDisabled()
  await userEvent.click(screen.getByRole("button", { name: "按最新版本重新提交" }))
  expect(reviews).toBe(1)
})

it("keeps a review draft but does not arm retry when the version-conflict refetch fails", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let detailReads = 0
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/lead-reviews") {
      return json({ code: "version_conflict", message: "stale", recovery_action: "reload" }, 409)
    }
    detailReads += 1
    return detailReads === 1 ? json(detail) : json({ detail: "private failure" }, 500)
  })
  renderDialog(["leads.read", "leads.review"], fetchMock)
  await userEvent.click(await screen.findByRole("button", { name: "确认值得跟进" }))
  await userEvent.type(screen.getByLabelText("处理原因"), "Keep this after refetch failure.")
  await userEvent.click(screen.getByRole("button", { name: "确认值得跟进" }))

  expect(await screen.findByText("最新机会版本没有加载成功，请重新加载后再提交。")).toBeVisible()
  expect(screen.getByLabelText("处理原因")).toHaveValue("Keep this after refetch failure.")
  expect(screen.queryByText("另一位同事刚刚保存了处理结果")).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "按最新版本重新提交" })).toBeDisabled()
})

it.each([
  ["idempotency_conflict", "幂等键已绑定其他处理。", "修改处理内容后重新提交。"],
  ["lead_state_conflict", "当前机会状态不允许该处理。", "重新加载机会后选择可用操作。"],
] as const)("blocks review retry for %s and shows its recovery", async (code, conflictMessage, recovery) => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let detailReads = 0
  const fetchMock = vi.fn(async (path: string) => {
    if (path === "/api/v1/lead-reviews") return json({ code, message: conflictMessage, recovery_action: recovery }, 409)
    detailReads += 1
    return json(detail)
  })
  renderDialog(["leads.read", "leads.review"], fetchMock)
  await userEvent.click(await screen.findByRole("button", { name: "确认值得跟进" }))
  await userEvent.type(screen.getByLabelText("处理原因"), "Retain classified conflict input.")
  await userEvent.click(screen.getByRole("button", { name: "确认值得跟进" }))

  expect(await screen.findByText(`${conflictMessage} ${recovery}`)).toBeVisible()
  expect(screen.getByLabelText("处理原因")).toHaveValue("Retain classified conflict input.")
  expect(screen.queryByRole("button", { name: "按最新版本重新提交" })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "确认值得跟进" })).toBeDisabled()
  expect(detailReads).toBe(1)
})

it("recovers an analysis conflict against the refreshed version and follows the accepted job", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const analyzeBodies: Array<Record<string, unknown>> = []
  let detailReads = 0
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/lead-candidates/lead-1/analyze") {
      analyzeBodies.push(JSON.parse(options?.body as string) as Record<string, unknown>)
      if (analyzeBodies.length === 1) {
        return json({ code: "version_conflict", message: "stale", recovery_action: "reload", current_version: 3 }, 409)
      }
      return json({ job_id: "job-1", lead_candidate_id: "lead-1", status: "QUEUED" }, 202)
    }
    if (path === "/api/v1/jobs/job-1") {
      return json({
        job_id: "job-1", status: "SUCCEEDED", type: "LEAD_ANALYZE", progress: 100,
        attempt: 1, max_attempts: 3, created_at: "2026-08-11T00:00:00Z",
        finished_at: "2026-08-11T00:01:00Z", error: null, result_reference: null,
      })
    }
    detailReads += 1
    return json({ ...detail, version: detailReads === 1 ? 2 : 3 })
  })
  renderDialog(["leads.read", "leads.analyze"], fetchMock)

  await userEvent.click(await screen.findByRole("button", { name: "重新分析" }))
  expect(await screen.findByText("另一位同事刚刚保存了处理结果")).toBeVisible()
  await userEvent.click(screen.getByRole("button", { name: "按最新版本重新提交" }))
  expect(await screen.findByText("分析已完成")).toBeVisible()

  expect(analyzeBodies.map((body) => body.expected_version)).toEqual([2, 3])
  expect(analyzeBodies.map((body) => body.evidence_ids)).toEqual([["evidence-1"], ["evidence-1"]])
  expect(analyzeBodies[1]?.idempotency_key).not.toBe(analyzeBodies[0]?.idempotency_key)
})

it("does not arm analysis retry when the version-conflict refetch fails", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let detailReads = 0
  const fetchMock = vi.fn(async (path: string) => {
    if (path.endsWith("/analyze")) return json({ code: "version_conflict", message: "stale", recovery_action: "reload" }, 409)
    detailReads += 1
    return detailReads === 1 ? json(detail) : json({ detail: "private failure" }, 500)
  })
  renderDialog(["leads.read", "leads.analyze"], fetchMock)
  await userEvent.click(await screen.findByRole("button", { name: "重新分析" }))

  expect(await screen.findByText("最新机会版本没有加载成功，请重新加载后再分析。")).toBeVisible()
  expect(screen.queryByText("另一位同事刚刚保存了处理结果")).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "按最新版本重新提交" })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "重新分析" })).toBeDisabled()
})

it.each([
  ["idempotency_conflict", "分析键已绑定其他请求。", "修改分析范围后重试。"],
  ["lead_state_conflict", "当前机会状态不能分析。", "重新加载机会后重试。"],
] as const)("blocks analysis retry for %s and shows its recovery", async (code, conflictMessage, recovery) => {
  document.cookie = "csrftoken=csrf-value; path=/"
  let detailReads = 0
  const fetchMock = vi.fn(async (path: string) => {
    if (path.endsWith("/analyze")) return json({ code, message: conflictMessage, recovery_action: recovery }, 409)
    detailReads += 1
    return json(detail)
  })
  renderDialog(["leads.read", "leads.analyze"], fetchMock)
  await userEvent.click(await screen.findByRole("button", { name: "重新分析" }))

  expect(await screen.findByText(`${conflictMessage} ${recovery}`)).toBeVisible()
  expect(screen.queryByRole("button", { name: "按最新版本重新提交" })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "重新分析" })).toBeDisabled()
  expect(detailReads).toBe(1)
})

it("invalidates the organization queue, detail, and job scopes after a review", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn(async (path: string) => path === "/api/v1/lead-reviews"
    ? json({
      review_id: "review-1", lead_candidate_id: "lead-1", candidate_status: "REVIEWED",
      candidate_version: 3, insight_id: null, insight_version: null,
    }, 201)
    : json(detail))
  const view = renderDialog(["leads.read", "leads.review"], fetchMock)
  const invalidations = vi.spyOn(view.queryClient, "invalidateQueries")

  await userEvent.click(await screen.findByRole("button", { name: "确认值得跟进" }))
  await userEvent.type(screen.getByLabelText("处理原因"), "Evidence is sufficient.")
  await userEvent.click(screen.getByRole("button", { name: "确认值得跟进" }))
  await screen.findByText("处理结果已保存")

  expect(invalidations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "list"] })
  expect(invalidations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "detail", "lead-1"] })
  expect(invalidations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "job"] })
})

it.each(["close", "candidate", "organization"] as const)(
  "invalidates the captured review scopes after a late accepted mutation on %s",
  async (transition) => {
    document.cookie = "csrftoken=csrf-value; path=/"
    const reviewResponse = deferred<Response>()
    const fetchMock = vi.fn((path: string) => {
      if (path === "/api/v1/lead-reviews") return reviewResponse.promise
      if (path.endsWith("/lead-2")) {
        return Promise.resolve(json({ ...detail, id: "lead-2", company: { ...detail.company, name: "New Candidate" } }))
      }
      return Promise.resolve(json(detail))
    })
    const view = renderDialog(["leads.read", "leads.review"], fetchMock)
    const invalidations = vi.spyOn(view.queryClient, "invalidateQueries")
    await userEvent.click(await screen.findByRole("button", { name: "确认值得跟进" }))
    await userEvent.type(screen.getByLabelText("处理原因"), "Late server-side review.")
    await userEvent.click(screen.getByRole("button", { name: "确认值得跟进" }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/lead-reviews", expect.anything()))

    if (transition === "close") await view.rerender({ organizationId: "org-1", candidateId: "lead-1", open: false })
    else if (transition === "candidate") await view.rerender({ organizationId: "org-1", candidateId: "lead-2", open: true })
    else await view.rerender({ organizationId: "org-2", candidateId: "lead-2", open: true })

    reviewResponse.resolve(json({
      review_id: "review-late", lead_candidate_id: "lead-1", candidate_status: "REVIEWED",
      candidate_version: 3, insight_id: null, insight_version: null,
    }, 201))

    await waitFor(() => {
      expect(invalidations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "list"] })
      expect(invalidations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "detail", "lead-1"] })
      expect(invalidations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "job"] })
    })
    expect(screen.queryByText("处理结果已保存")).not.toBeInTheDocument()
    if (transition !== "close") expect(await screen.findByText("New Candidate")).toBeVisible()
  },
)

it.each(["close", "candidate", "organization"] as const)(
  "invalidates captured analysis scopes without polling after a late acceptance on %s",
  async (transition) => {
    document.cookie = "csrftoken=csrf-value; path=/"
    const analyzeResponse = deferred<Response>()
    const fetchMock = vi.fn((path: string) => {
      if (path.endsWith("/analyze")) return analyzeResponse.promise
      if (path.endsWith("/lead-2")) {
        return Promise.resolve(json({ ...detail, id: "lead-2", company: { ...detail.company, name: "New Candidate" } }))
      }
      return Promise.resolve(json(detail))
    })
    const view = renderDialog(["leads.read", "leads.analyze"], fetchMock)
    const invalidations = vi.spyOn(view.queryClient, "invalidateQueries")
    await userEvent.click(await screen.findByRole("button", { name: "重新分析" }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/lead-candidates/lead-1/analyze", expect.anything(),
    ))

    if (transition === "close") await view.rerender({ organizationId: "org-1", candidateId: "lead-1", open: false })
    else if (transition === "candidate") await view.rerender({ organizationId: "org-1", candidateId: "lead-2", open: true })
    else await view.rerender({ organizationId: "org-2", candidateId: "lead-2", open: true })

    analyzeResponse.resolve(json({ job_id: "job-late", lead_candidate_id: "lead-1", status: "QUEUED" }, 202))

    await waitFor(() => {
      expect(invalidations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "list"] })
      expect(invalidations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "detail", "lead-1"] })
      expect(invalidations).toHaveBeenCalledWith({ queryKey: ["leads", "org-1", "job"] })
    })
    expect(fetchMock.mock.calls.some(([path]) => path === "/api/v1/jobs/job-late")).toBe(false)
    expect(screen.queryByText("分析已完成")).not.toBeInTheDocument()
    if (transition !== "close") expect(await screen.findByText("New Candidate")).toBeVisible()
  },
)

it("shows every review reason and correction in the collapsed audit history", async () => {
  const history = {
    ...detail,
    review_history: [
      { id: "review-1", action: "CORRECT", reason: "Corrected identity.", correction: { company_name: "ABC Packaging GmbH" }, reviewer: 2, insight_id: "insight-2", candidate_status: "REVIEWED", candidate_version: 3, created_at: "2026-08-10T02:00:00Z" },
      { id: "review-2", action: "REQUEST_MORE_EVIDENCE", reason: "Need a public capability page.", correction: null, reviewer: 3, insight_id: "insight-2", candidate_status: "REVIEWED", candidate_version: 4, created_at: "2026-08-10T03:00:00Z" },
    ],
  }
  renderDialog(["leads.read", "credentials.manage"], vi.fn(async () => json(history)))
  const audit = (await screen.findByText("高级审计信息")).closest("details")!
  await userEvent.click(within(audit).getByText("高级审计信息"))
  expect(within(audit).getByText("Corrected identity.")).toBeVisible()
  expect(within(audit).getByText("Need a public capability page.")).toBeVisible()
  expect(within(audit).getByText(/ABC Packaging GmbH/)).toBeVisible()
})

it("localizes audit keys without hiding their recorded values", async () => {
  const auditDetail = {
    ...detail,
    latest_insight: {
      ...detail.latest_insight,
      dimensions: { ...detail.latest_insight.dimensions, unknown_metric: 7 },
      ai_audit: {
        ...detail.latest_insight.ai_audit,
        unknown_private_key: "opaque-value",
        nested_record: { private_nested_key: "nested-value" },
      },
    },
  }
  renderDialog(["leads.read", "credentials.manage"], vi.fn(async () => json(auditDetail)))
  const audit = (await screen.findByText("高级审计信息")).closest("details")!
  await userEvent.click(within(audit).getByText("高级审计信息"))

  for (const label of ["购买意向", "公司匹配", "需求明确度", "能力匹配", "时效性", "其他指标"]) {
    expect(within(audit).getByText(label)).toBeVisible()
  }
  for (const label of ["分析记录编号", "运行状态", "分析模板", "模板版本", "分析模型", "未识别字段 1"]) {
    expect(within(audit).getByText(new RegExp(label))).toBeVisible()
  }
  expect(audit).toHaveTextContent("run-1")
  expect(audit).toHaveTextContent("opaque-value")
  expect(audit).toHaveTextContent("nested-value")
  expect(audit).not.toHaveTextContent(/intent|company_fit|specificity|capability_fit|recency|unknown_metric/)
  expect(audit).not.toHaveTextContent(/ai_run_id|prompt_code|prompt_version|unknown_private_key|private_nested_key/)
})

it("cancels an obsolete detail request and ignores its late result", async () => {
  let resolveOld!: (response: Response) => void
  const oldRequest = new Promise<Response>((resolve) => { resolveOld = resolve })
  let oldSignal: AbortSignal | undefined
  const fetchMock = vi.fn((path: string, options?: RequestInit) => {
    if (path.endsWith("/lead-1")) {
      oldSignal = options?.signal as AbortSignal | undefined
      return oldRequest
    }
    return Promise.resolve(json({ ...detail, id: "lead-2", company: { ...detail.company, name: "New Candidate" } }))
  })
  const view = renderDialog(["leads.read"], fetchMock)
  await waitFor(() => expect(oldSignal).toBeDefined())
  await view.rerender({ organizationId: "org-1", candidateId: "lead-2", open: true })
  expect(await screen.findByText("New Candidate")).toBeVisible()
  expect(oldSignal?.aborted).toBe(true)
  resolveOld(json({ ...detail, company: { ...detail.company, name: "Obsolete Candidate" } }))
  await new Promise((resolve) => { setTimeout(resolve, 0) })
  expect(screen.queryByText("Obsolete Candidate")).not.toBeInTheDocument()
})
