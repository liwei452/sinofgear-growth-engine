import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import CompanyPage from "./CompanyPage.vue"
import EffectivenessPage from "./EffectivenessPage.vue"
import OpportunitiesPage from "./OpportunitiesPage.vue"
import PromotionPage from "./PromotionPage.vue"

it("reviews an ICP and a complete TikTok manual publishing package", async () => {
  const user = userEvent.setup()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(screen.getByRole("heading", { name: "推广计划与内容包" })).toBeInTheDocument()
  expect(screen.getByText("尚未形成客户画像")).toBeInTheDocument()
  expect(screen.queryByText("德国包装机械制造商 · 51–500 人")).not.toBeInTheDocument()
  const tiktok = screen.getByRole("article", { name: "TikTok 内容包" })
  expect(tiktok).toHaveTextContent("15–60 秒")
  expect(tiktok).toHaveTextContent("9:16")
  expect(tiktok).toHaveTextContent("英文口播")
  expect(tiktok).toHaveTextContent("中文字幕")
  expect(tiktok).toHaveTextContent("分镜")
  expect(tiktok).toHaveTextContent("标题 / 标签 / CTA")
  expect(tiktok).toHaveTextContent("UTM")
  expect(tiktok).toHaveTextContent("手工发布包")
  expect(tiktok).toHaveTextContent("Demo / Fake")
  await user.click(screen.getByRole("button", { name: "批准内容包" }))
  expect(screen.getByRole("status")).toHaveTextContent("已批准，等待人工下载或手工发布")
})

it("keeps accounts, contacts, signals, and inbound leads visibly distinct", () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(OpportunitiesPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  for (const objectName of ["目标公司", "联系人", "需求信号", "入站线索"]) {
    expect(screen.getByText(objectName, { selector: "dt" })).toBeInTheDocument()
  }
  expect(screen.getByText("PackTech GmbH", { selector: "h2" })).toBeInTheDocument()
  expect(screen.getAllByText("公开采购岗位", { exact: false }).length).toBeGreaterThan(0)
  expect(screen.getByRole("button", { name: "加入跟进" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "生成联系草稿" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "查看证据" })).toBeInTheDocument()
})

it("shows no channel success metrics until a result has actually been recorded", async () => {
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], opportunity_reviews: [], crm_handoffs: [], reactivations: [],
    channel_packages: [], publish_batches: [], metric_receipts: [] as Array<Record<string, unknown>>, field_provenance: [], connectors: [],
  }
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(workspace), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(EffectivenessPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(screen.getByRole("heading", { name: "推广效果" })).toBeInTheDocument()
  expect(await screen.findByText("尚未回填渠道结果")).toBeInTheDocument()
  expect(screen.queryByText("26.5%")).not.toBeInTheDocument()
  expect(screen.queryByText("3 个询盘")).not.toBeInTheDocument()
  const summary = screen.getByRole("region", { name: "渠道回填摘要" })
  expect(within(summary).getByText("尚未发生 / 无数据")).toBeInTheDocument()
})

it("shows persisted account approval in the effectiveness attribution panel", async () => {
  const workspace = {
    target_accounts: [{ id: "account-pack", name: "PackTech GmbH", country: "Germany", industry: "Packaging machinery", employee_range: "51-200", website: "", is_demo: true, data_label: "Demo / Fake" }],
    contacts: [], inbound_leads: [], follow_ups: [], outreach_drafts: [], opportunity_reviews: [], crm_handoffs: [],
    intent_signals: [], channel_packages: [], publish_batches: [], metric_receipts: [], field_provenance: [], connectors: [],
    reactivations: [{
      id: "react-pack", account_id: "account-pack", account_name: "PackTech GmbH", industry: "Packaging machinery",
      relationship_source: "PAST_INQUIRY", last_interacted_at: "2026-04-15T08:00:00Z",
      interaction_summary: "2025 trade fair discussion.", tier: "STRATEGIC", status: "APPROVED", is_demo: true,
      why_reactivate: "已有合法关系", recommended_action: "人工复核", evidence: "已有关系记录",
      risk: "发送前复核", draft: { id: "draft-pack", english_draft: "Hello", chinese_explanation: "已有事实", status: "APPROVED" },
      events: [{ event_type: "REACTIVATION_APPROVED", created_at: "2026-08-15T08:30:00Z", delivery: "NEVER_SENT" }],
      delivery: "NEVER_SENT",
    }],
  }
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(EffectivenessPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const panel = await screen.findByRole("region", { name: "账户获客漏斗" })
  expect(within(panel).getByRole("article", { name: "PackTech GmbH 归因记录" })).toHaveTextContent("人工批准")
  expect(within(panel).getByText("已批准，尚未发送")).toBeInTheDocument()
})

it("requires provenance before saving a verified manual channel result", async () => {
  document.cookie = "csrftoken=manual-metric-provenance-token"
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], opportunity_reviews: [], crm_handoffs: [], reactivations: [],
    channel_packages: [], publish_batches: [], metric_receipts: [], field_provenance: [], connectors: [],
  }
  let submitted: Record<string, unknown> | undefined
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    submitted = JSON.parse(String(init?.body))
    const saved = { id: "metric-real", ...(submitted ?? {}), created_at: "2026-08-15T10:00:00Z", updated_at: "2026-08-15T10:00:00Z" }
    workspace.metric_receipts.unshift(saved)
    return new Response(JSON.stringify(saved), {
      status: 201, headers: { "Content-Type": "application/json" },
    })
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(EffectivenessPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  await screen.findByText("尚未回填渠道结果")
  await user.selectOptions(screen.getByLabelText("数据性质"), "VERIFIED_MANUAL")
  await user.type(screen.getByLabelText("数据来源说明"), "LinkedIn Page analytics checked by owner")
  await user.type(screen.getByLabelText("观察时间"), "2026-08-15T09:30")
  await user.click(screen.getByRole("button", { name: "保存回填" }))

  await waitFor(() => expect(submitted).toBeDefined())
  expect(submitted).toMatchObject({
    is_demo: false,
    payload: {
      source_note: "LinkedIn Page analytics checked by owner",
      observed_at: "2026-08-15T09:30",
    },
  })
  expect(await screen.findByText("LinkedIn Page analytics checked by owner")).toBeInTheDocument()
  expect(screen.getByText(/观察时间.*2026-08-15T09:30/)).toBeInTheDocument()
})

it("persists content-package approval and manual metric backfill", async () => {
  document.cookie = "csrftoken=growth-pages-test-token"
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], connectors: [], metric_receipts: [],
    channel_packages: [{
      id: "10000000-0000-4000-8000-000000001201", account_id: null, channel: "TIKTOK",
      payload: {
        duration_seconds: 30, aspect_ratio: "9:16", title: "API TikTok package",
        verified_fact_evidence: [{
          fact_id: "11111111-1111-4111-8111-111111111111",
          field_name: "process", value: "Gear grinding", source_filename: "gear-catalog.pdf",
          source_page: 2, source_excerpt: "Process: Gear grinding", is_demo: true,
        }],
      },
      status: "AWAITING_REVIEW", is_demo: true, data_label: "Demo / Fake",
      delivery: "MANUAL_ONLY", created_at: "2026-08-14T08:00:00Z", updated_at: "2026-08-14T08:00:00Z",
    }],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/approve")) {
      return new Response(JSON.stringify({
        id: workspace.channel_packages[0].id, status: "APPROVED", delivery: "MANUAL_ONLY",
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/manual-export")) {
      return new Response(JSON.stringify({
        package_id: workspace.channel_packages[0].id,
        channel: "TIKTOK", mode: "MANUAL_PACKAGE", data_label: "Demo / Fake",
        delivery: "MANUAL_ONLY", filename: "tiktok-manual-package.json",
        payload: workspace.channel_packages[0].payload,
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/growth/metric-receipts") {
      return new Response(JSON.stringify({
        id: "metric-1", channel: "TIKTOK", payload: { views: 7000, clicks: 200 }, is_demo: true,
        created_at: "2026-08-14T09:00:00Z", updated_at: "2026-08-14T09:00:00Z",
      }), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  const promotionClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const promotion = render(PromotionPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient: promotionClient }]] },
  })

  expect(await screen.findByText("API TikTok package")).toBeInTheDocument()
  const tiktokPackage = screen.getByRole("article", { name: "TikTok 内容包" })
  expect(within(tiktokPackage).getByText("process：Gear grinding")).toBeInTheDocument()
  expect(within(tiktokPackage).getByText("gear-catalog.pdf · 第 2 页 · Demo/Fake")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "批准内容包" }))
  expect(await screen.findByRole("status")).toHaveTextContent("已批准")
  await user.click(screen.getByRole("button", { name: "下载发布包" }))
  expect(await screen.findByText(/发布包已下载/)).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/manual-export"))).toBe(true)
  promotion.unmount()

  const effectivenessClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(EffectivenessPage, {
    global: { plugins: [[VueQueryPlugin, { queryClient: effectivenessClient }]] },
  })
  await user.clear(screen.getByLabelText("播放或访问"))
  await user.type(screen.getByLabelText("播放或访问"), "7000")
  await user.clear(screen.getByLabelText("点击"))
  await user.type(screen.getByLabelText("点击"), "200")
  await user.click(screen.getByRole("button", { name: "保存回填" }))

  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("指标已保存"))
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/approve"))).toBe(true)
  expect(fetchMock.mock.calls.some(([path]) => String(path) === "/api/v1/growth/metric-receipts")).toBe(true)
})

it("keeps channel package review state independent", async () => {
  document.cookie = "csrftoken=channel-review-test-token"
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], connectors: [], metric_receipts: [],
    channel_packages: [
      {
        id: "10000000-0000-4000-8000-000000001201", account_id: null, channel: "LINKEDIN",
        payload: { title: "LinkedIn evidence post", format: "English post with Chinese copy" },
        status: "AWAITING_REVIEW", is_demo: true, data_label: "Demo / Fake",
        delivery: "MANUAL_ONLY", created_at: "2026-08-14T08:00:00Z", updated_at: "2026-08-14T08:00:00Z",
      },
      {
        id: "10000000-0000-4000-8000-000000001204", account_id: null, channel: "TIKTOK",
        payload: { title: "TikTok proof video", duration_seconds: 30, aspect_ratio: "9:16" },
        status: "AWAITING_REVIEW", is_demo: true, data_label: "Demo / Fake",
        delivery: "MANUAL_ONLY", created_at: "2026-08-14T08:00:00Z", updated_at: "2026-08-14T08:00:00Z",
      },
    ],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/approve")) {
      return new Response(JSON.stringify({
        id: workspace.channel_packages[0].id, status: "APPROVED", delivery: "MANUAL_ONLY",
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  await screen.findByText("LinkedIn evidence post")
  const linkedIn = screen.getByRole("article", { name: "LinkedIn Company Page 内容包" })
  const tiktok = screen.getByRole("article", { name: "TikTok 内容包" })
  await user.click(within(linkedIn).getByRole("button", { name: "批准 LinkedIn 内容包" }))

  expect(await within(linkedIn).findByRole("button", { name: "下载 LinkedIn 发布包" })).toBeEnabled()
  expect(within(tiktok).getByRole("button", { name: "批准 TikTok 内容包" })).toBeEnabled()
  const combined = screen.getByRole("region", { name: "四渠道手工发布包" })
  expect(within(combined).getByRole("button", { name: "下载四渠道手工发布包" })).toBeDisabled()
  expect(combined).toHaveTextContent("Facebook：缺少内容包")
  expect(combined).toHaveTextContent("TikTok：等待人工审核")
})

it("requires one explicit confirmation before approving all four channel packages", async () => {
  document.cookie = "csrftoken=batch-review-test-token"
  const channels = ["LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"]
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], metric_receipts: [], publish_batches: [],
    connectors: channels.map(channel => ({
      channel, status: "CONNECTED", connection_label: "已连接", recovery_action: "", mode: "DEMO_FAKE",
    })),
    channel_packages: channels.map((channel, index) => ({
      id: `40000000-0000-4000-8000-00000000120${index + 1}`,
      account_id: null, source_platform_content_id: `50000000-0000-4000-8000-00000000120${index + 1}`,
      channel,
      payload: channel === "TIKTOK"
        ? { title: "TikTok evidence version", duration_seconds: 30, aspect_ratio: "9:16" }
        : { title: `${channel} evidence version` },
      status: "AWAITING_REVIEW", is_demo: true, data_label: "Demo / Fake", delivery: "MANUAL_ONLY",
      created_at: "2026-08-15T10:00:00Z", updated_at: "2026-08-15T10:00:00Z",
    })),
  }
  let capturedIds: string[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/growth/channel-packages/approve-all") {
      capturedIds = JSON.parse(String(init?.body)).package_ids
      workspace.channel_packages.forEach(item => { item.status = "APPROVED" })
      return new Response(JSON.stringify({ status: "APPROVED", delivery: "MANUAL_ONLY", packages: [] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const review = await screen.findByRole("region", { name: "四渠道内容总审核" })
  const approveAll = within(review).getByRole("button", { name: "批准 4 个渠道内容" })
  expect(approveAll).toBeDisabled()
  await user.click(within(review).getByRole("checkbox", { name: "我已核对四个平台内容与事实证据" }))
  await user.click(approveAll)

  expect(capturedIds).toEqual(workspace.channel_packages.map(item => item.id))
  expect(await within(review).findByText("四个平台内容均已人工批准")).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([path]) => String(path) === "/api/v1/growth/publish-batches")).toBe(false)
})

it("downloads one approved four-channel manual package without publishing", async () => {
  document.cookie = "csrftoken=combined-export-test-token"
  const channels = ["LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"]
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], metric_receipts: [], publish_batches: [], connectors: [],
    channel_packages: channels.map((channel, index) => ({
      id: `60000000-0000-4000-8000-00000000120${index + 1}`,
      account_id: null, source_platform_content_id: `70000000-0000-4000-8000-00000000120${index + 1}`,
      channel,
      payload: channel === "TIKTOK"
        ? { title: "TikTok approved", duration_seconds: 30, aspect_ratio: "9:16" }
        : { title: `${channel} approved` },
      status: "APPROVED", is_demo: true, data_label: "Demo / Fake", delivery: "MANUAL_ONLY",
      created_at: "2026-08-15T10:00:00Z", updated_at: "2026-08-15T10:00:00Z",
    })),
  }
  let exportedIds: string[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    if (path === "/api/v1/growth/channel-packages/manual-export-all") {
      exportedIds = JSON.parse(String(init?.body)).package_ids
      return new Response(new Blob(["safe-zip"]), {
        status: 200,
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition": 'attachment; filename="four-channel-manual-package-abc123.zip"',
          "X-Content-SHA256": "abc123",
        },
      })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const objectUrl = vi.fn(() => "blob:four-channel-export")
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: objectUrl, revokeObjectURL: vi.fn() }))
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const exportPanel = await screen.findByRole("region", { name: "四渠道手工发布包" })
  const download = within(exportPanel).getByRole("button", { name: "下载四渠道手工发布包" })
  expect(download).toBeEnabled()
  await user.click(download)

  expect(exportedIds).toEqual(workspace.channel_packages.map(item => item.id))
  expect(objectUrl).toHaveBeenCalledOnce()
  expect(await screen.findByText("四渠道手工发布包已下载；请人工登录平台发布，未触发任何平台请求。")).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([path]) => String(path) === "/api/v1/growth/publish-batches")).toBe(false)
})

it("publishes all approved channels once and retries only failed channels", async () => {
  document.cookie = "csrftoken=one-click-publish-test-token"
  const channels = ["LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"]
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], metric_receipts: [],
    connectors: channels.map(channel => ({
      channel, status: "CONNECTED", connection_label: "已连接", recovery_action: "", mode: "DEMO_FAKE",
    })),
    channel_packages: channels.map((channel, index) => ({
      id: `10000000-0000-4000-8000-00000000120${index + 1}`,
      account_id: null,
      channel,
      payload: channel === "TIKTOK"
        ? { title: `${channel} inspection proof`, duration_seconds: 30, aspect_ratio: "9:16" }
        : { title: `${channel} inspection proof` },
      status: "APPROVED",
      is_demo: true,
      data_label: "Demo / Fake",
      delivery: "MANUAL_ONLY",
      created_at: "2026-08-14T08:00:00Z",
      updated_at: "2026-08-14T08:00:00Z",
    })),
  }
  const resultItems = channels.map(channel => ({
    id: `item-${channel}`,
    channel,
    status: channel === "TIKTOK" ? "FAILED" : "SUCCEEDED",
    attempt_number: 1,
    external_post_url: channel === "TIKTOK" ? "" : `https://example.invalid/demo-post/${channel.toLowerCase()}/item`,
    error_code: channel === "TIKTOK" ? "PROVIDER_ERROR" : "",
    recovery_action: channel === "TIKTOK" ? "可重试该失败渠道。" : "",
    created_at: "2026-08-14T08:00:00Z",
    updated_at: "2026-08-14T08:00:00Z",
  }))
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/growth/publish-batches") {
      expect(JSON.parse(String(init?.body))).toEqual({ package_ids: workspace.channel_packages.map(item => item.id) })
      const key = new Headers(init?.headers).get("Idempotency-Key") ?? ""
      expect(key).toMatch(/^[\x21-\x7e]{1,128}$/)
      return new Response(JSON.stringify({
        id: "batch-1", status: "PARTIAL_SUCCESS", is_demo: true,
        data_label: "Demo / Fake 发布结果", created_at: "2026-08-14T08:00:00Z",
        updated_at: "2026-08-14T08:00:00Z", items: resultItems,
      }), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/growth/publish-batches/batch-1/retry-failed") {
      return new Response(JSON.stringify({
        id: "batch-1", status: "SUCCEEDED", is_demo: true,
        data_label: "Demo / Fake 发布结果", created_at: "2026-08-14T08:00:00Z",
        updated_at: "2026-08-14T08:01:00Z",
        items: resultItems.map(item => item.channel === "TIKTOK" ? {
          ...item, status: "SUCCEEDED", attempt_number: 2,
          external_post_url: "https://example.invalid/demo-post/tiktok/item", error_code: "", recovery_action: "",
        } : item),
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const readiness = await screen.findByRole("region", { name: "四渠道发布就绪检查" })
  expect(within(readiness).getByText("LinkedIn · 已就绪")).toBeInTheDocument()
  expect(within(readiness).getByText("Facebook · 已就绪")).toBeInTheDocument()
  expect(within(readiness).getByText("Instagram · 已就绪")).toBeInTheDocument()
  expect(within(readiness).getByText("TikTok · 已就绪")).toBeInTheDocument()
  await user.click(await screen.findByRole("button", { name: "一键发布到 4 个渠道" }))

  expect(await screen.findByText("Demo / Fake 发布结果")).toBeInTheDocument()
  expect(screen.getByText("3 个渠道发布成功，1 个渠道需要重试。")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "查看 LinkedIn Demo 帖子" })).toHaveAttribute("href", expect.stringContaining("example.invalid"))
  await user.click(screen.getByRole("button", { name: "重试失败渠道" }))
  expect(await screen.findByText("4 个渠道均已发布成功。")).toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([path]) => String(path) === "/api/v1/growth/publish-batches")).toHaveLength(1)
})

it("explains every blocked channel and never silently publishes a partial batch", async () => {
  document.cookie = "csrftoken=readiness-gate-test-token"
  const channels = ["LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"]
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], metric_receipts: [], publish_batches: [],
    connectors: channels.map(channel => ({
      channel,
      status: channel === "INSTAGRAM" ? "NOT_CONNECTED" : "CONNECTED",
      connection_label: channel === "INSTAGRAM" ? "未连接" : "已连接",
      recovery_action: channel === "INSTAGRAM" ? "连接账号" : "",
      mode: "DEMO_FAKE",
    })),
    channel_packages: channels.map((channel, index) => ({
      id: `20000000-0000-4000-8000-00000000120${index + 1}`,
      account_id: null, source_platform_content_id: `30000000-0000-4000-8000-00000000120${index + 1}`,
      channel,
      payload: channel === "TIKTOK"
        ? { title: "Incomplete TikTok", duration_seconds: 10, aspect_ratio: "16:9" }
        : { title: `${channel} reviewed content` },
      status: channel === "FACEBOOK" ? "AWAITING_REVIEW" : "APPROVED",
      is_demo: true, data_label: "Demo / Fake", delivery: "MANUAL_ONLY",
      created_at: "2026-08-15T10:00:00Z", updated_at: "2026-08-15T10:00:00Z",
    })),
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findAllByText("LINKEDIN reviewed content")).not.toHaveLength(0)
  const readiness = screen.getByRole("region", { name: "四渠道发布就绪检查" })
  expect(within(readiness).getByText("LinkedIn · 已就绪")).toBeInTheDocument()
  expect(within(readiness).getByText("Facebook · 等待内容审核")).toBeInTheDocument()
  expect(within(readiness).getByText("Instagram · 账号未连接")).toBeInTheDocument()
  expect(within(readiness).getByText("TikTok · 发布格式待补全")).toBeInTheDocument()
  await user.click(within(readiness).getByRole("button", { name: "审核 Facebook 内容" }))
  expect(document.querySelector("#channel-package-FACEBOOK")).toHaveFocus()
  await user.click(within(readiness).getByRole("button", { name: "处理 Instagram 账号" }))
  expect(document.querySelector("#channel-package-INSTAGRAM")).toHaveFocus()
  expect(within(readiness).getByRole("link", { name: "补全 TikTok 发布格式" })).toHaveAttribute("href", "/reviews")
  const blocked = within(readiness).getByRole("button", { name: "还有 3 个渠道未就绪" })
  expect(blocked).toBeDisabled()
  await user.click(blocked)
  expect(fetchMock.mock.calls.some(([path]) => String(path) === "/api/v1/growth/publish-batches")).toBe(false)
})

it("restores the latest one-click publish result after a page reload", async () => {
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], metric_receipts: [], connectors: [], channel_packages: [],
    publish_batches: [{
      id: "batch-persisted", status: "SUCCEEDED", is_demo: true,
      data_label: "Demo / Fake 发布结果", created_at: "2026-08-14T08:00:00Z",
      updated_at: "2026-08-14T08:01:00Z",
      items: ["LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"].map(channel => ({
        id: `item-${channel}`, channel, status: "SUCCEEDED", attempt_number: 1,
        external_post_url: `https://example.invalid/demo-post/${channel.toLowerCase()}/item`,
        error_code: "", recovery_action: "", created_at: "2026-08-14T08:00:00Z",
        updated_at: "2026-08-14T08:01:00Z",
      })),
    }],
  }
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(workspace), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByText("Demo / Fake 发布结果")).toBeInTheDocument()
  expect(screen.getByText("4 个渠道均已发布成功。")).toBeInTheDocument()
})

it("labels official publish links truthfully and uses the recorded success count", async () => {
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], metric_receipts: [], connectors: [], channel_packages: [],
    publish_batches: [{
      id: "batch-official", status: "SUCCEEDED", is_demo: false,
      data_label: "真实平台发布结果", created_at: "2026-08-15T08:00:00Z",
      updated_at: "2026-08-15T08:01:00Z",
      items: [{
        id: "item-linkedin", channel: "LINKEDIN", status: "SUCCEEDED", attempt_number: 1,
        external_post_url: "https://www.linkedin.com/feed/update/urn:li:activity:123",
        mode: "OFFICIAL", error_code: "", retryable: false, recovery_action: "",
        created_at: "2026-08-15T08:00:00Z", updated_at: "2026-08-15T08:01:00Z",
      }],
    }],
  }
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(workspace), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByRole("link", { name: "查看 LinkedIn 平台帖子" })).toHaveAttribute(
    "href", "https://www.linkedin.com/feed/update/urn:li:activity:123",
  )
  expect(screen.getByText("1 个渠道已发布成功。")).toBeInTheDocument()
  expect(screen.getByText("结果记录时间：")).toBeInTheDocument()
  expect(screen.getByText("2026-08-15 16:01")).toHaveAttribute(
    "datetime", "2026-08-15T08:01:00Z",
  )
  expect(screen.queryByText(/Demo 帖子/)).not.toBeInTheDocument()
})

it("shows company facts with provenance, verification, cost, and gaps", () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(CompanyPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(screen.getByRole("heading", { name: "我的公司" })).toBeInTheDocument()
  expect(screen.getByRole("columnheader", { name: "字段来源" })).toBeInTheDocument()
  expect(screen.getByRole("columnheader", { name: "确认状态" })).toBeInTheDocument()
  expect(screen.getByRole("columnheader", { name: "来源成本" })).toBeInTheDocument()
  expect(screen.getByText("ISO 9001 证书 · 人工上传记录")).toBeInTheDocument()
  expect(screen.getAllByText("待确认", { exact: true }).length).toBe(2)
  expect(screen.getByRole("heading", { name: "建议补充" })).toBeInTheDocument()
})

it("sorts and switches the opportunity queue without sharing follow-up state", async () => {
  document.cookie = "csrftoken=opportunity-page-test-token"
  const accountId = "10000000-0000-4000-8000-000000001001"
  const workspace = {
    target_accounts: [
      {
        id: "10000000-0000-4000-8000-000000001003", name: "NordMotion AB", country: "Sweden",
        industry: "Automation equipment", employee_range: "51-200", website: "",
        is_demo: true, data_label: "Demo / Fake",
      },
      {
        id: accountId, name: "API Opportunity GmbH", country: "Germany",
        industry: "Packaging machinery", employee_range: "51-200", website: "",
        is_demo: true, data_label: "Demo / Fake",
      },
    ],
    contacts: [{
      id: "contact-1", account_id: accountId, full_name: "Purchasing team",
      role_title: "Public company contact path", public_contact_path: "https://example.invalid/contact",
      verification_status: "PUBLIC_PATH",
    }],
    intent_signals: [
      {
        id: "signal-low", account_id: "10000000-0000-4000-8000-000000001003",
        signal_type: "PRODUCT_CHANGE", source_label: "Public product page",
        source_url: "https://example.invalid/products", evidence_text: "Added a low-noise drive range",
        confidence: 52, observed_at: "2026-08-14T08:00:00Z", data_label: "Demo / Fake",
      },
      {
        id: "signal-1", account_id: accountId, signal_type: "HIRING",
        source_label: "Public careers page", source_url: "https://example.invalid/careers",
        evidence_text: "Hiring a transmission buyer", confidence: 88,
        observed_at: "2026-08-14T09:20:00Z", data_label: "Demo / Fake",
      },
    ],
    inbound_leads: [], follow_ups: [], outreach_drafts: [], channel_packages: [],
    metric_receipts: [], field_provenance: [], connectors: [],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/follow-up")) {
      return new Response(JSON.stringify({ id: "follow-1", account_id: accountId, status: "OPEN" }), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/draft")) {
      return new Response(JSON.stringify({
        id: "draft-1", status: "DRAFT", "English draft": "Persisted opportunity-page draft.",
        "Chinese explanation": "人工审核后才能使用。", delivery: "NEVER_SENT",
      }), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(OpportunitiesPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByRole("heading", { name: "API Opportunity GmbH" })).toBeInTheDocument()
  expect(screen.getByText("Purchasing team", { exact: false })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "加入跟进" }))
  await waitFor(() => expect(screen.getByRole("button", { name: "已加入跟进" })).toBeDisabled())
  await user.click(screen.getByRole("button", { name: /NordMotion AB/ }))
  expect(await screen.findByRole("heading", { name: "NordMotion AB" })).toBeInTheDocument()
  expect(screen.getByText("Added a low-noise drive range")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "加入跟进" })).toBeEnabled()
  await user.click(screen.getByRole("button", { name: /API Opportunity GmbH/ }))
  await user.click(screen.getByRole("button", { name: "生成联系草稿" }))
  expect(await screen.findByText(/Persisted opportunity-page draft\./)).toBeInTheDocument()
})

it("explains evidence scoring and shows only safe source links with saved follow-up history", async () => {
  const primaryId = "10000000-0000-4000-8000-000000001001"
  const observedId = "10000000-0000-4000-8000-000000001002"
  const workspace = {
    target_accounts: [
      {
        id: primaryId, name: "Evidence Buyer GmbH", country: "Germany",
        industry: "Packaging machinery", employee_range: "51-200", website: "",
        is_demo: true, data_label: "Demo / Fake",
      },
      {
        id: observedId, name: "Thin Evidence SpA", country: "Italy",
        industry: "Food machinery", employee_range: "201-500", website: "",
        is_demo: true, data_label: "Demo / Fake",
      },
    ],
    contacts: [],
    intent_signals: [
      {
        id: "signal-primary", account_id: primaryId, signal_type: "HIRING",
        source_label: "Public careers page", source_url: "https://example.invalid/evidence",
        evidence_text: "Hiring a precision transmission buyer", confidence: 88,
        observed_at: "2026-08-14T09:20:00Z", data_label: "Demo / Fake",
        collection_method: "DEMO_FIXTURE", collection_method_label: "本地演示样本",
        content_hash: "a".repeat(64), scoring_rule_version: "opportunity-v1",
        score_breakdown: {
          icp_fit: 20, intent_strength: 24, recency: 14,
          role_relevance: 12, evidence_coverage: 18, risk_penalty: 0,
        },
        evidence_envelope: {
          field_value: "Hiring a precision transmission buyer",
          source_url: "https://example.invalid/evidence",
          source_excerpt: "Hiring a precision transmission buyer",
          confidence: 88,
          observed_at: "2026-08-14T09:20:00Z",
          source_cost_micros: 0,
          license_contract: "TED_SEARCH_API_PUBLIC_DATA",
          usage_rights: "INTERNAL_DISCOVERY_WITH_SOURCE_LINK",
          review_status: "PENDING_REVIEW",
          queue: "MONITORING",
          source_type: "TENDER",
          matched_keywords: ["gear shaft", "helical gear"],
          company_match_confidence: 80,
          ai_exclusion_reasons: [],
        },
        uncertainty_notes: ["采购时间仍需人工确认"], priority_label: "优先跟进",
      },
      {
        id: "signal-observed", account_id: observedId, signal_type: "EXPANSION",
        source_label: "Untrusted import", source_url: "http://unsafe.example/evidence",
        evidence_text: "Possible expansion", confidence: 90,
        observed_at: "2026-08-14T08:00:00Z", data_label: "Demo / Fake",
        collection_method: "MANUAL_URL", collection_method_label: "人工导入网页",
        content_hash: "b".repeat(64), scoring_rule_version: "opportunity-v1",
        score_breakdown: {
          icp_fit: 25, intent_strength: 25, recency: 20,
          role_relevance: 10, evidence_coverage: 10, risk_penalty: 0,
        },
        uncertainty_notes: ["只有单一来源"], priority_label: "继续观察",
      },
    ],
    inbound_leads: [],
    follow_ups: [{
      id: "follow-primary", account_id: primaryId, status: "OPEN",
      created_at: "2026-08-14T10:00:00Z", updated_at: "2026-08-14T10:00:00Z",
    }],
    outreach_drafts: [{
      id: "draft-primary", account_id: primaryId,
      english_draft: "May I share our inspection summary?",
      chinese_explanation: "仅询问是否愿意查看资料。", status: "DRAFT", delivery: "NEVER_SENT",
      created_at: "2026-08-14T10:05:00Z", updated_at: "2026-08-14T10:05:00Z",
    }],
    channel_packages: [], publish_batches: [], metric_receipts: [], field_provenance: [], connectors: [],
  }
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(workspace), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(OpportunitiesPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByRole("heading", { name: "Evidence Buyer GmbH" })).toBeInTheDocument()
  expect(screen.getAllByText("优先跟进 · 88")).toHaveLength(2)
  await user.click(screen.getByRole("button", { name: "查看证据" }))
  expect(screen.getByRole("heading", { name: "评分依据" })).toBeInTheDocument()
  expect(screen.getByText("证据覆盖 18")).toBeInTheDocument()
  expect(screen.getByText("风险扣分 0")).toBeInTheDocument()
  expect(screen.getByText("本地演示样本")).toBeInTheDocument()
  expect(screen.getByText("TED 官方公开数据")).toBeInTheDocument()
  expect(screen.getByText("待人工审查")).toBeInTheDocument()
  expect(screen.getByText("免费公开来源")).toBeInTheDocument()
  expect(screen.getByText("TENDER · 官方招投标")).toBeInTheDocument()
  expect(screen.getByText("gear shaft、helical gear")).toBeInTheDocument()
  expect(screen.getByText("80%")).toBeInTheDocument()
  expect(screen.getByText("无 AI 排除项")).toBeInTheDocument()
  expect(screen.queryByText("MONITORING")).not.toBeInTheDocument()
  expect(screen.getByText("采购时间仍需人工确认")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "打开原始来源" })).toHaveAttribute(
    "href", "https://example.invalid/evidence",
  )
  expect(screen.getByRole("heading", { name: "跟进记录" })).toBeInTheDocument()
  expect(screen.getByText("从未发送")).toBeInTheDocument()
  expect(screen.getByText("May I share our inspection summary?")).toBeInTheDocument()
  expect(screen.getByText("仅询问是否愿意查看资料。")).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: /Thin Evidence SpA/ }))
  expect(screen.getAllByText("继续观察 · 90")).toHaveLength(2)
  await user.click(screen.getByRole("button", { name: "查看证据" }))
  expect(screen.getByText("证据覆盖 10")).toBeInTheDocument()
  expect(screen.getByText("只有单一来源")).toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "打开原始来源" })).not.toBeInTheDocument()
})

it("keeps legacy opportunity evidence usable when score details are missing", async () => {
  const accountId = "10000000-0000-4000-8000-000000001099"
  const workspace = {
    target_accounts: [{
      id: accountId, name: "Legacy Evidence Ltd", country: "United Kingdom",
      industry: "Machinery", employee_range: "11-50", website: "",
      is_demo: true, data_label: "Demo / Fake",
    }],
    contacts: [],
    intent_signals: [{
      id: "legacy-signal", account_id: accountId, signal_type: "MANUAL",
      source_label: "Legacy import", source_url: "", evidence_text: "Imported before score details existed",
      confidence: 61, observed_at: "2026-08-14T07:00:00Z", data_label: "Demo / Fake",
    }],
    inbound_leads: [], follow_ups: [], outreach_drafts: [], channel_packages: [],
    publish_batches: [], metric_receipts: [], field_provenance: [], connectors: [],
  }
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(workspace), {
    status: 200, headers: { "Content-Type": "application/json" },
  })))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(OpportunitiesPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByRole("heading", { name: "Legacy Evidence Ltd" })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "查看证据" }))
  expect(screen.getByText("评分明细暂缺，不能仅凭总分判断。")).toBeInTheDocument()
  expect(screen.getByText("暂未记录不确定项，仍需人工复核原始来源。")).toBeInTheDocument()
})

it("records plain-language human review before an optional Mock CRM handoff", async () => {
  document.cookie = "csrftoken=opportunity-review-test-token"
  const accountId = "10000000-0000-4000-8000-000000009001"
  const workspace = {
    target_accounts: [{
      id: accountId, name: "Jakarta Drive Systems", country: "Indonesia",
      industry: "Industrial equipment", employee_range: "51-200", website: "",
      is_demo: false, data_label: "Licensed / permitted source",
    }],
    contacts: [],
    intent_signals: [{
      id: "signal-review", account_id: accountId, signal_type: "PROCUREMENT_NOTICE",
      source_label: "Official tender", source_url: "https://example.invalid/tender/1",
      evidence_text: "Tender requests custom helical gear components.", confidence: 82,
      observed_at: "2026-08-15T09:00:00Z", data_label: "Licensed / permitted source",
      collection_method: "OFFICIAL_PUBLIC_API", collection_method_label: "官方公开数据接口",
      content_hash: "a".repeat(64), scoring_rule_version: "opportunity-v1",
      score_breakdown: {
        icp_fit: 20, intent_strength: 23, recency: 14,
        role_relevance: 10, evidence_coverage: 17, risk_penalty: 2,
      },
      uncertainty_notes: ["采购数量仍需确认"], priority_label: "优先跟进",
    }],
    inbound_leads: [], follow_ups: [], outreach_drafts: [], opportunity_reviews: [],
    crm_handoffs: [], channel_packages: [], publish_batches: [], metric_receipts: [],
    field_provenance: [], connectors: [],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/review")) {
      const review = {
        id: "review-1", account_id: accountId, signal_id: "signal-review",
        decision: "PRIORITIZE", status_label: "优先跟进", reason: "人工确认为优先跟进",
        original_confidence: 82, original_score_breakdown: workspace.intent_signals[0].score_breakdown,
        created_at: "2026-08-15T10:00:00Z",
      }
      workspace.opportunity_reviews.unshift(review)
      return new Response(JSON.stringify(review), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/draft")) {
      workspace.outreach_drafts.unshift({
        id: "draft-review", account_id: accountId,
        english_draft: "May I confirm your gear component requirements?",
        chinese_explanation: "仅作为人工审核后的联系建议，不会自动发送。",
        status: "DRAFT", delivery: "NEVER_SENT",
        created_at: "2026-08-15T10:01:00Z", updated_at: "2026-08-15T10:01:00Z",
      })
      return new Response(JSON.stringify({
        id: "draft-review", status: "DRAFT",
        "English draft": "May I confirm your gear component requirements?",
        "Chinese explanation": "仅作为人工审核后的联系建议，不会自动发送。",
        delivery: "NEVER_SENT",
      }), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/crm-handoff")) {
      const handoff = {
        id: "handoff-1", account_id: accountId, review_id: "review-1", draft_id: "draft-review",
        connector: "MOCK_CRM", status: "RECORDED", payload_snapshot: {},
        delivery: "NEVER_SENT", created_at: "2026-08-15T10:02:00Z",
      }
      workspace.crm_handoffs.unshift(handoff)
      return new Response(JSON.stringify(handoff), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(OpportunitiesPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByRole("heading", { name: "Jakarta Drive Systems" })).toBeInTheDocument()
  expect(screen.getByText("AI 建议：优先跟进")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "确认优先跟进" }))
  expect(await screen.findByText("人工判断：优先跟进")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "生成联系草稿" }))
  expect(await screen.findByText("May I confirm your gear component requirements?")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "确认草稿并交给 Mock CRM" }))
  expect(await screen.findByText("已保存到 Mock CRM，未发送任何消息。")).toBeInTheDocument()
})

it("loads company provenance and persists human verification", async () => {
  document.cookie = "csrftoken=company-page-test-token"
  const factId = "10000000-0000-4000-8000-000000001403"
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], channel_packages: [], metric_receipts: [], connectors: [],
    field_provenance: [{
      id: factId, field_name: "accuracy_grade", field_value: "DIN 6",
      source_label: "Product library", verification_status: "NEEDS_EVIDENCE",
      source_cost_micros: 20000, created_at: "2026-08-14T08:00:00Z", updated_at: "2026-08-14T08:00:00Z",
    }],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/verify")) {
      return new Response(JSON.stringify({ id: factId, verification_status: "VERIFIED" }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(CompanyPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByText("Product library")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "确认 DIN 6" }))
  await waitFor(() => expect(screen.getByText("已确认", { selector: "span" })).toBeInTheDocument())
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/verify"))).toBe(true)
})

it("shows safe channel connection states and starts authorization without publishing", async () => {
  document.cookie = "csrftoken=connection-state-test-token"
  const channels = ["LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"]
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], metric_receipts: [], publish_batches: [],
    market_pilots: {
      markets: [
        { country_label: "印度尼西亚", status: "ACTIVE_MARKET", suitable_industries: ["工业传动", "矿业设备"], is_demo: true },
        { country_label: "南非", status: "ACTIVE_MARKET", suitable_industries: ["矿业设备", "工业维护"], is_demo: true },
      ],
      validation_goals: { weeks: 8 },
    },
    connectors: [
      { channel: "LINKEDIN", status: "CONNECTED", connection_label: "已连接", recovery_action: "", mode: "OFFICIAL" },
      { channel: "FACEBOOK", status: "CONNECTED", connection_label: "已连接", recovery_action: "", mode: "DEMO_FAKE" },
      { channel: "INSTAGRAM", status: "NOT_CONNECTED", connection_label: "未连接", recovery_action: "连接账号", mode: "" },
      { channel: "TIKTOK", status: "REAUTHORIZATION_REQUIRED", connection_label: "需要重新授权", recovery_action: "重新连接", mode: "OFFICIAL" },
    ],
    channel_packages: channels.map((channel, index) => ({
      id: `20000000-0000-4000-8000-00000000120${index + 1}`,
      account_id: null, channel, payload: channel === "TIKTOK" ? {
        title: "TIKTOK package", duration_seconds: 30, aspect_ratio: "9:16",
        script: "Verified TikTok script", shot_list: ["Gear inspection close-up", "Measurement result"],
        english_voiceover: "Verified English voiceover", chinese_subtitles: "已核对中文字幕",
        hashtags: ["#customgear", "#manufacturing"], cta: "View verified capabilities",
        utm: "utm_source=tiktok&utm_medium=organic&utm_campaign=verified-package",
      } : { title: `${channel} package` },
      status: "APPROVED", is_demo: channel === "FACEBOOK",
      data_label: channel === "FACEBOOK" ? "Demo / Fake" : "Reviewed content package",
      delivery: "MANUAL_ONLY", created_at: "2026-08-14T08:00:00Z", updated_at: "2026-08-14T08:00:00Z",
    })),
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/platform-connections/TIKTOK/authorize") {
      return new Response(JSON.stringify({
        code: "CONFIGURATION_REQUIRED", message: "官方账号连接尚未配置。", recovery_action: "完成平台应用配置后再连接",
      }), { status: 409, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findAllByText("LINKEDIN package")).not.toHaveLength(0)
  expect(screen.getByText("印度尼西亚 + 南非 · 当前试点")).toBeInTheDocument()
  expect(screen.getByText("工业传动、矿业设备、工业维护相关企业")).toBeInTheDocument()
  expect(screen.getByText("8 周市场验证")).toBeInTheDocument()
  expect(screen.queryByText("德国 · 包装机械")).not.toBeInTheDocument()
  const linkedIn = screen.getByRole("article", { name: "LinkedIn Company Page 内容包" })
  const facebook = screen.getByRole("article", { name: "Facebook Page 内容包" })
  const instagram = screen.getByRole("article", { name: "Instagram Business 内容包" })
  const tiktok = screen.getByRole("article", { name: "TikTok 内容包" })
  expect(linkedIn).toHaveTextContent("已连接")
  expect(linkedIn).toHaveTextContent("发布方式：官方接口 · 仍需人工确认")
  expect(facebook).toHaveTextContent("已连接 · Demo / Fake")
  expect(facebook).toHaveTextContent("发布方式：Demo / Fake · 不会真实发布")
  expect(instagram).toHaveTextContent("未连接")
  expect(instagram).toHaveTextContent("发布方式：手工发布包 · 不会调用平台")
  expect(tiktok).toHaveTextContent("需要重新授权")
  expect(tiktok).toHaveTextContent("发布方式：手工发布包 · 不会调用平台")
  expect(tiktok).toHaveTextContent("Verified TikTok script")
  expect(tiktok).toHaveTextContent("Gear inspection close-up · Measurement result")
  expect(tiktok).toHaveTextContent("Verified English voiceover")
  expect(tiktok).toHaveTextContent("已核对中文字幕")
  expect(tiktok).toHaveTextContent("#customgear #manufacturing")
  expect(tiktok).toHaveTextContent("View verified capabilities")
  expect(tiktok).toHaveTextContent("utm_campaign=verified-package")
  expect(tiktok).not.toHaveTextContent("痛点 4 秒")
  expect(screen.getByText("混合发布方式 · 以各渠道状态为准")).toBeInTheDocument()
  expect(screen.queryByText("Fake Connector · 一键发布演示")).not.toBeInTheDocument()
  expect(screen.getByText("当前路径：官方连接 1 个 · Demo 演示 1 个 · 手工发布包 2 个")).toBeInTheDocument()
  const calendar = screen.getByRole("region", { name: "内容日历" })
  expect(calendar).toHaveTextContent("4 个内容包")
  expect(calendar).toHaveTextContent("LINKEDIN package")
  expect(calendar).toHaveTextContent("待安排")
  expect(calendar).not.toHaveTextContent("精密检测如何降低装机返工")
  expect(within(instagram).getByRole("button", { name: "连接 Instagram 账号" })).toBeEnabled()
  await user.click(within(tiktok).getByRole("button", { name: "重新连接 TikTok 账号" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("官方账号连接尚未配置")
  expect(fetchMock.mock.calls.some(([path]) => String(path) === "/api/v1/platform-connections/TIKTOK/authorize")).toBe(true)
  expect(fetchMock.mock.calls.some(([path]) => String(path) === "/api/v1/growth/publish-batches")).toBe(false)
  expect(document.body.textContent?.toLowerCase()).not.toMatch(/access_token|client_secret|oauth scope/)
})

it("requires explicit account selection after authorization and never publishes during connection", async () => {
  document.cookie = "csrftoken=account-picker-test-token"
  window.history.replaceState({}, "", "/promotion?connection_session=30000000-0000-4000-8000-000000000001&connection_status=ready&keep=1")
  let connected = false
  const baseWorkspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], metric_receipts: [], publish_batches: [], channel_packages: [],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify({
        ...baseWorkspace,
        connectors: [
          { channel: "FACEBOOK", status: "NOT_CONNECTED", connection_label: "未连接", recovery_action: "连接账号", mode: "" },
          { channel: "INSTAGRAM", status: connected ? "CONNECTED" : "NOT_CONNECTED", connection_label: connected ? "已连接" : "未连接", recovery_action: connected ? "" : "连接账号", mode: connected ? "OFFICIAL" : "" },
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path === "/api/v1/platform-connection-sessions/30000000-0000-4000-8000-000000000001") {
      return new Response(JSON.stringify({
        id: "30000000-0000-4000-8000-000000000001", platform: "FACEBOOK", platform_name: "Meta",
        expires_at: "2026-08-15T09:10:00Z", candidates: [
          { candidate_id: "30000000-0000-4000-8000-000000000011", display_name: "Acme Facebook", channel: "FACEBOOK", capability_label: "可发布", publication_mode: "PUBLIC" },
          { candidate_id: "30000000-0000-4000-8000-000000000012", display_name: "Acme Instagram", channel: "INSTAGRAM", capability_label: "可发布", publication_mode: "PUBLIC" },
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.endsWith("/confirm")) {
      expect(JSON.parse(String(init?.body))).toEqual({ candidate_id: "30000000-0000-4000-8000-000000000012" })
      connected = true
      return new Response(JSON.stringify({
        platform: "INSTAGRAM", status: "CONNECTED", connection_label: "已连接", recovery_action: "", mode: "OFFICIAL",
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByRole("heading", { name: "选择要用于发布的账号" })).toBeInTheDocument()
  expect(screen.getByRole("radio", { name: /Acme Facebook/ })).toBeChecked()
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/confirm"))).toBe(false)
  await user.click(screen.getByRole("radio", { name: /Acme Instagram/ }))
  await user.click(screen.getByRole("button", { name: "使用此账号" }))

  expect(await screen.findByRole("status")).toHaveTextContent("Acme Instagram 已连接")
  await waitFor(() => expect(screen.queryByRole("heading", { name: "选择要用于发布的账号" })).not.toBeInTheDocument())
  expect(window.location.search).toBe("?keep=1")
  expect(fetchMock.mock.calls.some(([path]) => String(path) === "/api/v1/growth/publish-batches")).toBe(false)
  expect(document.body.textContent?.toLowerCase()).not.toMatch(/access_token|client_secret|oauth scope/)
  window.history.replaceState({}, "", "/promotion")
})

it("shows private-only TikTok readiness and lets the owner leave without connecting", async () => {
  window.history.replaceState({}, "", "/promotion?connection_session=30000000-0000-4000-8000-000000000002&connection_status=ready")
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], metric_receipts: [], publish_batches: [], channel_packages: [], connectors: [],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    if (path.includes("platform-connection-sessions")) {
      return new Response(JSON.stringify({
        id: "30000000-0000-4000-8000-000000000002", platform: "TIKTOK", platform_name: "TikTok",
        expires_at: "2026-08-15T09:10:00Z", candidates: [{
          candidate_id: "30000000-0000-4000-8000-000000000021", display_name: "Acme TikTok",
          channel: "TIKTOK", capability_label: "仅私密发布", publication_mode: "PRIVATE_ONLY",
        }],
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(PromotionPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(await screen.findByText(/仅私密发布/)).toBeInTheDocument()
  expect(screen.getByRole("radio", { name: /Acme TikTok/ })).toBeChecked()
  await user.click(screen.getByRole("button", { name: "暂不连接" }))

  expect(screen.queryByRole("heading", { name: "选择要用于发布的账号" })).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/confirm"))).toBe(false)
  expect(window.location.search).toBe("")
})
