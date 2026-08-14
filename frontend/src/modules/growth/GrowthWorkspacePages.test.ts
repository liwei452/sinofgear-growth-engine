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
  expect(screen.getByText("德国包装机械制造商 · 51–500 人")).toBeInTheDocument()
  const tiktok = screen.getByRole("article", { name: "TikTok 内容包" })
  expect(tiktok).toHaveTextContent("15–60 秒")
  expect(tiktok).toHaveTextContent("9:16")
  expect(tiktok).toHaveTextContent("英文口播")
  expect(tiktok).toHaveTextContent("中文字幕")
  expect(tiktok).toHaveTextContent("分镜")
  expect(tiktok).toHaveTextContent("标题 / 标签 / CTA")
  expect(tiktok).toHaveTextContent("UTM")
  expect(tiktok).toHaveTextContent("手工发布包")
  expect(tiktok).toHaveTextContent("Fake Connector")
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

it("explains effectiveness denominators and low-sample uncertainty", () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(EffectivenessPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  expect(screen.getByRole("heading", { name: "推广效果" })).toBeInTheDocument()
  expect(screen.getByText("点击 186 / 已发布内容包 12")).toBeInTheDocument()
  expect(screen.getByText("回复 9 / 已人工触达 34")).toBeInTheDocument()
  expect(screen.getByText("询盘 3 / 落地页访问 186")).toBeInTheDocument()
  expect(screen.getByText("样本不足，暂不自动调整策略")).toBeInTheDocument()
  expect(screen.getByText(/2026-08-08 至 2026-08-14/)).toBeInTheDocument()
})

it("persists content-package approval and manual metric backfill", async () => {
  document.cookie = "csrftoken=growth-pages-test-token"
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], connectors: [], metric_receipts: [],
    channel_packages: [{
      id: "10000000-0000-4000-8000-000000001201", account_id: null, channel: "TIKTOK",
      payload: { duration_seconds: 30, aspect_ratio: "9:16", title: "API TikTok package" },
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
})

it("publishes all approved channels once and retries only failed channels", async () => {
  document.cookie = "csrftoken=one-click-publish-test-token"
  const channels = ["LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"]
  const workspace = {
    target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
    outreach_drafts: [], field_provenance: [], metric_receipts: [],
    connectors: channels.map(channel => ({ channel, status: "FAKE_CONNECTOR", mode: "ONE_CLICK_DEMO" })),
    channel_packages: channels.map((channel, index) => ({
      id: `10000000-0000-4000-8000-00000000120${index + 1}`,
      account_id: null,
      channel,
      payload: { title: `${channel} inspection proof` },
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

  await user.click(await screen.findByRole("button", { name: "一键发布到 4 个渠道" }))

  expect(await screen.findByText("Demo / Fake 发布结果")).toBeInTheDocument()
  expect(screen.getByText("3 个渠道发布成功，1 个渠道需要重试。")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "查看 LinkedIn Demo 帖子" })).toHaveAttribute("href", expect.stringContaining("example.invalid"))
  await user.click(screen.getByRole("button", { name: "重试失败渠道" }))
  expect(await screen.findByText("4 个渠道均已发布成功。")).toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([path]) => String(path) === "/api/v1/growth/publish-batches")).toHaveLength(1)
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
