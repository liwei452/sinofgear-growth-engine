import { afterEach, expect, it, vi } from "vitest"

import { ApiError } from "../../api/client"
import {
  contentQueryKeys,
  getCursorPage,
  listMasterContents,
  safeCursorUrl,
} from "./api"

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

it("keeps every content workflow query family isolated by organization", () => {
  expect(contentQueryKeys.campaigns("org-a")).toEqual(["content-workflow", "org-a", "campaigns"])
  expect(contentQueryKeys.briefs("org-a")).toEqual(["content-workflow", "org-a", "briefs"])
  expect(contentQueryKeys.jobs("org-a")).toEqual(["content-workflow", "org-a", "jobs"])
  expect(contentQueryKeys.masterContents("org-a", { status: "IN_REVIEW" })).toEqual([
    "content-workflow", "org-a", "master-contents", { status: "IN_REVIEW" },
  ])
  expect(contentQueryKeys.platformContents("org-b", {})).toEqual([
    "content-workflow", "org-b", "platform-contents", {},
  ])
  expect(contentQueryKeys.aiRun("org-b", "run-1")).toEqual([
    "content-workflow", "org-b", "ai-runs", "run-1",
  ])
  expect(contentQueryKeys.platforms("org-b")).toEqual(["content-workflow", "org-b", "platforms"])
  expect(contentQueryKeys.assets("org-b")).toEqual(["content-workflow", "org-b", "assets"])
})

it("accepts only same-origin cursor links at the exact requested API path", async () => {
  expect(safeCursorUrl("/api/v1/assets?cursor=abc", "/api/v1/assets")).toBe("/api/v1/assets?cursor=abc")
  expect(safeCursorUrl(`${window.location.origin}/api/v1/assets?cursor=abc`, "/api/v1/assets")).toBe("/api/v1/assets?cursor=abc")
  for (const unsafe of [
    "https://evil.example/api/v1/assets?cursor=x",
    "//evil.example/api/v1/assets?cursor=x",
    "/api/v1/jobs?cursor=wrong-resource",
    "not a url",
  ]) expect(safeCursorUrl(unsafe, "/api/v1/assets")).toBeNull()

  const fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)
  await expect(getCursorPage("https://evil.example/api/v1/assets", "/api/v1/assets"))
    .rejects.toBeInstanceOf(ApiError)
  expect(fetchMock).not.toHaveBeenCalled()
})

it("encodes content filters with URLSearchParams", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ next: null, previous: null, results: [] }), {
    status: 200, headers: { "Content-Type": "application/json" },
  }))
  vi.stubGlobal("fetch", fetchMock)

  await listMasterContents({ status: "IN_REVIEW", campaign: "campaign id", page_size: 20 })

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/master-contents?status=IN_REVIEW&campaign=campaign+id&page_size=20",
    expect.anything(),
  )
})
