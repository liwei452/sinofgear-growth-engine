import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import OpportunityWorkspacePage from "./OpportunityWorkspacePage.vue"

afterEach(() => vi.unstubAllGlobals())

const candidate = {
  id: "acct-1", company_name: "Atlas Gear Works", country: "Vietnam", website: "https://atlas.example",
  industry: "Industrial machinery", status: "PENDING_REVIEW", status_label: "待人工审核",
  source_owner: "Licensed directory", license_contract: "Internal evaluation", import_format: "CSV",
  is_demo: false, score: 82, grade: "A", intent_score: 76,
  intent_breakdown: { procurement: 76 }, created_at: "2026-08-19T08:00:00Z",
}

async function renderPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/opportunities", component: OpportunityWorkspacePage }],
  })
  await router.push("/opportunities?q=gear&stage=ALL&sort=score")
  return { router, ...render(OpportunityWorkspacePage, {
    global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }], router] },
  }) }
}

it("keeps the selected opportunity in the URL and shows evidence with only public contact paths", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (String(input) === "/api/v1/growth/discovery/profile") {
      return new Response(JSON.stringify({
        enabled: true, source_label: "Licensed directory", schedule_label: "Manual", product_scope_label: "Gear",
        next_run_at: null, last_run: null, candidate_count: 1, candidates: [candidate], enrichment_candidates: [], available_sources: [],
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${String(input)}`)
  }))
  const user = userEvent.setup()
  const { router } = await renderPage()

  expect(await screen.findByRole("searchbox", { name: "搜索客户机会" })).toBeInTheDocument()
  expect(await screen.findByRole("list", { name: "客户机会列表" })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "查看 Atlas Gear Works 的证据" }))
  expect(router.currentRoute.value.query.selected).toBe("acct-1")
  expect(screen.getByRole("region", { name: "客户机会详情" })).toHaveTextContent("推荐原因")
  expect(screen.getByRole("region", { name: "客户机会详情" })).toHaveTextContent("公开联系路径")
  expect(screen.getByRole("region", { name: "客户机会详情" })).toHaveTextContent("尚未补全公开联系路径")
})

it("reports a failed candidate feed instead of inventing opportunities", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("forbidden", { status: 403 })))
  await renderPage()
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取客户机会")
})

it("imports a supplied candidate list for human review without claiming it was scraped", async () => {
  document.cookie = "csrftoken=opportunity-test-token; path=/"
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/v1/growth/discovery/profile") return new Response(JSON.stringify({
      enabled: true, source_label: "Licensed directory", schedule_label: "Manual", product_scope_label: "Gear",
      next_run_at: null, last_run: null, candidate_count: 0, candidates: [], enrichment_candidates: [], available_sources: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (String(input) === "/api/v1/growth/discovery/candidate-imports" && init?.method === "POST") return new Response(JSON.stringify({
      created_count: 1, duplicate_count: 0, invalid_count: 0, errors: [], queue_label: "待人工审核候选公司",
    }), { status: 200, headers: { "Content-Type": "application/json" } })
    throw new Error(`Unexpected request: ${String(input)}`)
  }))
  const user = userEvent.setup()
  await renderPage()
  await user.click(await screen.findByRole("button", { name: "导入候选名单" }))
  await user.type(screen.getByRole("textbox", { name: "候选名单内容" }), "company_name,country\nAtlas Gear Works,Vietnam")
  await user.click(screen.getByRole("button", { name: "导入并进入人工审核" }))
  expect(await screen.findByText("已导入 1 条候选公司，等待人工审核。", { exact: true })).toBeInTheDocument()
})

it("keeps an accepted candidate visible in the enrichment stage after refetch", async () => {
  document.cookie = "csrftoken=opportunity-review-token; path=/"
  let accepted = false
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/v1/growth/discovery/profile") return new Response(JSON.stringify({
      enabled: true, source_label: "Licensed directory", schedule_label: "Manual", product_scope_label: "Gear",
      next_run_at: null, last_run: null, candidate_count: accepted ? 0 : 1,
      candidates: accepted ? [] : [candidate],
      enrichment_candidates: accepted ? [{ ...candidate, status: "ACCEPTED", status_label: "待资料补全", latest_preview: null, workflow: { account_id: null, follow_up_status: null, draft: null } }] : [],
      available_sources: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (String(input).endsWith("/review") && init?.method === "POST") {
      accepted = true
      return new Response(JSON.stringify({ id: candidate.id, status: "ACCEPTED", status_label: "待资料补全", message: "已接受" }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${String(input)}`)
  }))
  const user = userEvent.setup()
  await renderPage()
  await user.click(await screen.findByRole("button", { name: "查看 Atlas Gear Works 的证据" }))
  await user.click(screen.getByRole("button", { name: "人工接受候选" }))
  expect(await screen.findByRole("button", { name: "准备资料补全" })).toBeInTheDocument()
})

it("allows fact preparation but blocks a pending list licence before follow-up or contact drafting", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    enabled: true, source_label: "Manual import", schedule_label: "Manual", product_scope_label: "Gear",
    next_run_at: null, last_run: null, candidate_count: 0, candidates: [],
    enrichment_candidates: [{
      ...candidate,
      status: "ACCEPTED",
      status_label: "待确认名单许可",
      license_contract: "待人工确认使用范围",
      latest_preview: null,
      workflow: { account_id: null, follow_up_status: null, draft: null },
    }],
    available_sources: [],
  }), { status: 200, headers: { "Content-Type": "application/json" } })))
  const user = userEvent.setup()
  await renderPage()

  await user.click(await screen.findByRole("button", { name: "查看 Atlas Gear Works 的证据" }))

  expect(screen.getByText("候选名单的使用许可尚待人工确认，暂不能加入跟进或生成联系草稿。", { exact: true })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "准备资料补全" })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "加入跟进" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "生成联系草稿" })).not.toBeInTheDocument()
})

it("continues a confirmed-license candidate through follow-up and an unsent contact draft without expanding the profile API", async () => {
  document.cookie = "csrftoken=opportunity-draft-token; path=/"
  const requests: string[] = []
  let followedUp = false
  let drafted = false
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    requests.push(`${init?.method ?? "GET"} ${path}`)
    if (path === "/api/v1/growth/discovery/profile") return new Response(JSON.stringify({ enabled: true, source_label: "Licensed directory", schedule_label: "Manual", product_scope_label: "Gear", next_run_at: null, last_run: null, candidate_count: 0, candidates: [], enrichment_candidates: [{ ...candidate, status: "ACCEPTED", latest_preview: { candidate_id: candidate.id, mode: "IMPORTED_FACTS_REVIEW", data_label: "Imported", facts: [], public_contact_paths: [], uncertainties: [], message: "Prepared", created: false }, workflow: { account_id: followedUp ? "account-atlas" : null, follow_up_status: followedUp ? "OPEN" : null, draft: drafted ? { status: "DRAFT", delivery: "NEVER_SENT", message_id: null, sent_at: null } : null } }], available_sources: [] }), { status: 200, headers: { "Content-Type": "application/json" } })
    if (path.endsWith(`/candidates/${candidate.id}/follow-up`) && init?.method === "POST") { followedUp = true; return new Response(JSON.stringify({ account_id: "account-atlas", follow_up_id: "follow-up-atlas", status: "OPEN", created: true, message: "已加入人工跟进" }), { status: 201, headers: { "Content-Type": "application/json" } }) }
    if (path === "/api/v1/growth/opportunities/account-atlas/draft" && init?.method === "POST") { drafted = true; return new Response(JSON.stringify({ id: "draft-atlas", status: "DRAFT", delivery: "NEVER_SENT", "English draft": "Hello", "Chinese explanation": "草稿" }), { status: 200, headers: { "Content-Type": "application/json" } }) }
    throw new Error(`Unexpected request: ${path}`)
  }))
  const user = userEvent.setup()
  await renderPage()
  await user.click(await screen.findByRole("button", { name: "查看 Atlas Gear Works 的证据" }))
  await user.click(screen.getByRole("button", { name: "加入跟进" }))
  expect(await screen.findByText("已加入跟进（OPEN），尚未外发联系。", { exact: true })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "生成联系草稿" }))
  expect(await screen.findByText("已生成联系草稿（DRAFT），状态为未发送。", { exact: true })).toBeInTheDocument()
  expect(requests).toContain(`POST /api/v1/growth/enrichment/candidates/${candidate.id}/follow-up`)
  expect(requests).toContain("POST /api/v1/growth/opportunities/account-atlas/draft")
})
