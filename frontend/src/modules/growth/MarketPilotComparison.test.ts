import { render, screen, within } from "@testing-library/vue"
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
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
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(MarketPilotComparison, { props: { summary }, global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

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
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(MarketPilotComparison, { props: { summary, onSelectMarket }, global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

    const indonesia = screen.getByRole("article", { name: "印度尼西亚 强海关数据路线" })
    await user.click(within(indonesia).getByRole("button", { name: "查看该市场候选公司" }))

    expect(onSelectMarket).toHaveBeenCalledWith({ countryCode: "IDN", countryName: "印度尼西亚" })
  })

  it("searches and filters explainable markets, persists watching, and opens the data path", async () => {
    document.cookie = "csrftoken=market-watch-token"
    const user = userEvent.setup()
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      country_code: "USA", is_watched: true, message: "已加入观察市场。",
    }), { status: 200, headers: { "Content-Type": "application/json" } }))
    vi.stubGlobal("fetch", fetchMock)
    const expandedSummary = {
      ...summary,
      markets: [...summary.markets, {
        ...summary.markets[0],
        country_code: "USA", country_label: "美国", status: "OBSERVATION_POOL",
        route: "LICENSED_TRADE", route_label: "海关强数据路线", region: "NORTH_AMERICA",
        path_family: "CUSTOMS_STRONG", suitable_industries: ["工业设备", "包装机械"],
        data_availability_label: "中高：需许可企业级交易数据",
        evidence_note: "研究配置；来源方向为许可交易数据、企业官网与公开采购",
        recommended_action: "查看该市场候选公司并选择许可名单或公开线索路径",
        recommendation_reasons: ["制造业规模大，值得验证"], hold_reasons: ["付费数据尚未接入"],
        is_demo: false, is_watched: false,
      }],
    }
    const onSelectMarket = vi.fn()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(MarketPilotComparison, {
      props: { summary: expandedSummary, onSelectMarket },
      global: { plugins: [[VueQueryPlugin, { queryClient }]] },
    })

    await user.type(screen.getByRole("searchbox", { name: "搜索国家" }), "美国")
    const usa = screen.getByRole("article", { name: "美国 海关强数据路线" })
    expect(within(usa).queryByText("Demo / 研究配置")).not.toBeInTheDocument()
    expect(within(usa).getByText(/工业设备/)).toBeInTheDocument()
    expect(within(usa).getByText(/许可企业级交易数据/)).toBeInTheDocument()
    expect(within(usa).getByText(/来源方向为许可交易数据/)).toBeInTheDocument()
    expect(within(usa).getByText(/付费数据尚未接入/)).toBeInTheDocument()
    await user.click(within(usa).getByRole("button", { name: "加入观察市场" }))
    expect(await within(usa).findByText("已观察")).toBeInTheDocument()
    await user.click(within(usa).getByRole("button", { name: "查看该市场候选公司" }))
    expect(onSelectMarket).toHaveBeenCalledWith({ countryCode: "USA", countryName: "美国" })
  })
})
