import { render, screen, waitFor, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import TradeMarketEvidencePanel from "./TradeMarketEvidencePanel.vue"


const markets = [
  { country_code: "IDN", country_label: "印度尼西亚" },
  { country_code: "ZAF", country_label: "南非" },
]

const empty = {
  status: "NO_DATA",
  is_demo: false,
  scope_warning: "宏观贸易仅用于市场判断，不是具体买家证据。",
  indicators: {},
  evidence: [],
}

const ready = {
  status: "READY",
  is_demo: true,
  scope_warning: "宏观贸易仅用于市场判断，不是具体买家证据。",
  indicators: {
    import_scale: {
      formula: "sum(latest world import values)", value_usd: "225000.00",
      inputs: { period: "2024", world_values: ["125000.00", "100000.00"] },
    },
    year_over_year: {
      formula: "(current - previous) / previous * 100", value_percent: "25.00",
      inputs: { current: "225000.00", previous: "180000.00" },
    },
    continuity: {
      formula: "observed requested periods / requested periods * 100", value_percent: "100.00",
      inputs: { observed_periods: ["2023", "2024"], requested_periods: ["2023", "2024"] },
    },
    freshness: {
      formula: "as_of date - latest observed period end", value_days: 593,
      inputs: { as_of: "2026-08-16", latest_observed_at: "2024-12-31" },
    },
    china_share: {
      formula: "China import value / world import value * 100", value_percent: "40.00",
      inputs: { china_value: "90000.00", world_value: "225000.00" },
    },
  },
  evidence: [{
    id: "snapshot-1", reporter_code: "360", partner_code: "0", hs_code: "848340",
    period: "2024", trade_value_usd: "125000.00",
    source_url: "https://comtradeplus.un.org/TradeFlow?reporterCode=360",
    source_dataset: "UN_COMTRADE_FIXTURE", dataset_version: "FIXTURE-2026-08-16",
    fetched_at: "2026-08-16T00:00:00Z", is_demo: true,
  }],
}


describe("TradeMarketEvidencePanel", () => {
  it("shows an honest empty state with default HS codes and no buyer implication", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(empty), {
      status: 200, headers: { "Content-Type": "application/json" },
    })))

    render(TradeMarketEvidencePanel, { props: { markets } })

    await userEvent.setup().click(screen.getByRole("button", { name: "查看市场贸易证据" }))
    expect(await screen.findByText("当前没有官方贸易快照")).toBeInTheDocument()
    expect(screen.getByText("宏观贸易仅用于市场判断，不是具体买家证据。")).toBeInTheDocument()
    expect(screen.getByDisplayValue("848340, 848390")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "同步公开贸易数据" })).toBeEnabled()
    expect(screen.getByText("用于判断市场规模和变化，不会生成买家公司、联系人或采购意向。")).toBeInTheDocument()
  })

  it("labels fixture evidence, exposes formulas and keeps source links after reload", async () => {
    document.cookie = "csrftoken=trade-panel-token"
    let synced = false
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === "/api/v1/growth/trade-syncs" && init?.method === "POST") {
        synced = true
        return new Response(JSON.stringify({
          mode: "FIXTURE", is_demo: true, run_ids: ["run-1"], snapshot_ids: ["snapshot-1"],
          created_snapshot_count: 6, reused_snapshot_count: 0,
          scope_warning: "宏观贸易仅用于市场判断，不是具体买家证据。",
        }), { status: 201, headers: { "Content-Type": "application/json" } })
      }
      if (path.startsWith("/api/v1/growth/trade-indicators")) {
        return new Response(JSON.stringify(synced ? ready : empty), {
          status: 200, headers: { "Content-Type": "application/json" },
        })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal("fetch", fetchMock)
    const user = userEvent.setup()

    const view = render(TradeMarketEvidencePanel, { props: { markets } })
    await user.click(screen.getByRole("button", { name: "查看市场贸易证据" }))
    await screen.findByText("当前没有官方贸易快照")
    await user.click(screen.getByRole("button", { name: "同步公开贸易数据" }))

    expect(await screen.findByText("Demo / Fake 数据")).toBeInTheDocument()
    expect(screen.getByText("25.00%")).toBeInTheDocument()
    expect(screen.getByText("(本期 - 上年同期) / 上年同期 × 100%")).toBeInTheDocument()
    const evidence = screen.getByRole("region", { name: "公开贸易证据" })
    expect(within(evidence).getByRole("link", { name: "查看 UN Comtrade 原始来源" })).toHaveAttribute(
      "href", "https://comtradeplus.un.org/TradeFlow?reporterCode=360",
    )
    view.unmount()
    render(TradeMarketEvidencePanel, { props: { markets } })
    await user.click(screen.getByRole("button", { name: "查看市场贸易证据" }))
    await waitFor(() => expect(screen.getByText("Demo / Fake 数据")).toBeInTheDocument())
    expect(fetchMock.mock.calls.filter(([input]) => String(input).startsWith("/api/v1/growth/trade-indicators"))).toHaveLength(3)
  })

  it("explains that the connector is not configured instead of loading demo fallback", async () => {
    document.cookie = "csrftoken=trade-panel-disabled-token"
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.startsWith("/api/v1/growth/trade-indicators")) {
        return new Response(JSON.stringify(empty), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      return new Response(JSON.stringify({
        code: "CONFIGURATION_REQUIRED", message: "公开贸易数据源尚未启用。",
        recovery_action: "由管理员明确启用官方公共数据连接器；当前不会自动加载演示数据。",
      }), { status: 503, headers: { "Content-Type": "application/json" } })
    })
    vi.stubGlobal("fetch", fetchMock)
    const user = userEvent.setup()
    render(TradeMarketEvidencePanel, { props: { markets } })
    await user.click(screen.getByRole("button", { name: "查看市场贸易证据" }))
    await screen.findByText("当前没有官方贸易快照")

    await user.click(screen.getByRole("button", { name: "同步公开贸易数据" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("公开贸易连接器未配置")
    expect(screen.getByRole("alert")).toHaveTextContent("不会自动加载演示数据")
    expect(screen.queryByText("Demo / Fake 数据")).not.toBeInTheDocument()
  })
})
