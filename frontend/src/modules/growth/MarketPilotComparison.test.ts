import { render, screen, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import MarketPilotComparison from "./MarketPilotComparison.vue"

const summary = {
  markets: [
    { country_code: "IDN", country_label: "印度尼西亚", status: "ACTIVE_MARKET", route: "STRONG_CUSTOMS_DATA", route_label: "强海关数据路线", recommended_wave: "当前试点", source_types: ["DIRECT_CUSTOMS"], last_updated_at: "2026-08-15", scores: {}, sample_quality: { raw_sample_count: 0, named_buyer_rate: null, active_entity_match_rate: null, duplicate_rate: null, evidence_company_count: 0, evidence_company_threshold: 20 }, recommendation_reasons: ["验证交易数据路线"], hold_reasons: ["需核验许可"], metrics: { effective_customer_rate: null, positive_reply_rate: null, source_cost_micros: 0, raw_sample_count: 0 } },
    { country_code: "ZAF", country_label: "南非", status: "ACTIVE_MARKET", route: "MIXED_SIGNALS", route_label: "混合信号路线", recommended_wave: "当前试点", source_types: ["AGGREGATE_TRADE", "TENDER", "COMPANY_WEB"], last_updated_at: "2026-08-15", scores: {}, sample_quality: { raw_sample_count: 0, named_buyer_rate: null, active_entity_match_rate: null, duplicate_rate: null, evidence_company_count: 0, evidence_company_threshold: 20 }, recommendation_reasons: ["验证混合信号路线"], hold_reasons: ["宏观数据不是公司证据"], metrics: { effective_customer_rate: null, positive_reply_rate: null, source_cost_micros: 0, raw_sample_count: 0 } },
    { country_code: "CHL", country_label: "智利", status: "DATA_VALIDATION", route: "TRADE_TENDER_WEB", route_label: "交易数据 + 招投标 + 官网", recommended_wave: "下一优先", source_types: ["CARRIER_BOL", "TENDER", "COMPANY_WEB"], last_updated_at: "2026-08-15", scores: {}, sample_quality: { raw_sample_count: 0, named_buyer_rate: null, active_entity_match_rate: null, duplicate_rate: null, evidence_company_count: 0, evidence_company_threshold: 20 }, recommendation_reasons: ["矿业 MRO 与开放采购信号完整"], hold_reasons: ["等待 200 条样本"], metrics: { effective_customer_rate: null, positive_reply_rate: null, source_cost_micros: 0, raw_sample_count: 0 } },
    { country_code: "VNM", country_label: "越南", status: "DATA_VALIDATION", route: "SECOND_PHASE", route_label: "第二阶段", recommended_wave: "第二阶段", source_types: ["CARRIER_BOL"], last_updated_at: "2026-08-15", scores: {}, sample_quality: { raw_sample_count: 0, named_buyer_rate: null, active_entity_match_rate: null, duplicate_rate: null, evidence_company_count: 0, evidence_company_threshold: 20 }, recommendation_reasons: ["制造业需求"], hold_reasons: ["需核验新鲜度"], metrics: { effective_customer_rate: null, positive_reply_rate: null, source_cost_micros: 0, raw_sample_count: 0 } },
    { country_code: "PHL", country_label: "菲律宾", status: "DATA_VALIDATION", route: "SECOND_PHASE", route_label: "第二阶段", recommended_wave: "第二阶段", source_types: ["DIRECT_CUSTOMS"], last_updated_at: "2026-08-15", scores: {}, sample_quality: { raw_sample_count: 0, named_buyer_rate: null, active_entity_match_rate: null, duplicate_rate: null, evidence_company_count: 0, evidence_company_threshold: 20 }, recommendation_reasons: ["供应商覆盖"], hold_reasons: ["需核验许可"], metrics: { effective_customer_rate: null, positive_reply_rate: null, source_cost_micros: 0, raw_sample_count: 0 } },
    { country_code: "IND", country_label: "印度", status: "OBSERVATION_POOL", route: "CONDITIONAL_TENDER_WEB", route_label: "条件市场", recommended_wave: "条件观察", source_types: ["TENDER", "COMPANY_WEB"], last_updated_at: "2026-08-15", scores: {}, sample_quality: { raw_sample_count: 0, named_buyer_rate: null, active_entity_match_rate: null, duplicate_rate: null, evidence_company_count: 0, evidence_company_threshold: 20 }, recommendation_reasons: ["需求与招投标价值高"], hold_reasons: ["主体报关数据需要可核验授权与合同许可"], metrics: { effective_customer_rate: null, positive_reply_rate: null, source_cost_micros: 0, raw_sample_count: 0 } },
  ],
  score_weights: { data_availability: 25, demand_strength: 25, purchase_intent: 20, company_reachability: 15, commercial_execution: 15 },
  quality_gate: { minimum_raw_samples: 200, minimum_named_buyer_rate: 80, minimum_active_entity_match_rate: 70, maximum_median_record_age_days: 90, maximum_duplicate_rate: 10, license_required: true },
  search_policy: { hs_codes: ["848340", "848390"], include_terms: ["gear shaft"], exclude_terms: ["complete gearbox"] },
  validation_goals: { reviewed_valid_companies: 50, sales_conversations: 15, positive_intent_signals: 5, progressed_opportunities: 2, weeks: 8 },
}

describe("MarketPilotComparison", () => {
  it("compares two active routes without inventing rates and keeps phase two gated", () => {
    render(MarketPilotComparison, { props: { summary } })

    const indonesia = screen.getByRole("article", { name: "印度尼西亚 强海关数据路线" })
    const southAfrica = screen.getByRole("article", { name: "南非 混合信号路线" })
    for (const card of [indonesia, southAfrica]) {
      expect(within(card).getByText("有效客户率")).toBeInTheDocument()
      expect(within(card).getByText("积极回复率")).toBeInTheDocument()
      expect(within(card).getAllByText("待采样")).toHaveLength(2)
      expect(within(card).getByText("来源成本")).toBeInTheDocument()
      expect(within(card).getByText("¥0.00")).toBeInTheDocument()
    }
    expect(screen.getByText("市场雷达")).toBeInTheDocument()
    expect(screen.getByText("智利 · 下一优先")).toBeInTheDocument()
    expect(screen.getByText("印度 · 条件观察")).toBeInTheDocument()
    expect(screen.getByText("数据可获得性 25% · 需求强度 25% · 采购意图 20% · 企业可触达性 15% · 商业可执行性 15%" )).toBeInTheDocument()
    expect(screen.getByText("主体报关数据需要可核验授权与合同许可")).toBeInTheDocument()
    expect(screen.queryByText("INDIA DIRECT_CUSTOMS")).not.toBeInTheDocument()
  })

  it("opens the candidate entry for any selected market", async () => {
    const user = userEvent.setup()
    const onSelectMarket = vi.fn()
    render(MarketPilotComparison, { props: { summary, onSelectMarket } })

    const indonesia = screen.getByRole("article", { name: "印度尼西亚 强海关数据路线" })
    await user.click(within(indonesia).getByRole("button", { name: "查看该市场候选公司" }))

    expect(onSelectMarket).toHaveBeenCalledWith({ countryCode: "IDN", countryName: "印度尼西亚" })
  })
})
