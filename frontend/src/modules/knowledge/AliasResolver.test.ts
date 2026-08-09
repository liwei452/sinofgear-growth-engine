import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import AliasResolver from "./AliasResolver.vue"

afterEach(() => { vi.unstubAllGlobals(); document.cookie = "csrftoken=; Max-Age=0; path=/" })

it("resolves one name in a collapsible panel and announces the selected concept", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const match = { concept_id: "c1", code: "HELICAL_GEAR", concept_type: "PRODUCT_TYPE", scope: "SYSTEM", label_zh: "斜齿轮", label_en: "Helical gear" }
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ambiguous: false, selected: match, candidates: [match] }), { status: 200, headers: { "Content-Type": "application/json" } }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup(); render(AliasResolver)
  await user.click(screen.getByText("检查一个名称"))
  await user.type(screen.getByLabelText("要检查的名称"), "helical gears")
  await user.selectOptions(screen.getByLabelText("语言"), "en")
  await user.click(screen.getByRole("button", { name: "检查名称" }))
  expect(await screen.findByText(/唯一匹配：斜齿轮/)).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/knowledge/resolve", expect.objectContaining({ method: "POST" }))
})

it("shows ambiguous candidates and a clear no-match result without creating aliases", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const candidates = [
    { concept_id: "c1", code: "GEAR", concept_type: "PRODUCT_TYPE", scope: "SYSTEM", label_zh: "齿轮", label_en: "Gear" },
    { concept_id: "c2", code: "GEAR_SET", concept_type: "PRODUCT_TYPE", scope: "ORGANIZATION", label_zh: "齿轮组", label_en: "Gear set" },
  ]
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ ambiguous: true, selected: null, candidates }), { status: 200, headers: { "Content-Type": "application/json" } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ambiguous: false, selected: null, candidates: [] }), { status: 200, headers: { "Content-Type": "application/json" } }))
  vi.stubGlobal("fetch", fetchMock)
  const user = userEvent.setup(); render(AliasResolver)
  await user.click(screen.getByText("检查一个名称"))
  const input = screen.getByLabelText("要检查的名称")
  await user.type(input, "gear"); await user.click(screen.getByRole("button", { name: "检查名称" }))
  expect(await screen.findByText("找到多个可能匹配，请人工确认：")).toBeInTheDocument()
  expect(screen.getByText(/齿轮组/)).toBeInTheDocument()
  await user.clear(input); await user.type(input, "unknown"); await user.click(screen.getByRole("button", { name: "检查名称" }))
  expect(await screen.findByText("暂时没有找到匹配的已通过知识。" )).toBeInTheDocument()
  expect(fetchMock.mock.calls.every(([path]) => path === "/api/v1/knowledge/resolve")).toBe(true)
})
