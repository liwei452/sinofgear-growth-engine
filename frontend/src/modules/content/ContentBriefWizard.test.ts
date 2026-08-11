import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, it, vi } from "vitest"

import { ApiError } from "../../api/client"
import "../../styles/tokens.css"
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
      more: { campaigns: false, products: false, platforms: false, assets: false, concepts: false },
      pageErrors: { campaigns: "", products: "", platforms: "", assets: "", concepts: "" },
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

it("uses the shared SinofGear blue tokens for the current ordinary wizard step", () => {
  renderWizard({ experience: "ordinary" })
  const current = document.querySelector<HTMLElement>(".wizard-progress [aria-current='step']")!

  expect(getComputedStyle(current).backgroundColor).toBe("var(--sg-brand-tint)")
  expect(getComputedStyle(current).color).toBe("var(--sg-brand)")
  expect(getComputedStyle(document.documentElement).getPropertyValue("--sg-brand").trim()).toBe("#005ba8")
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
  const missingDraft: ContentBrief = { ...draft, product_ids: ["product-1", "product-outside-page", "product-other-page"] }
  patchBriefMock.mockResolvedValueOnce(missingDraft)
  const user = userEvent.setup()
  renderWizard({ brief: missingDraft })

  await user.click(screen.getByRole("button", { name: "下一步" }))
  const placeholder = screen.getByLabelText("历史产品 1（名称暂不可用）（不可用，仅可移除）")
  const secondPlaceholder = screen.getByLabelText("历史产品 2（名称暂不可用）（不可用，仅可移除）")
  expect(placeholder).toBeChecked()
  expect(secondPlaceholder).toBeChecked()
  for (const summary of screen.getAllByText("内部ID")) expect(summary.closest("details")).not.toHaveAttribute("open")
  await user.click(placeholder)
  expect(screen.getByLabelText("历史产品 2（名称暂不可用）（不可用，仅可移除）")).toBeChecked()
  await user.click(secondPlaceholder)
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(screen.getByRole("button", { name: "保存需求草稿" }))

  expect(patchBriefMock).toHaveBeenCalledWith("brief-1", expect.objectContaining({ product_ids: ["product-1"] }))
})

it("assigns stable distinct numbers when multiple linked products become missing after mount", async () => {
  const changingDraft: ContentBrief = {
    ...draft,
    product_ids: ["product-1", "product-later-1", "product-later-2"],
  }
  const view = renderWizard({
    brief: changingDraft,
    products: [
      product("product-1", "精密齿轮", "ACTIVE"),
      product("product-later-1", "稍后缺失一", "ACTIVE"),
      product("product-later-2", "稍后缺失二", "ACTIVE"),
    ],
  })

  await view.rerender({ products: [product("product-1", "精密齿轮", "ACTIVE")] })
  await userEvent.click(screen.getByRole("button", { name: "下一步" }))

  expect(screen.getByLabelText("历史产品 1（名称暂不可用）（不可用，仅可移除）")).toBeChecked()
  expect(screen.getByLabelText("历史产品 2（名称暂不可用）（不可用，仅可移除）")).toBeChecked()

  await view.rerender({ products: [
    product("product-1", "精密齿轮", "ACTIVE"),
    product("product-later-1", "稍后缺失一", "ACTIVE"),
  ] })
  expect(screen.getByLabelText("历史产品 2（名称暂不可用）（不可用，仅可移除）")).toBeChecked()

  await view.rerender({ products: [product("product-1", "精密齿轮", "ACTIVE")] })
  expect(screen.getByLabelText("历史产品 1（名称暂不可用）（不可用，仅可移除）")).toBeChecked()
  expect(screen.getByLabelText("历史产品 2（名称暂不可用）（不可用，仅可移除）")).toBeChecked()
})

it("keeps missing relationship UUIDs private in the ordinary wizard and still removes by ID", async () => {
  const productUuid = "11111111-1111-4111-8111-111111111111"
  const assetUuid = "22222222-2222-4222-8222-222222222222"
  const conceptUuid = "33333333-3333-4333-8333-333333333333"
  const uuidDraft: ContentBrief = {
    ...draft,
    product_ids: ["product-1", productUuid],
    asset_ids: [assetUuid],
    concept_links: [{ role: "STANDARD", concept_id: conceptUuid }],
  }
  patchBriefMock.mockResolvedValueOnce(uuidDraft)
  const user = userEvent.setup()
  renderWizard({ brief: uuidDraft, experience: "ordinary" })

  const missingProduct = screen.getByLabelText("历史产品 1（名称暂不可用）（不可用，仅可移除）")
  expect(missingProduct).toBeChecked()
  expect(document.body).not.toHaveTextContent(productUuid)
  await user.click(screen.getByRole("button", { name: "保存产品并继续" }))
  await user.click(screen.getByRole("button", { name: "保存目标并查看素材" }))

  const missingAsset = screen.getByLabelText("历史素材 1（名称暂不可用）（不可用，仅可移除）")
  const missingConcept = screen.getByLabelText("历史知识 1（名称暂不可用）（不可用，仅可移除）")
  expect(missingAsset).toBeChecked()
  expect(missingConcept).toBeChecked()
  expect(document.body).not.toHaveTextContent(assetUuid)
  expect(document.body).not.toHaveTextContent(conceptUuid)
  await user.click(screen.getByRole("button", { name: "查看并确认方案" }))
  expect(screen.getByRole("heading", { name: "确认方案" }).parentElement).toHaveTextContent(
    "精密齿轮、历史产品 1（名称暂不可用）",
  )
  expect(document.body).not.toHaveTextContent(productUuid)
  expect(document.body).not.toHaveTextContent(assetUuid)
  expect(document.body).not.toHaveTextContent(conceptUuid)

  await user.click(screen.getByRole("button", { name: "上一步" }))
  await user.click(screen.getByLabelText("历史素材 1（名称暂不可用）（不可用，仅可移除）"))
  await user.click(screen.getByLabelText("历史知识 1（名称暂不可用）（不可用，仅可移除）"))
  await user.click(screen.getByRole("button", { name: "上一步" }))
  await user.click(screen.getByRole("button", { name: "上一步" }))
  await user.click(screen.getByLabelText("历史产品 1（名称暂不可用）（不可用，仅可移除）"))
  await user.click(screen.getByRole("button", { name: "保存产品并继续" }))
  await user.click(screen.getByRole("button", { name: "保存目标并查看素材" }))
  await user.click(screen.getByRole("button", { name: "查看并确认方案" }))
  await user.click(screen.getByRole("button", { name: "保存修改方案" }))

  expect(patchBriefMock).toHaveBeenCalledWith("brief-1", expect.objectContaining({
    product_ids: ["product-1"], asset_ids: [], concept_links: [],
  }))
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
  const user = userEvent.setup()
  renderWizard({ experience: "ordinary" })

  expect(screen.getByRole("heading", { name: "选择产品" })).toBeVisible()
  expect(screen.getByLabelText("精密齿轮")).toBeVisible()
  expect(screen.queryByLabelText("目标国家（必填）")).not.toBeInTheDocument()
  expect(screen.queryByRole("textbox", { name: /聊天|对话|问 AI/ })).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "保存产品并继续" }))
  expect(screen.getByRole("heading", { name: "告诉 AI 目标" })).toBeVisible()
  await user.click(screen.getByRole("button", { name: "保存目标并查看素材" }))
  expect(screen.getByRole("heading", { name: "查看可用素材" })).toBeVisible()
  expect(screen.getByRole("button", { name: "查看并确认方案" })).toBeVisible()
})

it("returns ordinary server field errors to their real step and restores focus", async () => {
  patchBriefMock.mockRejectedValueOnce(new ApiError(400, "请求未能完成", undefined, {
    fieldErrors: { landing_page_url: ["落地页与当前组织不匹配。"] },
  }))
  const user = userEvent.setup()
  renderWizard({ experience: "ordinary" })

  await user.click(screen.getByRole("button", { name: "保存产品并继续" }))
  await user.click(screen.getByRole("button", { name: "保存目标并查看素材" }))
  await user.click(screen.getByRole("button", { name: "查看并确认方案" }))
  await user.click(screen.getByRole("button", { name: "保存修改方案" }))

  expect(await screen.findByRole("heading", { name: "告诉 AI 目标" })).toBeVisible()
  expect(screen.getByText("该项内容未通过检查，请修改后重试。")).toBeVisible()
  expect(document.body).not.toHaveTextContent("落地页与当前组织不匹配。")
  expect(screen.getByLabelText("落地页（可选）")).toHaveFocus()
})

it("translates ordinary validation details instead of exposing server fields or English recovery text", async () => {
  const privateUuid = "44444444-4444-4444-8444-444444444444"
  patchBriefMock.mockRejectedValueOnce(new ApiError(400, "English userMessage must stay private", "PERMISSION_DENIED", {
    fieldErrors: {
      product_ids: [`Invalid product UUID ${privateUuid}`],
      internal_validation_path: ["Contact your administrator and retry"],
    },
  }))
  const user = userEvent.setup()
  renderWizard({ experience: "ordinary" })

  await user.click(screen.getByRole("button", { name: "保存产品并继续" }))
  await user.click(screen.getByRole("button", { name: "保存目标并查看素材" }))
  await user.click(screen.getByRole("button", { name: "查看并确认方案" }))
  await user.click(screen.getByRole("button", { name: "保存修改方案" }))

  expect(await screen.findByText("该项内容未通过检查，请修改后重试。")).toBeVisible()
  expect(document.body).not.toHaveTextContent("product_ids")
  expect(document.body).not.toHaveTextContent("internal_validation_path")
  expect(document.body).not.toHaveTextContent("English userMessage")
  expect(document.body).not.toHaveTextContent("Contact your administrator")
  expect(document.body).not.toHaveTextContent("PERMISSION_DENIED")
  expect(document.body).not.toHaveTextContent(privateUuid)
})

it("validates an ordinary landing page before leaving the goal step", async () => {
  const user = userEvent.setup()
  renderWizard({ experience: "ordinary" })

  await user.click(screen.getByRole("button", { name: "保存产品并继续" }))
  const landingPage = screen.getByLabelText("落地页（可选）")
  await user.clear(landingPage)
  await user.type(landingPage, "ftp://example.com")
  await user.click(screen.getByRole("button", { name: "保存目标并查看素材" }))

  expect(screen.getByRole("heading", { name: "告诉 AI 目标" })).toBeVisible()
  expect(screen.getByText("请输入 http 或 https 开头的网址。")).toBeVisible()
  expect(landingPage).toHaveFocus()
})

it("lets ordinary editors remove unavailable and missing material provenance", async () => {
  const staleDraft: ContentBrief = {
    ...draft,
    product_ids: ["product-1", "product-archived"],
    asset_ids: ["asset-archived", "asset-missing"],
    concept_links: [
      { role: "STANDARD", concept_id: "concept-rejected" },
      { role: "STANDARD", concept_id: "concept-missing" },
    ],
  }
  patchBriefMock.mockResolvedValueOnce(staleDraft)
  const user = userEvent.setup()
  renderWizard({
    experience: "ordinary",
    brief: staleDraft,
    products: [product("product-1", "精密齿轮", "ACTIVE"), product("product-archived", "旧产品", "ARCHIVED")],
    assets: [asset("asset-archived", "old-photo.png", "ARCHIVED")],
    concepts: [{ id: "concept-rejected", code: "OLD", concept_type: "STANDARD", label_zh: "旧标准", label_en: "Old standard", status: "REJECTED" }],
  })

  await user.click(screen.getByLabelText("旧产品（不可用，仅可移除）"))
  await user.click(screen.getByRole("button", { name: "保存产品并继续" }))
  await user.click(screen.getByRole("button", { name: "保存目标并查看素材" }))
  for (const label of [
    "old-photo.png（不可用，仅可移除）",
    "历史素材 1（名称暂不可用）（不可用，仅可移除）",
    "Old standard (STANDARD)（不可用，仅可移除）",
    "历史知识 1（名称暂不可用）（不可用，仅可移除）",
  ]) await user.click(screen.getByLabelText(label))
  await user.click(screen.getByRole("button", { name: "查看并确认方案" }))
  await user.click(screen.getByRole("button", { name: "保存修改方案" }))

  expect(patchBriefMock).toHaveBeenCalledWith("brief-1", expect.objectContaining({
    product_ids: ["product-1"], asset_ids: [], concept_links: [],
  }))
})
