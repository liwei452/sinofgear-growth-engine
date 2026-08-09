import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import KnowledgeConceptDialog from "./KnowledgeConceptDialog.vue"
import ProductFormDialog from "../products/ProductFormDialog.vue"

const saved = {
  id: "concept-1", scope: "ORGANIZATION", organization: "org-1", concept_type: "MATERIAL",
  code: "ALLOY_STEEL", label_zh: "合金钢", label_en: "Alloy steel", description: "",
  status: "SUGGESTED", version: 1, evidence: [], suggested_by_ai_run_id: null, created_by: 1,
  reviewed_by: null, reviewed_at: null, created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
}

function renderDialog() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(KnowledgeConceptDialog, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
}

afterEach(() => { vi.unstubAllGlobals(); document.cookie = "csrftoken=; Max-Age=0; path=/" })

it("focuses its title, keeps focus inside, and closes on Escape", async () => {
  const user = userEvent.setup()
  const result = renderDialog()
  const title = await screen.findByRole("heading", { name: "新增知识建议" })
  await waitFor(() => expect(title).toHaveFocus())

  const submit = screen.getByRole("button", { name: "提交知识建议" })
  await user.keyboard("{Shift>}{Tab}{/Shift}")
  expect(submit).toHaveFocus()
  await user.keyboard("{Escape}")
  expect(result.emitted("close")).toHaveLength(1)
})

it("keeps the underlying dialog inert until a nested dialog unmounts", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const outer = render(ProductFormDialog, {
    props: { concepts: [], organizationId: "org-1" },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
  const outerTitle = await screen.findByRole("heading", { name: "新建产品" })
  await waitFor(() => expect(outerTitle).toHaveFocus())
  const outerBackdrop = screen.getByRole("dialog", { name: "新建产品" }).parentElement

  const inner = renderDialog()
  const innerTitle = await screen.findByRole("heading", { name: "新增知识建议" })
  await waitFor(() => expect(innerTitle).toHaveFocus())
  expect(outerBackdrop).toHaveAttribute("inert")

  inner.unmount()
  expect(outerBackdrop).not.toHaveAttribute("inert")
  expect(outerTitle).toHaveFocus()
  outer.unmount()
})

it("validates required fields, focuses the first error, and cancels without a request", async () => {
  const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup(); const result = renderDialog()
  await user.click(screen.getByRole("button", { name: "提交知识建议" }))
  expect(screen.getByRole("alert")).toHaveTextContent("请检查表单中的问题")
  expect(screen.getByLabelText("知识类型（必填）")).toHaveFocus()
  await user.click(screen.getByRole("button", { name: "取消" }))
  expect(result.emitted("close")).toHaveLength(1)
  expect(fetchMock).not.toHaveBeenCalled()
})
it("always posts an ORGANIZATION suggestion and emits the saved record", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(saved), { status: 201, headers: { "Content-Type": "application/json" } }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup(); const result = renderDialog()
  await user.selectOptions(screen.getByLabelText("知识类型（必填）"), "MATERIAL")
  await user.type(screen.getByLabelText("编码（必填）"), "alloy_steel")
  await user.type(screen.getByLabelText("中文名称（必填）"), "合金钢")
  await user.type(screen.getByLabelText("英文名称（必填）"), "Alloy steel")
  await user.click(screen.getByRole("button", { name: "提交知识建议" }))

  await waitFor(() => expect(result.emitted("saved")?.[0]?.[0]).toMatchObject({ id: "concept-1" }))
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/knowledge/concepts", expect.objectContaining({
    method: "POST", body: expect.stringContaining('"scope":"ORGANIZATION"'),
  }))
  expect(fetchMock.mock.calls[0]?.[1]?.body).not.toContain("SYSTEM")
})

it("maps duplicate-code field errors and restores the submit control", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ errors: { code: ["A concept with this scoped type and code already exists."] } }), { status: 400, headers: { "Content-Type": "application/json" } })))
  const user = userEvent.setup(); renderDialog()
  await user.selectOptions(screen.getByLabelText("知识类型（必填）"), "MATERIAL")
  await user.type(screen.getByLabelText("编码（必填）"), "STEEL")
  await user.type(screen.getByLabelText("中文名称（必填）"), "钢")
  await user.type(screen.getByLabelText("英文名称（必填）"), "Steel")
  await user.click(screen.getByRole("button", { name: "提交知识建议" }))
  expect(await screen.findByText("A concept with this scoped type and code already exists.")).toBeInTheDocument()
  expect(screen.getByLabelText("编码（必填）")).toHaveFocus()
  expect(screen.getByRole("button", { name: "提交知识建议" })).toBeEnabled()
})
