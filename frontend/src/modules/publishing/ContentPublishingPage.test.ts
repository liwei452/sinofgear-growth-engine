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
