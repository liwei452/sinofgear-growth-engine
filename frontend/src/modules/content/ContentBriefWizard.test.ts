import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, it, vi } from "vitest"

import { ApiError } from "../../api/client"
import ContentBriefWizard from "./ContentBriefWizard.vue"

const { patchBriefMock } = vi.hoisted(() => ({ patchBriefMock: vi.fn() }))

vi.mock("./api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./api")>(),
  patchBrief: patchBriefMock,
}))

const draft = {
  id: "brief-1", campaign_id: "campaign-1", previous_version_id: null, version: 1, status: "DRAFT",
  target_country: "德国", customer_type: "工业采购", content_objective: "获取询盘", cta: "立即询价",
  landing_page_url: "https://example.com/de", language: "de", prohibited_claims: ["永不磨损"],
  selling_points: ["精密磨齿"], advantages: ["交期稳定"], keywords: ["精密齿轮"],
  product_ids: ["product-1"], asset_ids: [], platform_ids: ["platform-1"], concept_links: [],
  created_by: 1, reviewed_by: null, reviewed_at: null,
  created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
} as const

function renderWizard(verifiedFactCount?: number) {
  return render(ContentBriefWizard, {
    props: {
      campaigns: [{ id: "campaign-1", name: "德国获客", description: "", status: "DRAFT", version: 1, product_ids: [], created_at: "", updated_at: "" }],
      products: [{ id: "product-1", name_zh: "精密齿轮", name_en: "Precision Gear", status: "ACTIVE", verified_fact_count: verifiedFactCount }],
      platforms: [{ id: "platform-1", code: "LINKEDIN", name: "LinkedIn", capabilities: ["PUBLISH"] }],
      assets: [], brief: draft,
      more: { campaigns: false, products: false, platforms: false, assets: false },
      pageErrors: { campaigns: "", products: "", platforms: "", assets: "" },
    },
  })
}

async function submitDraft(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "保存需求草稿" }))
}

beforeEach(() => patchBriefMock.mockReset())

it("shows how many human-verified facts are available before generation", async () => {
  const user = userEvent.setup()
  renderWizard(2)
  await user.click(screen.getByRole("button", { name: "下一步" }))
  expect(screen.getByText("· 2 条已验证事实可用")).toBeInTheDocument()
})

it("normalizes relationship aliases, returns to step two, and focuses a real product checkbox", async () => {
  patchBriefMock.mockRejectedValueOnce(new ApiError(400, "请求未能完成", undefined, {
    fieldErrors: { product_ids: ["请选择有效产品。"], target_platforms: ["请选择有效平台。"] },
  }))
  const user = userEvent.setup()
  renderWizard()

  await submitDraft(user)

  expect(await screen.findByRole("heading", { name: "选择产品和平台" })).toBeInTheDocument()
  expect(screen.getByText("请选择有效产品。")).toBeInTheDocument()
  expect(screen.getByText("请选择有效平台。")).toBeInTheDocument()
  expect(screen.getByLabelText("精密齿轮")).toHaveFocus()
})

it("focuses a real platform checkbox for a platform_ids error", async () => {
  patchBriefMock.mockRejectedValueOnce(new ApiError(400, "请求未能完成", undefined, {
    fieldErrors: { platform_ids: ["平台不支持此内容。"] },
  }))
  const user = userEvent.setup()
  renderWizard()

  await submitDraft(user)

  expect(await screen.findByText("平台不支持此内容。")).toBeInTheDocument()
  expect(screen.getByLabelText("LinkedIn")).toHaveFocus()
})

it("shows cross-field detail errors and focuses the first actual textarea", async () => {
  patchBriefMock.mockRejectedValueOnce(new ApiError(400, "请求未能完成", undefined, {
    fieldErrors: {
      selling_points: ["卖点与禁用说法冲突。"],
      prohibited_claims: ["禁用说法与卖点冲突。"],
    },
  }))
  const user = userEvent.setup()
  renderWizard()

  await submitDraft(user)

  expect(await screen.findByText("卖点与禁用说法冲突。")).toBeInTheDocument()
  expect(screen.getByText("禁用说法与卖点冲突。")).toBeInTheDocument()
  expect(screen.getByLabelText("卖点")).toHaveFocus()
})

it("puts unknown and non-field errors in a focusable summary", async () => {
  patchBriefMock.mockRejectedValueOnce(new ApiError(400, "请求未能完成", undefined, {
    fieldErrors: { non_field_errors: ["这些字段组合无效。"], mystery_field: ["未知规则失败。"] },
  }))
  const user = userEvent.setup()
  renderWizard()

  await submitDraft(user)

  const summary = await screen.findByRole("alert")
  expect(summary).toHaveTextContent("这些字段组合无效。")
  expect(summary).toHaveTextContent("未知规则失败。")
  expect(summary).toHaveFocus()
})
