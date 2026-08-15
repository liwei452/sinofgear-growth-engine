import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, within } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import ReactivationWorkbench from "./ReactivationWorkbench.vue"


const accounts = [
  { id: "account-1", name: "PackTech GmbH", country: "Germany", industry: "Packaging machinery", employee_range: "51-200", website: "", is_demo: true, data_label: "Demo / Fake" },
  { id: "account-2", name: "NordMotion AB", country: "Sweden", industry: "Automation equipment", employee_range: "51-200", website: "", is_demo: true, data_label: "Demo / Fake" },
]

function renderWorkbench(reactivations: Array<Record<string, unknown>> = []) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(ReactivationWorkbench, {
    props: { accounts, reactivations },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

it("selects a lawful dormant account, prepares a draft, and records approval without sending", async () => {
  document.cookie = "csrftoken=reactivation-token"
  const user = userEvent.setup()
  const selected = {
    id: "reactivation-1", account_id: "account-1", account_name: "PackTech GmbH",
    industry: "Packaging machinery", relationship_source: "PAST_INQUIRY",
    last_interacted_at: "2026-04-15T08:00:00Z",
    interaction_summary: "Discussed gear samples at the 2025 trade fair.",
    tier: "STRATEGIC", status: "SELECTED", is_demo: true,
    why_reactivate: "Existing lawful relationship plus saved account context",
    recommended_action: "Prepare a human-reviewed reactivation draft",
    evidence: "Verified public company update", risk: "Verify stale context before contact",
    draft: null, events: [{ event_type: "REACTIVATION_SELECTED", created_at: "2026-08-15T08:00:00Z", delivery: "NEVER_SENT" }],
    delivery: "NEVER_SENT",
  }
  const drafted = {
    id: "reactivation-1", draft_id: "draft-1", status: "DRAFTED", draft_status: "DRAFT",
    english_draft: "Hello PackTech GmbH team, following up on our 2025 trade fair discussion.",
    chinese_explanation: "只引用已有历史互动，不声称存在采购意向。", delivery: "NEVER_SENT",
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith("/draft")) return new Response(JSON.stringify(drafted), { status: 201, headers: { "Content-Type": "application/json" } })
    if (url.endsWith("/approve")) return new Response(JSON.stringify({ id: "reactivation-1", status: "APPROVED", draft_status: "APPROVED", delivery: "NEVER_SENT", message: "Draft approved for future manual sending; nothing was sent." }), { status: 200, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify(selected), { status: 201, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  renderWorkbench()

  await user.selectOptions(screen.getByLabelText("已有关系账户"), "account-1")
  await user.selectOptions(screen.getByLabelText("关系来源"), "PAST_INQUIRY")
  await user.type(screen.getByLabelText("最后互动时间"), "2026-04-15T16:00")
  await user.type(screen.getByLabelText("历史互动摘要"), "Discussed gear samples at the 2025 trade fair.")
  await user.click(screen.getByRole("checkbox", { name: "确认这是已有关系或合法自有名单" }))
  await user.click(screen.getByRole("button", { name: "加入重新激活" }))

  const card = await screen.findByRole("article", { name: "PackTech GmbH 重新激活" })
  expect(within(card).getByText("Demo / Fake")).toBeInTheDocument()
  expect(within(card).getByText(/战略账户/)).toBeInTheDocument()
  expect(within(card).getByText(/绝不自动发送/)).toBeInTheDocument()
  await user.click(within(card).getByRole("button", { name: "生成待审草稿" }))
  expect(await within(card).findByText(/Hello PackTech GmbH team/)).toBeInTheDocument()
  await user.click(within(card).getByRole("button", { name: "人工批准草稿" }))
  expect(await within(card).findByText("已批准，未发送")).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(3)
})

it("keeps observation accounts in evidence completion and does not offer a draft action", () => {
  renderWorkbench([{
    id: "reactivation-2", account_id: "account-2", account_name: "NordMotion AB",
    industry: "Automation equipment", relationship_source: "OWNED_CRM",
    last_interacted_at: "2026-01-15T08:00:00Z",
    interaction_summary: "Historical CRM conversation.", tier: "OBSERVATION", status: "SELECTED",
    is_demo: true, why_reactivate: "Existing lawful relationship plus saved account context",
    recommended_action: "Complete account evidence before outreach",
    evidence: "No verified recent signal saved", risk: "Evidence is insufficient",
    draft: null, events: [], delivery: "NEVER_SENT",
  }])

  const card = screen.getByRole("article", { name: "NordMotion AB 重新激活" })
  expect(within(card).getByText("Automation equipment · 观察账户")).toBeInTheDocument()
  expect(within(card).getByText(/只建议补全/)).toBeInTheDocument()
  expect(within(card).queryByRole("button", { name: "生成待审草稿" })).not.toBeInTheDocument()
})
