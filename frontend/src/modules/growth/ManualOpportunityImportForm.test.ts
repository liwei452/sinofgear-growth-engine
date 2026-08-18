import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import OpportunitiesPage from "./OpportunitiesPage.vue"


const accountId = "10000000-0000-4000-8000-000000009001"
const importedAccount = {
  id: accountId, name: "Buyer Systems GmbH", country: "Germany",
  industry: "Packaging machinery", employee_range: "", website: "",
  is_demo: false, data_label: "Licensed / permitted source",
}
const importedSignal = {
  id: "10000000-0000-4000-8000-000000009002", account_id: accountId,
  signal_type: "MANUAL_EVIDENCE", source_label: "Public company news",
  source_url: "https://example.invalid/news/expansion",
  evidence_text: "The company announced a new packaging line.", confidence: 50,
  observed_at: "2026-08-15T03:00:00Z", data_label: "Licensed / permitted source",
  collection_method: "MANUAL_URL_WITH_SCREENSHOT", collection_method_label: "人工导入网页与截图信息",
  content_hash: "48a8545300b0ee9cd550dafab4b43eccaceb82a9086d6acf547ccd20acbb65e1",
  score_breakdown: {
    icp_fit: 15, intent_strength: 15, recency: 12,
    role_relevance: 3, evidence_coverage: 10, risk_penalty: 5,
  },
  scoring_rule_version: "manual-opportunity-v1",
  uncertainty_notes: ["公司身份仍需人工核实", "采购范围与时间仍需人工确认"],
  evidence_envelope: {
    field_value: "The company announced a new packaging line.",
    source_url: "https://example.invalid/news/expansion",
    source_excerpt: "The company announced a new packaging line.",
    confidence: 50,
    observed_at: "2026-08-15T03:00:00Z",
    source_cost_micros: 0,
    license_contract: "USER_ASSERTED_PERMISSION",
    usage_rights: "INTERNAL_DISCOVERY_WITH_SOURCE_LINK",
    review_status: "PENDING_REVIEW",
    screenshot_reference: {
      file_name: "buyer-expansion.png",
      captured_at: "2026-08-14T01:30:00Z",
      source_url: "https://example.invalid/news/expansion",
      metadata_hash: "a".repeat(64),
    },
  },
  priority_label: "继续观察",
}

function workspace(imported = false) {
  return {
    target_accounts: imported ? [importedAccount] : [],
    contacts: [], intent_signals: imported ? [importedSignal] : [], inbound_leads: [],
    follow_ups: [], outreach_drafts: [], channel_packages: [], publish_batches: [],
    metric_receipts: [], field_provenance: [], connectors: [],
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(OpportunitiesPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
}

async function fillImportForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("公司名称"), "Buyer Systems GmbH")
  await user.type(screen.getByLabelText("国家或地区"), "Germany")
  await user.type(screen.getByLabelText("行业（选填）"), "Packaging machinery")
  await user.type(screen.getByLabelText("来源名称"), "Public company news")
  await user.type(screen.getByLabelText("公开 HTTPS 链接"), "https://example.invalid/news/expansion")
  await user.type(screen.getByLabelText("原始证据摘要"), "The company announced a new packaging line.")
  await user.type(screen.getByLabelText("截图文件名（可选）"), "buyer-expansion.png")
  await fireEvent.update(screen.getByLabelText("截图时间（可选）"), "2026-08-14T09:30")
}

it("imports a permitted public source and selects the persisted conservative opportunity", async () => {
  document.cookie = "csrftoken=manual-opportunity-test-token"
  let imported = false
  let postedBody: Record<string, unknown> | undefined
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace(imported)), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    if (path === "/api/v1/growth/opportunity-imports/manual-url") {
      postedBody = JSON.parse(String(init?.body)) as Record<string, unknown>
      imported = true
      return new Response(JSON.stringify({
        account: importedAccount, signal: importedSignal, created: true,
      }), { status: 201, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  }))
  const user = userEvent.setup()
  renderPage()

  expect(await screen.findByText("人工审核后跟进")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "名单导入" }))
  await user.click(screen.getByRole("button", { name: "导入公开线索" }))
  expect(screen.getByText(/系统不会访问该网页，也不会自动联系客户/)).toBeInTheDocument()
  await fillImportForm(user)
  await user.click(screen.getByRole("button", { name: "保存为待核实机会" }))

  await waitFor(() => expect(postedBody).toEqual({
    company_name: "Buyer Systems GmbH",
    country: "Germany",
    industry: "Packaging machinery",
    source_label: "Public company news",
    source_url: "https://example.invalid/news/expansion",
    evidence_text: "The company announced a new packaging line.",
    screenshot_file_name: "buyer-expansion.png",
    screenshot_captured_at: "2026-08-14T09:30",
  }))
  expect(await screen.findByRole("heading", { name: "Buyer Systems GmbH" })).toBeInTheDocument()
  expect(screen.getAllByText("继续观察 · 50")).toHaveLength(2)
  expect(screen.getByText("许可 / 用户提供来源")).toBeInTheDocument()
  expect(screen.getByRole("status")).toHaveTextContent("已保存为待核实机会")
  expect(screen.queryByLabelText("公司名称")).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "查看证据" }))
  expect(screen.getByText(/buyer-expansion\.png/)).toHaveTextContent("仅元数据")
})

it("keeps the form values and shows field guidance when an import fails", async () => {
  document.cookie = "csrftoken=manual-opportunity-error-token"
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === "/api/v1/growth/workspace") {
      return new Response(JSON.stringify(workspace()), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }
    if (path === "/api/v1/growth/opportunity-imports/manual-url") {
      return new Response(JSON.stringify({
        code: "INVALID_MANUAL_OPPORTUNITY",
        message: "公开来源必须使用 HTTPS。",
        recovery_action: "Correct the request and try again.",
        errors: { source_url: ["公开来源必须使用 HTTPS。"] },
      }), { status: 400, headers: { "Content-Type": "application/json" } })
    }
    throw new Error(`Unexpected request: ${path}`)
  }))
  const user = userEvent.setup()
  renderPage()

  await screen.findByText("人工审核后跟进")
  await user.click(screen.getByRole("button", { name: "名单导入" }))
  await user.click(screen.getByRole("button", { name: "导入公开线索" }))
  await fillImportForm(user)
  await user.click(screen.getByRole("button", { name: "保存为待核实机会" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("公开来源必须使用 HTTPS。")
  expect(screen.getByText("公开来源必须使用 HTTPS。", { selector: "small" })).toBeInTheDocument()
  expect(screen.getByLabelText("公司名称")).toHaveValue("Buyer Systems GmbH")
  expect(screen.getByLabelText("原始证据摘要")).toHaveValue(
    "The company announced a new packaging line.",
  )
  await user.click(screen.getByRole("button", { name: "取消" }))
  expect(screen.queryByLabelText("公司名称")).not.toBeInTheDocument()
})
