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

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise })
  return { promise, resolve, reject }
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

it("keeps tab focus usable and implements the tab relationships after disclosure", async () => {
  const user = userEvent.setup()
  render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  await user.click(screen.getByRole("button", { name: "更多导入方式" }))

  const screenshot = screen.getByRole("tab", { name: "截图" })
  expect(screenshot).toHaveFocus()
  expect(screenshot).toHaveAttribute("aria-controls", "source-import-panel")
  expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "source-import-tab-url")
  await user.keyboard("{End}")
  expect(screen.getByRole("tab", { name: "JSON 文件" })).toHaveFocus()
  await user.keyboard("{Home}")
  expect(screen.getByRole("tab", { name: "帖子链接" })).toHaveFocus()
  await user.keyboard("{ArrowRight}")
  expect(screen.getByRole("tab", { name: "批量粘贴" })).toHaveFocus()
})

it("makes an old poll inert after close and reopen", async () => {
  const user = userEvent.setup()
  const oldJob = deferred<Response>()
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(json({ job_id: "old-job", ingestion_batch_id: "old-batch", status: "QUEUED" }, 202))
    .mockImplementationOnce(() => oldJob.promise)
  vi.stubGlobal("fetch", fetchMock)
  document.cookie = "csrftoken=token; path=/"
  const view = render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  await user.type(screen.getByLabelText("公开链接"), "https://example.test/old")
  await user.type(screen.getByLabelText("公开原文"), "old public text")
  await user.click(screen.getByRole("button", { name: "导入公开信号" }))
  await flushPromises()
  await user.click(screen.getByRole("button", { name: "取消" }))
  await view.rerender({ organizationId: "org-2", open: true })
  oldJob.resolve(json(job("SUCCEEDED")))
  await flushPromises()
  expect(view.emitted("completed")).toBeUndefined()
  expect(screen.queryByText("已完成公开信息导入。")).not.toBeInTheDocument()
})

it("does not create a batch when a pending screenshot upload finishes after close", async () => {
  const user = userEvent.setup()
  vi.stubGlobal("URL", class extends URL { static createObjectURL = vi.fn(() => "blob:signal"); static revokeObjectURL = vi.fn() })
  const asset = deferred<Response>()
  const fetchMock = vi.fn().mockImplementation(() => asset.promise)
  vi.stubGlobal("fetch", fetchMock)
  document.cookie = "csrftoken=token; path=/"
  render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  await user.click(screen.getByRole("button", { name: "更多导入方式" }))
  await user.click(screen.getByRole("tab", { name: "截图" }))
  await user.type(screen.getByLabelText("公开链接"), "https://example.test/image")
  await user.type(screen.getByLabelText("公开原文"), "public text")
  await user.upload(screen.getByLabelText("截图文件"), new File(["image"], "signal.png", { type: "image/png" }))
  await user.click(screen.getByRole("button", { name: "导入公开信号" }))
  await user.click(screen.getByRole("button", { name: "取消" }))
  asset.resolve(json({ id: "asset-1" }, 201))
  await flushPromises()
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it("reopens ready for a new import while an old screenshot upload remains inert", async () => {
  const user = userEvent.setup()
  vi.stubGlobal("URL", class extends URL { static createObjectURL = vi.fn(() => "blob:signal"); static revokeObjectURL = vi.fn() })
  const asset = deferred<Response>()
  const fetchMock = vi.fn().mockImplementationOnce(() => asset.promise).mockResolvedValueOnce(json({ job_id: "new-job", ingestion_batch_id: "new-batch", status: "QUEUED" }, 202)).mockResolvedValueOnce(json(job("SUCCEEDED")))
  vi.stubGlobal("fetch", fetchMock)
  document.cookie = "csrftoken=token; path=/"
  const view = render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  await user.click(screen.getByRole("button", { name: "更多导入方式" })); await user.click(screen.getByRole("tab", { name: "截图" }))
  await user.type(screen.getByLabelText("公开链接"), "https://example.test/old"); await user.type(screen.getByLabelText("公开原文"), "old")
  await user.upload(screen.getByLabelText("截图文件"), new File(["image"], "old.png", { type: "image/png" })); await user.click(screen.getByRole("button", { name: "导入公开信号" }))
  await user.click(screen.getByRole("button", { name: "取消" })); await view.rerender({ organizationId: "org-1", open: true })
  await user.click(screen.getByRole("tab", { name: "帖子链接" }))
  expect(screen.getByRole("button", { name: "导入公开信号" })).toBeEnabled()
  await user.click(screen.getByRole("button", { name: "导入公开信号" })); await flushPromises()
  asset.resolve(json({ id: "old-asset" }, 201)); await flushPromises()
  expect(fetchMock).toHaveBeenCalledTimes(3)
})

it("cleans preview URLs and prevents failed or stale file reads from enabling submission", async () => {
  const user = userEvent.setup()
  const createUrl = vi.fn().mockReturnValueOnce("blob:first").mockReturnValueOnce("blob:second")
  const revokeUrl = vi.fn()
  vi.stubGlobal("URL", class extends URL { static createObjectURL = createUrl; static revokeObjectURL = revokeUrl })
  const view = render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  await user.click(screen.getByRole("button", { name: "更多导入方式" }))
  await user.click(screen.getByRole("tab", { name: "截图" }))
  await user.upload(screen.getByLabelText("截图文件"), new File(["one"], "one.png", { type: "image/png" }))
  await user.upload(screen.getByLabelText("截图文件"), new File(["two"], "two.png", { type: "image/png" }))
  expect(revokeUrl).toHaveBeenCalledWith("blob:first")
  await view.rerender({ organizationId: "org-1", open: false })
  expect(revokeUrl).toHaveBeenCalledWith("blob:second")

  await view.rerender({ organizationId: "org-1", open: true })
  await user.click(screen.getByRole("tab", { name: "CSV 文件" }))
  const bad = new File(["ignored"], "bad.csv", { type: "text/csv" })
  Object.defineProperty(bad, "text", { value: vi.fn().mockRejectedValue(new Error("read failed")) })
  await user.upload(screen.getAllByLabelText("CSV 文件").find((element) => element.tagName === "INPUT")!, bad)
  await flushPromises()
  expect(screen.getByRole("alert")).toHaveTextContent("文件没有读取成功")
  expect(screen.getByRole("button", { name: "导入公开信号" })).toBeDisabled()
})
