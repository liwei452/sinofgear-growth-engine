import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import CandidateListImportForm from "./CandidateListImportForm.vue"


it("imports a licensed CSV into the review-only candidate queue", async () => {
  document.cookie = "csrftoken=candidate-list-import-token"
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    expect(JSON.parse(String(init?.body))).toEqual({
      format: "CSV",
      content: "company_name,country,website\nJakarta Drives,Indonesia,https://example.invalid\n",
      source_owner: "Licensed data supplier",
      license_contract: "Internal prospecting licence",
      retention_days: 90,
      redistribution_allowed: false,
    })
    return new Response(JSON.stringify({
      created_count: 1,
      duplicate_count: 0,
      invalid_count: 0,
      errors: [],
      queue_label: "待核实候选公司",
    }), { status: 201, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(CandidateListImportForm, {
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })

  await user.click(screen.getByText("导入许可客户名单"))
  await user.upload(
    screen.getByLabelText("CSV 或 JSON 文件"),
    new File([
      "company_name,country,website\nJakarta Drives,Indonesia,https://example.invalid\n",
    ], "buyers.csv", { type: "text/csv" }),
  )
  await user.type(screen.getByLabelText("数据来源方"), "Licensed data supplier")
  await user.type(screen.getByLabelText("许可或合同名称"), "Internal prospecting licence")
  await user.click(screen.getByRole("button", { name: "导入为待核实候选" }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(await screen.findByRole("status")).toHaveTextContent(
    "已加入 1 家待核实候选；0 条重复，0 条无效。",
  )
  expect(screen.getByText("不会自动生成联系草稿，也不会联系客户。")).toBeInTheDocument()
})
