import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen, waitFor } from "@testing-library/vue"
import { config } from "@vue/test-utils"
import userEvent from "@testing-library/user-event"
import { afterAll, beforeAll, expect, it, vi } from "vitest"

import { createTestRouter } from "../../test/testRouter"
import CandidateEnrichmentQueue from "./CandidateEnrichmentQueue.vue"

const testRouter = createTestRouter()
beforeAll(async () => {
  config.global.plugins.push(testRouter)
  await testRouter.push("/")
  await testRouter.isReady()
})
afterAll(() => {
  config.global.plugins = config.global.plugins.filter((plugin) => plugin !== testRouter)
})

it("does not expose fake enrichment in the formal interface", () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(CandidateEnrichmentQueue, {
    props: { candidates: [{
      id: "candidate-formal", company_name: "Licensed Drives", country: "Chile", website: "",
      industry: "Machinery", status: "ACCEPTED", status_label: "待补全公司资料",
      source_owner: "Licensed list", license_contract: "Internal prospecting licence", import_format: "CSV",
      is_demo: false, created_at: "2026-08-15T06:00:00Z",
      latest_preview: {
        candidate_id: "candidate-formal", mode: "FAKE_PREVIEW", data_label: "Demo / Fake 资料补全预演",
        facts: [{ field: "industry", value: "Imagined industry", source: "Demo" }], public_contact_paths: [],
        uncertainties: [], message: "Fake preview", created: true,
      },
    }] },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })

  expect(screen.getByText("待确认已导入事实", { exact: false })).toBeInTheDocument()
  expect(screen.queryByText("Demo / Fake 资料补全预演")).not.toBeInTheDocument()
  expect(screen.queryByText("Imagined industry")).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "准备公司资料" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "上传真实资料" })).toHaveAttribute("href", "/assets")
})

it("lets a formal candidate review imported facts before joining follow-up", async () => {
  document.cookie = "csrftoken=formal-enrichment-token"
  const preview = {
    candidate_id: "candidate-formal",
    mode: "IMPORTED_FACTS_REVIEW",
    data_label: "许可名单事实 · 待人工确认",
    facts: [
      { field: "company_name", value: "Licensed Drives", source: "许可名单导入" },
      { field: "country", value: "Chile", source: "许可名单导入" },
    ],
    public_contact_paths: [],
    uncertainties: ["尚未联网核实公司官网", "没有采购意向证据"],
    message: "仅整理已导入事实；没有联网核实、没有采购意向，也不会联系客户。",
    created: true,
    account_id: null,
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith("/prepare")) return new Response(JSON.stringify(preview), { status: 201, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify({ account_id: "account-formal", follow_up_id: "follow-formal", status: "OPEN", created: true, message: "已加入人工跟进；没有生成采购意向，也没有联系客户。" }), { status: 201, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()

  render(CandidateEnrichmentQueue, {
    props: { candidates: [{
      id: "candidate-formal", company_name: "Licensed Drives", country: "Chile", website: "",
      industry: "Machinery", status: "ACCEPTED", status_label: "待补全公司资料",
      source_owner: "Licensed list", license_contract: "Internal prospecting licence", import_format: "CSV",
      is_demo: false, created_at: "2026-08-15T06:00:00Z", latest_preview: null,
    }] },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })

  await user.click(screen.getByRole("button", { name: "准备公司资料" }))
  expect(await screen.findByText("许可名单事实 · 待人工确认")).toBeInTheDocument()
  expect(screen.getByText("Licensed Drives", { selector: "dd" })).toBeInTheDocument()
  expect(screen.getByText("没有采购意向证据")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "加入跟进" }))
  expect(await screen.findByText("已加入人工跟进；没有生成采购意向，也没有联系客户。")).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it("restores the saved review draft after a refresh without asking to generate it again", () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(CandidateEnrichmentQueue, {
    props: {
      candidates: [{
        id: "candidate-saved", company_name: "Saved Drives", country: "Chile", website: "",
        industry: "Machinery", status: "ACCEPTED", status_label: "待补全公司资料",
        source_owner: "Licensed list", license_contract: "Internal prospecting licence", import_format: "CSV",
        is_demo: false, created_at: "2026-08-15T06:00:00Z",
        latest_preview: {
          candidate_id: "candidate-saved", mode: "IMPORTED_FACTS_REVIEW", data_label: "许可名单事实 · 待人工确认",
          facts: [{ field: "company_name", value: "Saved Drives", source: "许可名单导入" }],
          public_contact_paths: [], uncertainties: ["没有采购意向证据"],
          message: "仅整理已导入事实；没有采购意向，也不会联系客户。", created: false,
          account_id: "account-saved",
        },
      }],
      outreachDrafts: [{
        id: "draft-saved", account_id: "account-saved", english_draft: "Hello Saved Drives team.",
        chinese_explanation: "仅引用已保存事实。", status: "DRAFT", delivery: "NEVER_SENT",
        created_at: "2026-08-15T07:00:00Z", updated_at: "2026-08-15T07:00:00Z",
      }],
    },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })

  expect(screen.getByText("Hello Saved Drives team.")).toBeInTheDocument()
  expect(screen.getByText("待人工审核 · 绝不自动发送")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "生成联系草稿" })).not.toBeInTheDocument()
})


it("prepares a clearly fake company profile without inventing contacts or intent", async () => {
  document.cookie = "csrftoken=enrichment-token"
  const preview = {
    candidate_id: "candidate-1",
    mode: "FAKE_PREVIEW",
    data_label: "Demo / Fake 资料补全预演",
    facts: [
      { field: "company_name", value: "Jakarta Drives", source: "许可名单导入" },
      { field: "country", value: "Indonesia", source: "许可名单导入" },
    ],
    public_contact_paths: [],
    uncertainties: ["尚未联网核实公司官网", "尚未发现可验证的公开联系页面", "没有采购意向证据"],
    message: "未联网抓取，不会生成联系人、邮箱或采购意向，也不会联系客户。",
    created: true,
    account_id: null,
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith("/prepare")) return new Response(JSON.stringify(preview), { status: 201, headers: { "Content-Type": "application/json" } })
    if (url.endsWith("/follow-up")) return new Response(JSON.stringify({ account_id: "account-1", follow_up_id: "follow-1", status: "OPEN", created: true, message: "已加入人工跟进；没有生成采购意向，也没有联系客户。" }), { status: 201, headers: { "Content-Type": "application/json" } })
    return new Response(JSON.stringify({ id: "draft-1", status: "DRAFT", "English draft": "Hello Jakarta Drives team, may I share a capability summary?", "Chinese explanation": "仅询问是否愿意查看，不声称已有采购意向。", delivery: "NEVER_SENT" }), { status: 201, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()

  render(CandidateEnrichmentQueue, {
    props: {
      allowDemo: true,
      candidates: [{
        id: "candidate-1",
        company_name: "Jakarta Drives",
        country: "Indonesia",
        website: "",
        industry: "Industrial equipment",
        status: "ACCEPTED",
        status_label: "待补全公司资料",
        source_owner: "Licensed supplier",
        license_contract: "Prospecting licence 2026",
        import_format: "CSV",
        is_demo: false,
        created_at: "2026-08-15T06:00:00Z",
        latest_preview: null,
      }],
    },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })

  expect(screen.getByRole("heading", { name: "待补全公司资料" })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "准备公司资料" }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/v1/growth/enrichment/candidates/candidate-1/prepare")
  expect(await screen.findByText("Demo / Fake 资料补全预演")).toBeInTheDocument()
  expect(screen.getByText("Jakarta Drives", { selector: "dd" })).toBeInTheDocument()
  expect(screen.getAllByText(/许可名单导入/).length).toBeGreaterThan(0)
  expect(screen.getByText("尚未发现可验证的公开联系路径")).toBeInTheDocument()
  expect(screen.getByText("没有采购意向证据")).toBeInTheDocument()
  expect(screen.getByText("未联网抓取，不会生成联系人、邮箱或采购意向，也不会联系客户。")).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "加入跟进" }))
  expect(await screen.findByText("已加入人工跟进；没有生成采购意向，也没有联系客户。")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "生成联系草稿" }))
  expect(await screen.findByText(/Hello Jakarta Drives team/)).toBeInTheDocument()
  expect(screen.getByText("待人工审核 · 绝不自动发送")).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(3)
})
