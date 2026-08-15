import { render, screen, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it } from "vitest"

import type { GrowthWorkspace } from "./api"
import AccountAttributionPanel from "./AccountAttributionPanel.vue"

const workspace: GrowthWorkspace = {
  target_accounts: [
    { id: "account-pack", name: "PackTech GmbH", country: "Germany", industry: "Packaging machinery", employee_range: "51-200", website: "", is_demo: true, data_label: "Demo / Fake" },
    { id: "account-nord", name: "NordMotion AB", country: "Sweden", industry: "Automation equipment", employee_range: "51-200", website: "", is_demo: true, data_label: "Demo / Fake" },
  ],
  contacts: [],
  intent_signals: [{
    id: "signal-pack", account_id: "account-pack", signal_type: "TENDER",
    source_label: "TED 官方公开数据", source_url: "https://example.invalid/tender",
    evidence_text: "公开招标提及 helical gear", confidence: 88, observed_at: "2026-08-14T09:20:00Z",
    data_label: "Demo / Fake", collection_method: "DEMO_FIXTURE", collection_method_label: "本地演示样本",
    content_hash: "a".repeat(64), scoring_rule_version: "opportunity-v1",
    score_breakdown: { icp_fit: 25, intent_strength: 25, recency: 20, role_relevance: 10, evidence_coverage: 18, risk_penalty: 0 },
    uncertainty_notes: [], priority_label: "优先跟进",
    evidence_envelope: {
      field_value: "helical gear", source_url: "https://example.invalid/tender", source_excerpt: "公开招标提及 helical gear",
      confidence: 88, observed_at: "2026-08-14T09:20:00Z", source_cost_micros: 1500,
      license_contract: "PUBLIC_TENDER", usage_rights: "INTERNAL_DISCOVERY", review_status: "REVIEWED",
      queue: "MONITORING", source_type: "TENDER",
    },
  }],
  inbound_leads: [],
  follow_ups: [{ id: "follow-pack", account_id: "account-pack", status: "OPEN", created_at: "2026-08-15T08:10:00Z", updated_at: "2026-08-15T08:10:00Z" }],
  outreach_drafts: [{ id: "draft-pack", account_id: "account-pack", english_draft: "Hello PackTech team", chinese_explanation: "仅引用已有事实。", status: "DRAFT", delivery: "NEVER_SENT", created_at: "2026-08-15T08:20:00Z", updated_at: "2026-08-15T08:20:00Z" }],
  reactivations: [
    {
      id: "react-pack", account_id: "account-pack", account_name: "PackTech GmbH", industry: "Packaging machinery",
      relationship_source: "PAST_INQUIRY", last_interacted_at: "2026-04-15T08:00:00Z", interaction_summary: "2025 展会讨论过齿轮样品。",
      tier: "STRATEGIC", status: "APPROVED", is_demo: true, why_reactivate: "已有合法关系与近期证据",
      recommended_action: "人工选择发送渠道", evidence: "TED 官方公开数据 · 2026-08-14", risk: "发送前复核时效",
      draft: { id: "draft-react-pack", english_draft: "Following up on our 2025 discussion.", chinese_explanation: "没有声称当前采购。", status: "APPROVED" },
      events: [
        { event_type: "REACTIVATION_SELECTED", created_at: "2026-08-15T08:00:00Z", delivery: "NEVER_SENT" },
        { event_type: "REACTIVATION_DRAFTED", created_at: "2026-08-15T08:20:00Z", delivery: "NEVER_SENT" },
        { event_type: "REACTIVATION_APPROVED", created_at: "2026-08-15T08:30:00Z", delivery: "NEVER_SENT" },
      ],
      delivery: "NEVER_SENT",
    },
    {
      id: "react-nord", account_id: "account-nord", account_name: "NordMotion AB", industry: "Automation equipment",
      relationship_source: "OWNED_CRM", last_interacted_at: "2026-01-15T08:00:00Z", interaction_summary: "自有 CRM 历史沟通。",
      tier: "OBSERVATION", status: "SELECTED", is_demo: true, why_reactivate: "已有合法关系但证据不足",
      recommended_action: "补全公司与近期证据", evidence: "没有已验证近期信号", risk: "证据不足，不应触达",
      draft: null, events: [{ event_type: "REACTIVATION_SELECTED", created_at: "2026-08-15T09:00:00Z", delivery: "NEVER_SENT" }],
      delivery: "NEVER_SENT",
    },
  ],
  opportunity_reviews: [],
  crm_handoffs: [{ id: "handoff-pack", account_id: "account-pack", review_id: "review-pack", draft_id: "draft-pack", connector: "MOCK_CRM", status: "RECORDED", payload_snapshot: {}, delivery: "NEVER_SENT", created_at: "2026-08-15T08:31:00Z" }],
  channel_packages: [], publish_batches: [], metric_receipts: [], connectors: [],
  field_provenance: [{ id: "field-pack", field_name: "industry", field_value: "Packaging machinery", source_label: "公司官网", verification_status: "VERIFIED", source_cost_micros: 500, created_at: "2026-08-14T08:00:00Z", updated_at: "2026-08-14T08:00:00Z" }],
  discovery: {
    enabled: true, source_label: "许可名单与公开线索", schedule_label: "手工", product_scope_label: "齿轮", next_run_at: null, last_run: null,
    available_sources: [],
    candidates: [
      { id: "candidate-a", company_name: "Licensed Gears Ltd", country: "United Kingdom", website: "https://example.invalid", industry: "Machinery", status: "ACCEPTED", status_label: "待补全公司资料", source_owner: "Factory research", license_contract: "PUBLIC_DIRECTORY", import_format: "CSV", is_demo: false, created_at: "2026-08-15T07:00:00Z" },
      { id: "candidate-b", company_name: "Demo Motion Inc", country: "United States", website: "", industry: "Automation", status: "PENDING_REVIEW", status_label: "待人工核实", source_owner: "Demo fixture", license_contract: "DEMO_ONLY", import_format: "JSON", is_demo: true, created_at: "2026-08-15T07:10:00Z" },
    ],
    enrichment_candidates: [{ id: "candidate-a", company_name: "Licensed Gears Ltd", country: "United Kingdom", website: "https://example.invalid", industry: "Machinery", status: "ACCEPTED", status_label: "待补全公司资料", source_owner: "Factory research", license_contract: "PUBLIC_DIRECTORY", import_format: "CSV", is_demo: false, created_at: "2026-08-15T07:00:00Z", latest_preview: { candidate_id: "candidate-a", mode: "FAKE_PREVIEW", data_label: "Demo / Fake enrichment preview", facts: [{ field: "website", value: "https://example.invalid", source: "submitted list" }], public_contact_paths: [], uncertainties: [], message: "preview", created: true } }],
  },
}

it("shows only recorded funnel facts and explains unavailable outcome denominators", () => {
  render(AccountAttributionPanel, { props: { workspace } })

  const region = screen.getByRole("region", { name: "账户获客漏斗" })
  expect(within(region).getByRole("button", { name: /候选 2/ })).toBeInTheDocument()
  expect(within(region).getByRole("button", { name: /人工核实 1/ })).toBeInTheDocument()
  expect(within(region).getByRole("button", { name: /资料补全 1/ })).toBeInTheDocument()
  expect(within(region).getByRole("button", { name: /加入跟进 1/ })).toBeInTheDocument()
  expect(within(region).getByRole("button", { name: /草稿生成 1/ })).toBeInTheDocument()
  expect(within(region).getByRole("button", { name: /人工批准 1/ })).toBeInTheDocument()
  expect(within(region).getByRole("button", { name: /人工发送 尚未发生/ })).toBeInTheDocument()
  expect(within(region).getByRole("button", { name: /回复 尚未发生/ })).toBeInTheDocument()
  expect(within(region).getByRole("button", { name: /有效需求 尚未发生/ })).toBeInTheDocument()
  expect(within(region).getByText("有效账户率 50%")).toBeInTheDocument()
  expect(within(region).getByText("草稿批准率 100%")).toBeInTheDocument()
  expect(within(region).getByText("证据覆盖率 50%")).toBeInTheDocument()
  expect(within(region).getByText("数据成本 $0.002")).toBeInTheDocument()
  expect(within(region).getByText("积极回复率 无数据")).toBeInTheDocument()
  expect(within(region).getByText("需求率 无数据")).toBeInTheDocument()
})

it("filters evidence details without mixing demo and licensed records", async () => {
  const user = userEvent.setup()
  render(AccountAttributionPanel, { props: { workspace } })
  const region = screen.getByRole("region", { name: "账户获客漏斗" })

  const packTech = within(region).getByRole("article", { name: "PackTech GmbH 归因记录" })
  expect(within(packTech).getByText("人工批准")).toBeInTheDocument()
  expect(within(packTech).getByText("已批准，尚未发送")).toBeInTheDocument()
  const nord = within(region).getByRole("article", { name: "NordMotion AB 归因记录" })
  expect(within(nord).getByText("补全证据")).toBeInTheDocument()

  await user.selectOptions(within(region).getByLabelText("数据性质"), "RECORDED")
  expect(within(region).queryByRole("article", { name: "PackTech GmbH 归因记录" })).not.toBeInTheDocument()
  expect(within(region).getByRole("article", { name: "Licensed Gears Ltd 候选记录" })).toBeInTheDocument()

  await user.selectOptions(within(region).getByLabelText("数据性质"), "ALL")
  await user.click(within(region).getByRole("button", { name: /人工批准 1/ }))
  expect(within(region).getByRole("article", { name: "PackTech GmbH 归因记录" })).toBeInTheDocument()
  expect(within(region).queryByRole("article", { name: "NordMotion AB 归因记录" })).not.toBeInTheDocument()
  expect(within(region).getByText("TED 官方公开数据 · 2026-08-14")).toBeInTheDocument()
})

it("keeps progressed records visible when drilling into an earlier funnel stage", async () => {
  const user = userEvent.setup()
  render(AccountAttributionPanel, { props: { workspace } })
  const region = screen.getByRole("region", { name: "账户获客漏斗" })

  await user.click(within(region).getByRole("button", { name: /候选 2/ }))
  expect(within(region).getByRole("article", { name: "Licensed Gears Ltd 候选记录" })).toBeInTheDocument()
  expect(within(region).getByRole("article", { name: "Demo Motion Inc 候选记录" })).toBeInTheDocument()

  await user.click(within(region).getByRole("button", { name: /候选 2/ }))
  await user.click(within(region).getByRole("button", { name: /草稿生成 1/ }))
  expect(within(region).getByRole("article", { name: "PackTech GmbH 归因记录" })).toHaveTextContent("人工批准")
})
