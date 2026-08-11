import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import type { LeadCandidateDetail } from "./api"
import LeadHandoffPanel from "./LeadHandoffPanel.vue"

const detail = {
  id: "lead-1", company: { name: "ABC Packaging", domain: "abc.example", country_hint: "DE" },
  status: "REVIEWED", version: 2, created_at: "2026-08-10T00:00:00Z", updated_at: "2026-08-10T01:00:00Z",
  permitted_actions: [], evidence: [], requirements: [], review_history: [], insight_history: [], latest_insight: null,
} satisfies LeadCandidateDetail

afterEach(() => vi.unstubAllGlobals())

it("does not claim CRM delivery or emit a mutation when no connector exists", async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)
  const view = render(LeadHandoffPanel, {
    props: { detail, canHandoff: true, connectorConfigured: false },
  })

  await userEvent.click(screen.getByRole("button", { name: "交给 CRM" }))

  expect(screen.getByText("CRM 尚未配置，当前不会发送客户资料。")).toBeVisible()
  expect(screen.queryByText("交接成功")).not.toBeInTheDocument()
  expect(view.emitted("handoff")).toBeUndefined()
  expect(fetchMock).not.toHaveBeenCalled()
  expect(screen.getByRole("button", { name: "下载 JSON" })).toBeVisible()
  expect(screen.getByRole("button", { name: "下载 CSV" })).toBeVisible()
  expect(screen.getByRole("link", { name: "前往高级设置了解接入方式" })).toHaveAttribute("href", "#crm-connector-help")
  expect(screen.getByRole("heading", { name: "高级设置说明" })).toBeVisible()
  expect(screen.getByText(/后端连接器能力验证通过前，只能下载本地文件/)).toBeVisible()
})

it("defines the future connector event but never emits it without permission", async () => {
  const allowed = render(LeadHandoffPanel, {
    props: { detail, canHandoff: true, connectorConfigured: true },
  })
  await userEvent.click(screen.getByRole("button", { name: "交给 CRM" }))
  expect(allowed.emitted("handoff")).toEqual([[detail]])
  allowed.unmount()

  const denied = render(LeadHandoffPanel, {
    props: { detail, canHandoff: false, connectorConfigured: true },
  })
  expect(screen.getByRole("button", { name: "交给 CRM" })).toBeDisabled()
  await userEvent.click(screen.getByRole("button", { name: "交给 CRM" }))
  expect(denied.emitted("handoff")).toBeUndefined()
})
