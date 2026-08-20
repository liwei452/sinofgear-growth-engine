import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import ContentPublishingPage from "./ContentPublishingPage.vue"

const platformContent = {
  id: "content-1", master_content_id: "master-1", master_version: 1, platform_id: "linkedin",
  lineage_id: "lineage-1", previous_version_id: null, version: 1, status: "IN_REVIEW", is_current_head: true,
  publish_package_id: null, created_by_id: 1, created_at: "2026-08-20T08:00:00Z", updated_at: "2026-08-20T08:00:00Z",
  provenance: { source: "approved facts" },
  payload: { schema_version: 2, platform_code: "LINKEDIN", language: "en", title: "Gear reliability", body: "Verified efficiency data.", cta: "Contact us", landing_page_url: "https://example.test", hashtags: [], evidence_fact_ids: ["fact-1"] },
}

function renderPage() {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    const body = path.includes("/master-contents") ? { next: null, previous: null, results: [] }
      : path.includes("/platform-contents") ? { next: null, previous: null, results: [platformContent] }
        : path.includes("/publish-tasks") ? { next: null, previous: null, results: [] }
          : path.includes("/platforms") ? { results: [{ id: "linkedin", code: "LINKEDIN", name: "LinkedIn", capabilities: [] }] }
            : { user: { id: 1, username: "operator" }, organization: { id: "org", name: "Org", slug: "org" }, membership: { id: "member", role: "OPERATOR", status: "ACTIVE", permissions: ["publishing.read", "content.review"] } }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }))
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(ContentPublishingPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
}

afterEach(() => vi.unstubAllGlobals())

it("organizes content by outcome and opens platform evidence without treating it as published", async () => {
  const user = userEvent.setup()
  renderPage()

  expect(await screen.findByRole("tab", { name: /待人工审核/ })).toBeInTheDocument()
  expect(screen.getByRole("tab", { name: /已提交/ })).toBeInTheDocument()
  await user.click(await screen.findByRole("button", { name: /查看内容/ }))
  expect(screen.getByRole("dialog")).toHaveTextContent("LinkedIn")
  expect(screen.getByRole("dialog")).toHaveTextContent("证据")
  expect(screen.getByRole("dialog")).not.toHaveTextContent("已发布")
})

it("keeps each account task visible when one platform content has conflicting outcomes", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    const body = path.includes("/master-contents") ? { next: null, previous: null, results: [] }
      : path.includes("/platform-contents") ? { next: null, previous: null, results: [{ ...platformContent, status: "APPROVED" }] }
        : path.includes("/publish-tasks") ? { next: null, previous: null, results: [
          { id: "task-success", platform_content_id: "content-1", social_account_id: "account-a", connector_code: "OFFICIAL_API", status: "SUCCEEDED", provider_submission_id: "published-a" },
          { id: "task-unknown", platform_content_id: "content-1", social_account_id: "account-b", connector_code: "BUFFER", status: "SUBMISSION_UNKNOWN", provider_submission_id: "pending-b" },
        ] }
          : path.includes("/platforms") ? { results: [{ id: "linkedin", code: "LINKEDIN", name: "LinkedIn", capabilities: [] }] }
            : { user: { id: 1, username: "operator" }, organization: { id: "org", name: "Org", slug: "org" }, membership: { id: "member", role: "OPERATOR", status: "ACTIVE", permissions: ["publishing.read"] } }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }))
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(ContentPublishingPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  await userEvent.setup().click(await screen.findByRole("tab", { name: /已提交/ }))
  expect(await screen.findByText("账号：account-b")).toBeInTheDocument()
  expect(screen.getByText("平台提交状态待确认；请勿重复发布")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument()
  await userEvent.setup().click(screen.getByRole("tab", { name: /已发布/ }))
  expect(await screen.findByText("账号：account-a")).toBeInTheDocument()
})

it("loads the next cursor page and supports roving tab keyboard navigation", async () => {
  const user = userEvent.setup()
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    const body = path.includes("/master-contents?cursor=next") ? { next: null, previous: null, results: [{ ...platformContent, id: "master-2", status: "DRAFT" }] }
      : path.includes("/master-contents") ? { next: "/api/v1/master-contents?cursor=next", previous: null, results: [] }
        : path.includes("/platform-contents") ? { next: null, previous: null, results: [] }
          : path.includes("/publish-tasks") ? { next: null, previous: null, results: [] }
            : path.includes("/platforms") ? { results: [] }
              : { user: { id: 1, username: "operator" }, organization: { id: "org", name: "Org", slug: "org" }, membership: { id: "member", role: "OPERATOR", status: "ACTIVE", permissions: ["publishing.read"] } }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }))
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(ContentPublishingPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const review = await screen.findByRole("tab", { name: /待人工审核/ })
  review.focus()
  await user.keyboard("{ArrowRight}")
  expect(screen.getByRole("tab", { name: /已排期/ })).toHaveFocus()
  await user.keyboard("{End}")
  expect(screen.getByRole("tab", { name: /需要处理/ })).toHaveFocus()
  await user.click(screen.getByRole("tab", { name: /AI 草稿/ }))
  expect(await screen.findByText("Gear reliability")).toBeInTheDocument()
})

it("refreshes the workspace after dialog approval moves content out of review", async () => {
  const user = userEvent.setup()
  let approved = false
  document.cookie = "csrftoken=test-token"
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.includes("/platform-contents/content-1/approve") && init?.method === "POST") approved = true
    const body = path.includes("/master-contents") ? { next: null, previous: null, results: [] }
      : path.includes("/platform-contents/content-1/approve") ? { ...platformContent, status: "APPROVED" }
        : path.includes("/platform-contents") ? { next: null, previous: null, results: [{ ...platformContent, status: approved ? "APPROVED" : "IN_REVIEW" }] }
          : path.includes("/publish-tasks") ? { next: null, previous: null, results: [] }
            : path.includes("/platforms") ? { results: [{ id: "linkedin", code: "LINKEDIN", name: "LinkedIn", capabilities: [] }] }
              : { user: { id: 1, username: "operator" }, organization: { id: "org", name: "Org", slug: "org" }, membership: { id: "member", role: "OPERATOR", status: "ACTIVE", permissions: ["publishing.read", "content.review"] } }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }))
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(ContentPublishingPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  await user.click(await screen.findByRole("button", { name: /查看内容/ }))
  await user.click(screen.getByRole("button", { name: "通过" }))
  expect(await screen.findByRole("tab", { name: /准备发布 1/ })).toBeInTheDocument()
})

it("uses outcome-specific copy and keeps every tab panel target in the DOM", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    const body = path.includes("/master-contents") ? { next: null, previous: null, results: [] }
      : path.includes("/platform-contents") ? { next: null, previous: null, results: [{ ...platformContent, status: "APPROVED" }] }
        : path.includes("/publish-tasks") ? { next: null, previous: null, results: [
          { id: "failed", platform_content_id: "content-1", social_account_id: "failed-account", connector_code: "OFFICIAL_API", status: "FAILED", provider_submission_id: null },
          { id: "canceled", platform_content_id: "content-1", social_account_id: "canceled-account", connector_code: "OFFICIAL_API", status: "CANCELED", provider_submission_id: null },
          { id: "unknown", platform_content_id: "content-1", social_account_id: "unknown-account", connector_code: "BUFFER", status: "SUBMISSION_UNKNOWN", provider_submission_id: "pending" },
        ] }
          : path.includes("/platforms") ? { results: [] }
            : { user: { id: 1, username: "operator" }, organization: { id: "org", name: "Org", slug: "org" }, membership: { id: "member", role: "OPERATOR", status: "ACTIVE", permissions: ["publishing.read"] } }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }))
  }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(ContentPublishingPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

  const submitted = await screen.findByRole("tab", { name: /已提交/ })
  expect(submitted).toHaveAttribute("aria-controls", "publishing-panel-SUBMITTED")
  expect(document.getElementById(submitted.getAttribute("aria-controls") ?? "")).toBeInTheDocument()
  for (const stage of ["PREPARE", "AI_DRAFT", "SCHEDULED", "SUBMITTED", "PUBLISHED", "NEEDS_ATTENTION"]) {
    expect(document.getElementById(`publishing-panel-${stage}`)).toHaveProperty("hidden", true)
  }
  await userEvent.setup().click(submitted)
  expect(document.getElementById("publishing-panel-SUBMITTED")).toHaveProperty("hidden", false)
  for (const stage of ["PREPARE", "AI_DRAFT", "REVIEW", "SCHEDULED", "PUBLISHED", "NEEDS_ATTENTION"]) {
    expect(document.getElementById(`publishing-panel-${stage}`)).toHaveProperty("hidden", true)
  }
  expect(await screen.findByText("平台提交状态待确认；请勿重复发布")).toBeInTheDocument()
  await userEvent.setup().click(screen.getByRole("tab", { name: /需要处理/ }))
  expect(await screen.findByText("平台发布失败；请人工检查后处理")).toBeInTheDocument()
  expect(screen.getByText("发布任务已取消；尚未发布")).toBeInTheDocument()
})
