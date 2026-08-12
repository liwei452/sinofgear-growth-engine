import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { defineComponent, h } from "vue"
import { createMemoryHistory, RouterView } from "vue-router"
import { afterEach, expect, it, vi } from "vitest"

import "../styles/tokens.css"
import "../styles/base.css"
import AppShell from "./AppShell.vue"
import { createAppRouter, type AppRouteComponents } from "./router"
import { currentUserQueryOptions, type CurrentUser } from "../modules/auth/auth"
import AnalyticsPage from "../modules/analytics/AnalyticsPage.vue"
import CompanyProfilePage from "../modules/company/CompanyProfilePage.vue"
import PromotionPage from "../modules/content/PromotionPage.vue"
import DashboardPage from "../modules/dashboard/DashboardPage.vue"
import LeadRadarPage from "../modules/leads/LeadRadarPage.vue"

const forbiddenInternalTerms = [
  "Campaign", "ContentBrief", "MasterContent", "PlatformContent",
  "LeadCandidate", "LeadInsight", "SourceSignal", "AIRun",
  "PromptVersion", "Ontology", "PERMISSION_DENIED", "IN_REVIEW",
]
const rawFixtureStates = ["ANALYZED", "RUNNING", "SOURCE_IMPORT", "DRAFT", "READY"]
const internalSentinel = "__ORDINARY_INTERNAL_SENTINEL_7E41__"
const ids = {
  lead: "11111111-1111-4111-8111-111111111111",
  signal: "22222222-2222-4222-8222-222222222222",
  insight: "33333333-3333-4333-8333-333333333333",
  run: "44444444-4444-4444-8444-444444444444",
  campaign: "55555555-5555-4555-8555-555555555555",
  brief: "66666666-6666-4666-8666-666666666666",
  product: "77777777-7777-4777-8777-777777777777",
  platform: "88888888-8888-4888-8888-888888888888",
  asset: "99999999-9999-4999-8999-999999999999",
  knowledge: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  master: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
}

const permissions = [
  "products.read", "products.manage", "knowledge.read", "knowledge.create",
  "assets.read", "assets.manage", "campaigns.read", "campaigns.manage",
  "campaigns.review", "content.read", "content.manage", "content.review",
  "jobs.read", "jobs.manage", "memberships.read", "publishing.read",
  "tracking.read", "tracking.manage", "leads.read", "leads.review", "leads.manage", "sources.manage",
  "director.read", "director.decide",
]

const currentUser: CurrentUser = {
  user: { id: 1, username: "operator" },
  organization: { id: "org-contract", name: "SinofGear 示例组织", slug: "contract" },
  membership: { id: "member-contract", role: "OPERATOR", status: "ACTIVE", permissions },
}

const lead = {
  id: ids.lead, company_name: "北方传动", company_domain: "beifang.example",
  country_hint: "CN", status: "ANALYZED", high_value_eligible: true, latest_score: 88,
  latest_score_band: "HIGH", version: 2, created_at: "2026-08-10T08:00:00Z",
  updated_at: "2026-08-11T08:00:00Z",
}

const leadDetail = {
  id: lead.id, company: { name: lead.company_name, domain: lead.company_domain, country_hint: lead.country_hint },
  status: "ANALYZED", version: 2, created_at: lead.created_at, updated_at: lead.updated_at,
  permitted_actions: ["REVIEW"], requirements: [], review_history: [], insight_history: [],
  evidence: [{
    id: ids.signal, source_signal_id: ids.signal, platform: "LinkedIn",
    source_url: "https://example.test/post", original_text: "Need replacement helical gears",
    translated_text: "", language: "en", availability: "AVAILABLE", collection_method: "MANUAL",
    retention_class: "STANDARD", captured_at: lead.created_at, public_published_at: null,
  }],
  latest_insight: {
    id: ids.insight, source_insight_id: null, origin: "AI", score: 88, score_band: "HIGH",
    high_value_eligible: true, explanation: "需要更换斜齿轮。", dimensions: {},
    gates: { traceable_source: true, explicit_need_or_company_match: true, capability_evidence: true, audited_run: true, ontology_snapshot: true },
    extracted_requirement_values: { internal: internalSentinel }, ai_audit: { run_id: ids.run, ontology: internalSentinel },
    ai_confidence: "0.9000", company_match_confidence: "0.9000", evidence_confidence: "0.9000",
    review_reason: "", human_correction: null, reviewed_at: null, reviewed_by: null, version: 1,
    created_at: lead.created_at,
  },
}

const campaign = {
  id: ids.campaign, name: "Campaign HIGH ACTIVE 德国获客", description: "", status: "DRAFT", version: 1,
  product_ids: [], created_at: lead.created_at, updated_at: lead.updated_at,
}

const brief = {
  id: ids.brief, campaign_id: campaign.id, previous_version_id: null, version: 1,
  status: "READY", target_country: "德国", customer_type: "工业采购", content_objective: "获取询盘",
  cta: "立即询价", landing_page_url: "https://example.test/de", language: "de", prohibited_claims: [],
  selling_points: ["精密磨齿"], advantages: ["交期稳定"], keywords: ["精密齿轮"], product_ids: [ids.product],
  asset_ids: [ids.asset], platform_ids: [ids.platform], concept_links: [{ role: "STANDARD", concept_id: ids.knowledge }], created_by: 1, reviewed_by: 1,
  reviewed_at: lead.created_at, created_at: lead.created_at, updated_at: lead.updated_at,
}

const runningJob = {
  job_id: ids.run, type: "SOURCE_IMPORT", status: "RUNNING", progress: 40,
  attempt: 1, max_attempts: 3, created_at: lead.created_at, finished_at: null,
  error: null, result_reference: null,
}

const master = {
  id: ids.master, brief_id: ids.brief, brief_version: 1, generation_job_id: ids.run,
  ai_run_id: ids.run, lineage_id: internalSentinel, previous_version_id: null, version: 1,
  payload: { title: "真实推广内容", body: "根据已确认资料生成。", cta: "立即询价", concept_codes: [] },
  provenance: { internal: internalSentinel }, status: "IN_REVIEW", is_current_head: true,
  created_by_id: 1, created_at: lead.created_at, updated_at: lead.updated_at,
}

const product = {
  id: ids.product, name_zh: "Campaign HIGH ACTIVE 精密齿轮", name_en: "Precision Gear", status: "ACTIVE",
  manufacturing_capabilities: [], inspection_capabilities: [], concept_links: [], internal_notes: internalSentinel,
}

const platform = { id: ids.platform, code: "LINKEDIN", name: "LinkedIn", capabilities: ["PUBLISH"], internal: internalSentinel }
const asset = {
  id: ids.asset, asset_type: "IMAGE", original_filename: "真实产品图.png", mime_type: "image/png",
  size_bytes: 1024, checksum: internalSentinel, language: "zh", status: "ACTIVE", tags: [],
  metadata_json: { internal: internalSentinel }, created_at: lead.created_at, products: [],
}
const knowledge = {
  id: ids.knowledge, scope: "ORGANIZATION", organization: "org-contract", concept_type: "STANDARD",
  code: internalSentinel, label_zh: "DIN 标准", label_en: "DIN standard", description: "已审核标准",
  status: "APPROVED", version: 1, suggested_by_ai_run_id: ids.run, evidence: [], created_by: 1,
  reviewed_by: 1, reviewed_at: lead.created_at, created_at: lead.created_at, updated_at: lead.updated_at,
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } })
}

function page(results: unknown[]): Response {
  return json({ next: null, previous: null, results })
}

function relativeLuminance(color: string): number {
  const channels = color.match(/[\d.]+/g)?.slice(0, 3).map(Number) ?? []
  const linear = channels.map((channel) => {
    const value = channel / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * (linear[0] ?? 0) + 0.7152 * (linear[1] ?? 0) + 0.0722 * (linear[2] ?? 0)
}

function contrastRatio(foreground: string, background: string): number {
  const light = Math.max(relativeLuminance(foreground), relativeLuminance(background))
  const dark = Math.min(relativeLuminance(foreground), relativeLuminance(background))
  return (light + 0.05) / (dark + 0.05)
}

function effectiveBackgroundColor(element: HTMLElement): string {
  let current: HTMLElement | null = element
  while (current) {
    const color = getComputedStyle(current).backgroundColor
    if (color !== "transparent" && !color.endsWith(", 0)")) return color
    current = current.parentElement
  }
  return "rgb(255, 255, 255)"
}

function fixtureFetch(input: RequestInfo | URL): Promise<Response> {
  const path = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url
  if (path === "/api/v1/director/cockpit") return Promise.resolve(json({
    decisions: [{
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", type: "LEAD_HANDOFF",
      title: "北方传动值得联系", explanation: "公开信息显示明确的齿轮需求。",
      priority: 88, version: 1, actions: ["APPROVE", "REQUEST_ADJUSTMENT", "REJECT"],
    }],
    active_work: [{ job_id: ids.run, label: "正在分析公开客户线索", status: "RUNNING", progress: 40, progress_is_determinate: true }],
    recent_outcomes: [], generated_at: "2026-08-12T08:00:00Z",
  }))
  if (path === `/api/v1/lead-candidates/${encodeURIComponent(lead.id)}`) return Promise.resolve(json(leadDetail))
  if (path.startsWith("/api/v1/lead-candidates")) return Promise.resolve(page([lead]))
  if (path === "/api/v1/jobs?status=RUNNING") return Promise.resolve(page([runningJob]))
  if (path === "/api/v1/jobs" || path.startsWith("/api/v1/jobs?")) return Promise.resolve(page([]))
  if (path === "/api/v1/campaigns") return Promise.resolve(page([campaign]))
  if (path === "/api/v1/content-briefs") return Promise.resolve(page([brief]))
  if (path.startsWith("/api/v1/master-contents")) return Promise.resolve(page([master]))
  if (path.startsWith("/api/v1/products")) return Promise.resolve(page([product]))
  if (path === "/api/v1/platforms") return Promise.resolve(json({ results: [platform] }))
  if (path.startsWith("/api/v1/assets")) return Promise.resolve(page([asset]))
  if (path.startsWith("/api/v1/knowledge/concepts")) return Promise.resolve(page([knowledge]))
  if (path.startsWith("/api/v1/knowledge/evidence")) return Promise.resolve(page([]))
  if (path.startsWith("/api/v1/analytics")) return Promise.resolve(json({
    count: 1, total_clicks: 17, next: null, previous: null,
    results: [{ date: "2026-08-10", campaign_id: campaign.id, platform_id: ids.platform, country: "DE", product_id: ids.product, clicks: 17 }],
  }))
  if (path.startsWith("/api/v1/tracking-links") || path.startsWith("/api/v1/short-links") || path.startsWith("/api/v1/publish-tasks")) return Promise.resolve(page([]))
  return Promise.resolve(page([]))
}

const Placeholder = defineComponent({ template: "<div><h1>高级工作区</h1></div>" })
const Root = defineComponent({ setup: () => () => h(RouterView) })

async function renderOrdinaryRoute(path: string, options: { fetcher?: typeof fixtureFetch; ready?: string } = {}) {
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
    matches: false, media: "(max-width: 860px)", onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
  vi.stubGlobal("fetch", vi.fn(options.fetcher ?? fixtureFetch))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(currentUserQueryOptions().queryKey, currentUser)
  const components: AppRouteComponents = {
    Login: Placeholder, Shell: AppShell, Dashboard: DashboardPage, Promotion: PromotionPage,
    LeadRadar: LeadRadarPage, Analytics: AnalyticsPage, CompanyProfile: CompanyProfilePage,
    Products: Placeholder, Knowledge: Placeholder, ContentFactory: Placeholder, Reviews: Placeholder,
    Assets: Placeholder, PublishingCalendar: Placeholder, PlatformAccounts: Placeholder,
    AISettings: Placeholder, AgentCenter: Placeholder,
  }
  const router = createAppRouter(queryClient, { history: createMemoryHistory(), components })
  await router.push(path)
  await router.isReady()
  const view = render(Root, { global: { plugins: [[VueQueryPlugin, { queryClient }], router] } })
  const routeExpectations: Record<string, { heading: string; ready: string }> = {
    "/": { heading: /\u4eca\u5929.*\u4ef6\u4e8b\u9700\u8981\u4f60\u51b3\u5b9a/, ready: "北方传动" },
    "/promotion": { heading: "你今天想推广什么？", ready: "可推广产品" },
    "/lead-radar": { heading: "客户机会", ready: "需要更换斜齿轮。" },
    "/analytics": { heading: "效果", ready: "Campaign HIGH ACTIVE 德国获客" },
    "/company-profile": { heading: "产品资料", ready: "Campaign HIGH ACTIVE 精密齿轮" },
  }
  const expected = routeExpectations[path]
  await screen.findByRole("heading", { name: expected.heading, level: 1 })
  await screen.findAllByText(options.ready ?? expected.ready, { exact: false })
  await waitFor(() => expect(screen.queryByText("正在确认登录状态…")).not.toBeInTheDocument())
  return { ...view, router, queryClient }
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

it.each(["/", "/promotion", "/lead-radar", "/analytics", "/company-profile"])(
  "%s keeps internal language out of ordinary mode",
  async (path) => {
    const view = await renderOrdinaryRoute(path)
    for (const token of forbiddenInternalTerms) expect(screen.queryByText(token, { exact: true })).not.toBeInTheDocument()
    for (const state of rawFixtureStates) expect(screen.queryByText(state, { exact: true })).not.toBeInTheDocument()
    expect(view.container).not.toHaveTextContent(internalSentinel)
    for (const id of Object.values(ids)) expect(view.container).not.toHaveTextContent(id)
    expect(screen.getAllByRole("main")).toHaveLength(1)

    const main = screen.getByRole("main")
    expect(main).toHaveAttribute("id", "main-content")
    const skip = screen.getByRole("link", { name: "跳到主要内容" })
    expect(skip).toHaveAttribute("href", "#main-content")
    await userEvent.click(skip)
    expect(main).toHaveFocus()

    const headings = [...main.querySelectorAll<HTMLElement>("h1, h2, h3, h4, h5, h6")]
    expect(headings.filter((heading) => heading.tagName === "H1")).toHaveLength(1)
    for (let index = 1; index < headings.length; index += 1) {
      const previous = Number(headings[index - 1].tagName.slice(1))
      const current = Number(headings[index].tagName.slice(1))
      expect(current).toBeLessThanOrEqual(previous + 1)
    }
    for (const button of screen.queryAllByRole("button")) expect(button).toHaveAccessibleName()
  },
)

it("keeps ordinary shell columns explicitly shrinkable", async () => {
  await renderOrdinaryRoute("/analytics")
  const shellMain = document.querySelector<HTMLElement>(".app-main")
  const content = screen.getByRole("main")
  expect(["0", "0px"]).toContain(getComputedStyle(shellMain!).minWidth)
  expect(["0", "0px"]).toContain(getComputedStyle(content).minWidth)
})

it("preserves legitimate user content that includes words resembling internal states", async () => {
  await renderOrdinaryRoute("/company-profile")
  expect(screen.getAllByText(/Campaign HIGH ACTIVE 精密齿轮/).length).toBeGreaterThan(0)
})

const privateError = {
  code: "PERMISSION_DENIED",
  message: `English userMessage ${internalSentinel}`,
  recovery_action: "Contact your administrator and retry",
  errors: { internal_field_name: [`Invalid UUID ${ids.master}`] },
}

function errorFetch(prefix: string): typeof fixtureFetch {
  return (input: RequestInfo | URL) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url
    return path.includes(prefix) ? Promise.resolve(json(privateError, 403)) : fixtureFetch(input)
  }
}

it.each([
  ["/analytics", "/api/v1/analytics", "操作未能完成，请稍后重试。"],
  ["/company-profile", "/api/v1/products", "产品资料暂时无法读取。"],
  ["/promotion", "/api/v1/campaigns", "可推广产品"],
  ["/lead-radar", "/api/v1/lead-candidates", "服务暂时不可用，请稍后重新加载。"],
] as const)("%s translates API failures without exposing raw server details", async (path, prefix, ready) => {
  const view = await renderOrdinaryRoute(path, { fetcher: errorFetch(prefix), ready })
  if (path === "/promotion") {
    await userEvent.click(screen.getByRole("button", { name: "查看高级记录" }))
    await screen.findByText("活动没有加载成功，请稍后重试。", { exact: false })
  }
  expect(view.container).not.toHaveTextContent("PERMISSION_DENIED")
  expect(view.container).not.toHaveTextContent("English userMessage")
  expect(view.container).not.toHaveTextContent("Contact your administrator")
  expect(view.container).not.toHaveTextContent("internal_field_name")
  expect(view.container).not.toHaveTextContent(ids.master)
  expect(view.container).not.toHaveTextContent(internalSentinel)
})

it("keeps small navigation group labels at text contrast", async () => {
  await renderOrdinaryRoute("/")

  const label = screen.getByRole("heading", { name: "日常工作" })
  const sidebar = screen.getByTestId("app-sidebar")
  expect(contrastRatio(getComputedStyle(label).color, effectiveBackgroundColor(sidebar)))
    .toBeGreaterThanOrEqual(4.5)
})

it("removes non-essential motion when reduced motion is requested", async () => {
  await renderOrdinaryRoute("/")

  const reducedMotionRule = [...document.styleSheets]
    .flatMap((sheet) => [...sheet.cssRules])
    .filter((rule): rule is CSSMediaRule => rule instanceof CSSMediaRule)
    .filter((rule) => rule.conditionText.includes("prefers-reduced-motion"))
    .flatMap((rule) => [...rule.cssRules])
    .find((rule): rule is CSSStyleRule => rule instanceof CSSStyleRule && rule.selectorText.includes("*::before"))
  expect(reducedMotionRule).toBeDefined()
  expect(reducedMotionRule?.style.getPropertyValue("transition")).toBe("none")
  expect(reducedMotionRule?.style.getPropertyValue("animation")).toBe("none")
})
