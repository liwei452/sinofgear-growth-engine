import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, it, vi } from "vitest"

import { ApiError } from "../../api/client"
import type { Product, ProductStatus } from "../products/api"
import ContentBriefWizard from "./ContentBriefWizard.vue"
import type { Asset, BriefConcept, ContentBrief } from "./api"

const { patchBriefMock } = vi.hoisted(() => ({ patchBriefMock: vi.fn() }))

vi.mock("./api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./api")>(),
  patchBrief: patchBriefMock,
}))

const draft: ContentBrief = {
  id: "brief-1", campaign_id: "campaign-1", previous_version_id: null, version: 1, status: "DRAFT",
  target_country: "德国", customer_type: "工业采购", content_objective: "获取询盘", cta: "立即询价",
  landing_page_url: "https://example.com/de", language: "de", prohibited_claims: ["永不磨损"],
  selling_points: ["精密磨齿"], advantages: ["交期稳定"], keywords: ["精密齿轮"],
  product_ids: ["product-1"], asset_ids: [], platform_ids: ["platform-1"], concept_links: [],
  created_by: 1, reviewed_by: null, reviewed_at: null,
  created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
}

function product(id: string, name: string, status: ProductStatus): Product {
  return {
    id, organization: "org-1", name_zh: name, name_en: name, module_min: "1", module_max: "2",
    tooth_count_min: 10, tooth_count_max: 20, pressure_angle: "20", accuracy_grade: "DIN 6",
    heat_treatment: "", surface_treatment: "", manufacturing_capabilities: [], inspection_capabilities: [],
    moq: 1, lead_time: "", landing_page_url: "", status, version: 1, internal_notes: "", concept_links: [],
    created_at: "", updated_at: "",
  }
}

function asset(id: string, filename: string, status: string): Asset {
  return { id, asset_type: "IMAGE", original_filename: filename, mime_type: "image/png", size_bytes: 1, language: "zh", status, tags: [], created_at: "" }
}

function renderWizard(overrides: {
  brief?: ContentBrief | null
  products?: Product[]
  assets?: Asset[]
  concepts?: BriefConcept[]
  experience?: "ordinary" | "advanced"
} = {}) {
  return render(ContentBriefWizard, {
    props: {
      campaigns: [{ id: "campaign-1", name: "德国获客", description: "", status: "DRAFT", version: 1, product_ids: [], created_at: "", updated_at: "" }],
      products: overrides.products ?? [product("product-1", "精密齿轮", "ACTIVE")],
      platforms: [{ id: "platform-1", code: "LINKEDIN", name: "LinkedIn", capabilities: ["PUBLISH"] }],
      assets: overrides.assets ?? [], concepts: overrides.concepts ?? [], brief: overrides.brief === undefined ? draft : overrides.brief,
      experience: overrides.experience,
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

it("shows linked unavailable relationships and removes them from an edited draft", async () => {
  const staleDraft: ContentBrief = {
    ...draft,
    product_ids: ["product-1", "product-archived"],
    asset_ids: ["asset-archived"],
    concept_links: [{ role: "STANDARD", concept_id: "concept-rejected" }],
  }
  patchBriefMock.mockResolvedValueOnce(staleDraft)
  const user = userEvent.setup()
  renderWizard({
    brief: staleDraft,
    products: [
      product("product-1", "精密齿轮", "ACTIVE"),
      product("product-archived", "旧产品", "ARCHIVED"),
      product("product-unlinked", "未关联旧产品", "ARCHIVED"),
    ],
    assets: [asset("asset-archived", "old-photo.png", "ARCHIVED"), asset("asset-unlinked", "unlinked-old.png", "ARCHIVED")],
    concepts: [
      { id: "concept-rejected", code: "OLD_STANDARD", concept_type: "STANDARD", label_zh: "旧标准", label_en: "Old standard", status: "REJECTED" },
      { id: "concept-unlinked", code: "OTHER_OLD", concept_type: "STANDARD", label_zh: "其他旧标准", label_en: "Other old", status: "DEPRECATED" },
    ],
  })

  await user.click(screen.getByRole("button", { name: "下一步" }))
  expect(screen.getByLabelText("旧产品（不可用，仅可移除）")).toBeChecked()
  expect(screen.getByLabelText("old-photo.png（不可用，仅可移除）")).toBeChecked()
  expect(screen.getByLabelText("Old standard (STANDARD)（不可用，仅可移除）")).toBeChecked()
  expect(screen.queryByText("未关联旧产品")).not.toBeInTheDocument()
  expect(screen.queryByText("unlinked-old.png")).not.toBeInTheDocument()
  expect(screen.queryByText("其他旧标准")).not.toBeInTheDocument()

  await user.click(screen.getByLabelText("旧产品（不可用，仅可移除）"))
  await user.click(screen.getByLabelText("old-photo.png（不可用，仅可移除）"))
  await user.click(screen.getByLabelText("Old standard (STANDARD)（不可用，仅可移除）"))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "保存需求草稿" }))

  expect(patchBriefMock).toHaveBeenCalledWith("brief-1", expect.objectContaining({
    product_ids: ["product-1"], asset_ids: [], concept_links: [],
  }))
})

it("renders missing linked provenance as a removable unavailable placeholder", async () => {
  const missingDraft: ContentBrief = { ...draft, product_ids: ["product-1", "product-outside-page"] }
  patchBriefMock.mockResolvedValueOnce(missingDraft)
  const user = userEvent.setup()
  renderWizard({ brief: missingDraft })

  await user.click(screen.getByRole("button", { name: "下一步" }))
  const placeholder = screen.getByLabelText("历史关联产品 product-outside-page（不可用，仅可移除）")
  expect(placeholder).toBeChecked()
  await user.click(placeholder)
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "保存需求草稿" }))

  expect(patchBriefMock).toHaveBeenCalledWith("brief-1", expect.objectContaining({ product_ids: ["product-1"] }))
})

it("does not offer inactive or unapproved relationships during ordinary creation", async () => {
  const user = userEvent.setup()
  renderWizard({
    brief: null,
    products: [product("product-1", "精密齿轮", "ACTIVE"), product("product-archived", "旧产品", "ARCHIVED")],
    assets: [asset("asset-active", "current.png", "ACTIVE"), asset("asset-archived", "old.png", "ARCHIVED")],
    concepts: [
      { id: "concept-approved", code: "DIN", concept_type: "STANDARD", label_zh: "DIN", label_en: "DIN", status: "APPROVED" },
      { id: "concept-rejected", code: "OLD", concept_type: "STANDARD", label_zh: "旧标准", label_en: "Old", status: "REJECTED" },
    ],
  })

  await user.click(screen.getByRole("button", { name: "下一步" }))

  expect(screen.getByLabelText("精密齿轮")).toBeVisible()
  expect(screen.getByText("current.png")).toBeVisible()
  expect(screen.getByLabelText("DIN (STANDARD)")).toBeVisible()
  expect(screen.queryByText("旧产品")).not.toBeInTheDocument()
  expect(screen.queryByText("old.png")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Old (STANDARD)")).not.toBeInTheDocument()
})

it("uses beginner presets in product goal material confirmation order", async () => {
  renderWizard({ experience: "ordinary" })

  expect(screen.getByRole("heading", { name: "选择产品" })).toBeVisible()
  expect(screen.getByLabelText("精密齿轮")).toBeVisible()
  expect(screen.queryByLabelText("目标国家（必填）")).not.toBeInTheDocument()
  expect(screen.queryByRole("textbox", { name: /聊天|对话|问 AI/ })).not.toBeInTheDocument()
})
