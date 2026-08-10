import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { VueQueryPlugin } from "@tanstack/vue-query"
import { flushPromises } from "@vue/test-utils"
import { afterEach, expect, it, vi } from "vitest"

import SourceImportDialog from "./SourceImportDialog.vue"

function testApp() {
  return { plugins: [VueQueryPlugin] }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

function job(status: "QUEUED" | "RUNNING" | "SUCCEEDED") {
  return { job_id: "job-1", status, type: "SOURCE_IMPORT", progress: 0, attempt: 1, max_attempts: 3, created_at: "2026-08-11T00:00:00Z", finished_at: status === "SUCCEEDED" ? "2026-08-11T00:01:00Z" : null, error: null, result_reference: null }
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it("puts link and paste first and moves structured imports under more ways", async () => {
  const user = userEvent.setup()
  render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })

  expect(screen.getByRole("tab", { name: "帖子链接" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "批量粘贴" })).toBeVisible()
  await user.click(screen.getByRole("button", { name: "更多导入方式" }))
  expect(screen.getByRole("tab", { name: "截图" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "CSV 文件" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "JSON 文件" })).toBeVisible()
})

it("announces understandable progress and stops polling after completion", async () => {
  vi.useFakeTimers()
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(json({ job_id: "job-1", ingestion_batch_id: "batch-1", status: "QUEUED" }, 202))
    .mockResolvedValueOnce(json(job("QUEUED")))
    .mockResolvedValueOnce(json(job("RUNNING")))
    .mockResolvedValueOnce(json(job("SUCCEEDED")))
  vi.stubGlobal("fetch", fetchMock)
  document.cookie = "csrftoken=token; path=/"
  render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })

  await user.type(screen.getByLabelText("公开链接"), "https://example.test/posts/1")
  await user.type(screen.getByLabelText("公开原文"), "需要替换齿轮")
  await user.click(screen.getByRole("button", { name: "导入公开信号" }))
  expect(screen.getByRole("status")).toHaveTextContent("正在接收")
  await flushPromises()
  expect(screen.getByRole("status")).toHaveTextContent("正在整理")

  await vi.advanceTimersByTimeAsync(1_000)
  expect(screen.getByRole("status")).toHaveTextContent("正在处理")
  await vi.advanceTimersByTimeAsync(1_000)
  expect(screen.getByRole("status")).toHaveTextContent("已完成")
  await vi.advanceTimersByTimeAsync(4_000)
  expect(fetchMock).toHaveBeenCalledTimes(4)
})
