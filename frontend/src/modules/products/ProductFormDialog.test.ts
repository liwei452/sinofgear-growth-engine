import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import type { KnowledgeConcept } from "../knowledge/api"
import ProductFormDialog from "./ProductFormDialog.vue"

it("maps an approved CAPABILITY concept to the manufacturing capability product role", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const capability: KnowledgeConcept = {
    id: "capability-1", scope: "SYSTEM", organization: null, concept_type: "CAPABILITY",
    code: "CAP-GEAR-GRINDING", label_zh: "磨齿能力", label_en: "Gear grinding capability", description: "",
    status: "APPROVED", version: 1, suggested_by_ai_run_id: null, evidence: [], created_by: null,
    reviewed_by: 1, reviewed_at: null, created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
  }
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(baseProduct), {
    status: 201, headers: { "Content-Type": "application/json", ETag: '"1"' },
  }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderDialog({ concepts: [capability] })
  await fillRequired(user)

  await user.selectOptions(screen.getByLabelText("制造能力标签"), "capability-1")
  await user.click(screen.getByRole("button", { name: "保存产品" }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toMatchObject({
    concept_links: [{ role: "CAPABILITY", concept_id: "capability-1" }],
  })
})

const baseProduct = {
  id: "product-1", organization: "org-1", name_zh: "斜齿轮", name_en: "Helical Gear",
  module_min: "0.5000", module_max: "8.0000", tooth_count_min: 8, tooth_count_max: 240,
  pressure_angle: "20.000", accuracy_grade: "ISO 6", heat_treatment: "渗碳", surface_treatment: "喷丸",
  manufacturing_capabilities: ["滚齿"], inspection_capabilities: ["CMM"], moq: 10,
  lead_time: "4-6 周", landing_page_url: "https://example.com/gears", status: "ACTIVE", version: 1,
  internal_notes: "", concept_links: [], created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
}

function renderDialog(props: { productId?: string; concepts?: KnowledgeConcept[] } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(ProductFormDialog, {
    props: { concepts: [], organizationId: "org-1", ...props },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

async function fillRequired(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("英文名称（必填）"), "Helical Gear")
  await user.type(screen.getByLabelText("最小模数（必填）"), "0.5")
  await user.type(screen.getByLabelText("最大模数（必填）"), "8")
  await user.type(screen.getByLabelText("最少齿数（必填）"), "8")
  await user.type(screen.getByLabelText("最多齿数（必填）"), "240")
  await user.type(screen.getByLabelText("压力角（必填）"), "20")
  await user.type(screen.getByLabelText("最小起订量（必填）"), "10")
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("focuses the title, traps Tab, closes on Escape, and restores the opener", async () => {
  const opener = document.createElement("button")
  opener.textContent = "打开产品"
  document.body.appendChild(opener)
  opener.focus()
  const background = document.createElement("main")
  background.className = "app-shell"
  const drawer = document.createElement("aside")
  drawer.setAttribute("inert", "")
  background.appendChild(drawer)
  document.body.appendChild(background)

  const user = userEvent.setup()
  const result = renderDialog()
  const title = await screen.findByRole("heading", { name: "新建产品" })
  await waitFor(() => expect(title).toHaveFocus())
  expect(background).toHaveAttribute("inert")

  const close = screen.getByRole("button", { name: "关闭" })
  const save = screen.getByRole("button", { name: "保存产品" })
  await user.keyboard("{Shift>}{Tab}{/Shift}")
  expect(save).toHaveFocus()
  await user.tab()
  expect(close).toHaveFocus()

  await user.keyboard("{Escape}")
  expect(result.emitted("close")).toHaveLength(1)
  result.unmount()
  expect(background).not.toHaveAttribute("inert")
  expect(drawer).toHaveAttribute("inert")
  expect(opener).toHaveFocus()
  opener.remove()
  background.remove()
})

it("moves forward from the initially focused title to the first control", async () => {
  const user = userEvent.setup()
  renderDialog()
  const title = await screen.findByRole("heading", { name: "新建产品" })
  await waitFor(() => expect(title).toHaveFocus())

  await user.keyboard("{Tab}")
  expect(screen.getByRole("button", { name: "关闭" })).toHaveFocus()
})

it("validates ranges and URL, focuses the first error, and cancels without submitting", async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  const result = renderDialog()

  await user.click(screen.getByRole("button", { name: "保存产品" }))
  expect(screen.getByRole("alert")).toHaveTextContent("请检查表单中的问题")
  expect(screen.getByLabelText("英文名称（必填）")).toHaveFocus()
  await user.type(screen.getByLabelText("英文名称（必填）"), "Gear")
  await user.type(screen.getByLabelText("最小模数（必填）"), "8")
  await user.type(screen.getByLabelText("最大模数（必填）"), "2")
  await user.type(screen.getByLabelText("落地页网址"), "javascript:alert(1)")
  await user.click(screen.getByRole("button", { name: "保存产品" }))
  expect(screen.getByText("最大模数不能小于最小模数。")).toBeInTheDocument()
  expect(screen.getByText("请输入 http 或 https 开头的网址。")).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "取消" }))
  expect(result.emitted("close")).toHaveLength(1)
  expect(fetchMock).not.toHaveBeenCalled()
})

it("maps backend field errors, then creates and emits the real saved product", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ errors: { name_en: ["English name already exists."] } }), {
      status: 400, headers: { "Content-Type": "application/json" },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify(baseProduct), {
      status: 201, headers: { "Content-Type": "application/json", ETag: '"1"' },
    }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  const result = renderDialog()
  await fillRequired(user)

  await user.click(screen.getByRole("button", { name: "保存产品" }))
  expect(await screen.findByText("English name already exists.")).toBeInTheDocument()
  expect(screen.getByLabelText("英文名称（必填）")).toHaveFocus()
  await user.click(screen.getByRole("button", { name: "保存产品" }))

  await waitFor(() => expect(result.emitted("saved")?.[0]?.[0]).toMatchObject({
    product: { id: "product-1" },
    etag: '"1"',
  }))
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/api/v1/products",
    expect.objectContaining({ method: "POST" }),
  )
})

it("loads a real ETag, patches with If-Match, and reloads after a 409 conflict", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const reloaded = { ...baseProduct, name_en: "Newer Server Gear", version: 2 }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(baseProduct), {
      status: 200, headers: { "Content-Type": "application/json", ETag: '"1"' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ code: "PRODUCT_VERSION_CONFLICT", current_version: 2 }), {
      status: 409, headers: { "Content-Type": "application/json" },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify(reloaded), {
      status: 200, headers: { "Content-Type": "application/json", ETag: '"2"' },
    }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderDialog({ productId: "product-1" })

  expect(await screen.findByDisplayValue("Helical Gear")).toBeInTheDocument()
  await user.clear(screen.getByLabelText("英文名称（必填）"))
  await user.type(screen.getByLabelText("英文名称（必填）"), "My Edit")
  await user.click(screen.getByRole("button", { name: "保存修改" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("数据已被其他人更新")
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/v1/products/product-1",
    expect.objectContaining({ headers: expect.objectContaining({ "if-match": '"1"' }) }),
  )

  await user.click(screen.getByRole("button", { name: "重新加载最新数据" }))
  expect(await screen.findByDisplayValue("Newer Server Gear")).toBeInTheDocument()
})

it("announces a friendly read-only state when edit is forbidden", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(baseProduct), {
      status: 200, headers: { "Content-Type": "application/json", ETag: '"1"' },
    }))
    .mockResolvedValueOnce(new Response(null, { status: 403 }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderDialog({ productId: "product-1" })
  await screen.findByDisplayValue("Helical Gear")

  await user.click(screen.getByRole("button", { name: "保存修改" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("你暂时没有权限修改这个产品，可以继续查看最新信息。")
})

it("maps an approved INDUSTRY concept to the APPLICATION product role", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const industry: KnowledgeConcept = {
    id: "industry-1", scope: "SYSTEM", organization: null, concept_type: "INDUSTRY",
    code: "AUTOMOTIVE", label_zh: "汽车行业", label_en: "Automotive", description: "",
    status: "APPROVED", version: 1, suggested_by_ai_run_id: null, evidence: [], created_by: null,
    reviewed_by: 1, reviewed_at: null, created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
  }
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(baseProduct), {
    status: 201, headers: { "Content-Type": "application/json", ETag: '"1"' },
  }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup()
  renderDialog({ concepts: [industry] })
  await fillRequired(user)

  await user.selectOptions(screen.getByLabelText("应用标签"), "industry-1")
  await user.click(screen.getByRole("button", { name: "保存产品" }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toMatchObject({
    concept_links: [{ role: "APPLICATION", concept_id: "industry-1" }],
  })
})
