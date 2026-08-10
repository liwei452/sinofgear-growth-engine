import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query"
import { flushPromises } from "@vue/test-utils"
import { afterEach, expect, it, vi } from "vitest"

import SourceImportDialog from "./SourceImportDialog.vue"

function testApp(queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return { plugins: [[VueQueryPlugin, { queryClient }]] }
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

it("makes an active and pending poll inert when unmounted", async () => {
  vi.useFakeTimers()
  const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout")
  const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout")
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  const pendingPoll = deferred<Response>()
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(json({ job_id: "job-1", ingestion_batch_id: "batch-1", status: "QUEUED" }, 202))
    .mockResolvedValueOnce(json(job("QUEUED")))
    .mockImplementationOnce(() => pendingPoll.promise)
  vi.stubGlobal("fetch", fetchMock); document.cookie = "csrftoken=token; path=/"
  const view = render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  await user.type(screen.getByLabelText("公开链接"), "https://example.test/post"); await user.type(screen.getByLabelText("公开原文"), "text"); await user.click(screen.getByRole("button", { name: "导入公开信号" })); await flushPromises()
  await vi.advanceTimersByTimeAsync(1_000)
  expect(fetchMock).toHaveBeenCalledTimes(3)
  const pollTimerIndex = setTimeoutSpy.mock.calls.findIndex(([, delay]) => delay === 1_000)
  expect(pollTimerIndex).toBeGreaterThanOrEqual(0)
  const pollTimer = setTimeoutSpy.mock.results[pollTimerIndex].value

  view.unmount()
  expect(clearTimeoutSpy).toHaveBeenCalledWith(pollTimer)
  pendingPoll.resolve(json(job("SUCCEEDED")))
  await flushPromises()
  await vi.advanceTimersByTimeAsync(5_000)
  expect(fetchMock).toHaveBeenCalledTimes(3)
  expect(view.emitted("completed")).toBeUndefined()
  setTimeoutSpy.mockRestore()
  clearTimeoutSpy.mockRestore()
})

it("ignores stale CSV and JSON reads after mode, close, and newer-file changes", async () => {
  const user = userEvent.setup()
  const csv = deferred<string>(); const jsonRead = deferred<string>(); const newer = deferred<string>()
  const view = render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  await user.click(screen.getByRole("button", { name: "更多导入方式" })); await user.click(screen.getByRole("tab", { name: "CSV 文件" }))
  const csvFile = new File(["x"], "old.csv"); Object.defineProperty(csvFile, "text", { value: () => csv.promise })
  await user.upload(screen.getAllByLabelText("CSV 文件").find((item) => item.tagName === "INPUT")!, csvFile)
  await user.click(screen.getByRole("tab", { name: "JSON 文件" })); csv.resolve("source_url,original_text\nhttps://example.test/old,text"); await flushPromises()
  expect(screen.getByRole("button", { name: "导入公开信号" })).toBeDisabled()
  const jsonFile = new File(["x"], "old.json"); Object.defineProperty(jsonFile, "text", { value: () => jsonRead.promise })
  await user.upload(screen.getAllByLabelText("JSON 文件").find((item) => item.tagName === "INPUT")!, jsonFile)
  await view.rerender({ organizationId: "org-1", open: false }); await view.rerender({ organizationId: "org-1", open: true }); jsonRead.reject(new Error("late")); await flushPromises()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  await user.click(screen.getByRole("tab", { name: "JSON 文件" }))
  const nextFile = new File(["x"], "new.json"); Object.defineProperty(nextFile, "text", { value: () => newer.promise })
  await user.upload(screen.getAllByLabelText("JSON 文件").find((item) => item.tagName === "INPUT")!, nextFile); newer.resolve('{"rows":[{"source_url":"https://example.test/new","original_text":"text"}]}'); await flushPromises()
  expect(screen.getByRole("button", { name: "导入公开信号" })).toBeEnabled()
})

it("isolates active polling when the organization changes and scopes the new job cache", async () => {
  vi.useFakeTimers()
  const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout")
  const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout")
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const oldPoll = deferred<Response>()
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(json({ job_id: "timer-job", ingestion_batch_id: "timer-batch", status: "QUEUED" }, 202))
    .mockResolvedValueOnce(json({ ...job("QUEUED"), job_id: "timer-job" }))
    .mockResolvedValueOnce(json({ job_id: "old-job", ingestion_batch_id: "old-batch", status: "QUEUED" }, 202))
    .mockImplementationOnce(() => oldPoll.promise)
    .mockResolvedValueOnce(json({ job_id: "new-job", ingestion_batch_id: "new-batch", status: "QUEUED" }, 202))
    .mockResolvedValueOnce(json({ ...job("SUCCEEDED"), job_id: "new-job" }))
  vi.stubGlobal("fetch", fetchMock)
  document.cookie = "csrftoken=token; path=/"
  const view = render(SourceImportDialog, {
    props: { organizationId: "org-1", open: true },
    global: testApp(queryClient),
  })
  await user.type(screen.getByLabelText("公开链接"), "https://example.test/post")
  await user.type(screen.getByLabelText("公开原文"), "public text")

  await user.click(screen.getByRole("button", { name: "导入公开信号" }))
  await flushPromises()
  const pollTimerIndex = setTimeoutSpy.mock.calls.findIndex(([, delay]) => delay === 1_000)
  expect(pollTimerIndex).toBeGreaterThanOrEqual(0)
  const oldTimer = setTimeoutSpy.mock.results[pollTimerIndex].value
  await view.rerender({ organizationId: "org-2", open: true })
  expect(clearTimeoutSpy).toHaveBeenCalledWith(oldTimer)

  await view.rerender({ organizationId: "org-1", open: true })
  await user.click(screen.getByRole("button", { name: "导入公开信号" }))
  await flushPromises()
  await view.rerender({ organizationId: "org-2", open: true })
  expect(screen.getByRole("button", { name: "导入公开信号" })).toBeEnabled()
  await user.click(screen.getByRole("button", { name: "导入公开信号" }))
  await flushPromises()

  expect(queryClient.getQueryData(["leads", "org-2", "job", "new-job"])).toMatchObject({ status: "SUCCEEDED" })
  expect(queryClient.getQueryData(["leads", "org-1", "job", "new-job"])).toBeUndefined()
  expect(view.emitted("completed")).toEqual([[{ batchId: "new-batch", jobId: "new-job" }]])

  oldPoll.resolve(json({ ...job("SUCCEEDED"), job_id: "old-job" }))
  await flushPromises()
  await vi.advanceTimersByTimeAsync(5_000)
  expect(fetchMock).toHaveBeenCalledTimes(6)
  expect(view.emitted("completed")).toEqual([[{ batchId: "new-batch", jobId: "new-job" }]])
  setTimeoutSpy.mockRestore()
  clearTimeoutSpy.mockRestore()
})

it("keeps newer CSV and JSON previews when older file reads settle later", async () => {
  const user = userEvent.setup()
  const oldCsv = deferred<string>()
  const oldJson = deferred<string>()
  render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  await user.click(screen.getByRole("button", { name: "更多导入方式" }))
  await user.click(screen.getByRole("tab", { name: "CSV 文件" }))
  const csvInput = screen.getAllByLabelText("CSV 文件").find((item) => item.tagName === "INPUT")!
  const staleCsv = new File(["old"], "old.csv", { type: "text/csv" })
  const newestCsv = new File(["new"], "new.csv", { type: "text/csv" })
  Object.defineProperty(staleCsv, "text", { value: () => oldCsv.promise })
  Object.defineProperty(newestCsv, "text", { value: () => Promise.resolve("source_url,original_text\nhttps://example.test/new-1,text\nhttps://example.test/new-2,text") })
  await user.upload(csvInput, staleCsv)
  await user.upload(csvInput, newestCsv)
  await flushPromises()
  expect(screen.getByText(/2/, { selector: ".preview span" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "导入公开信号" })).toBeEnabled()

  oldCsv.resolve("source_url,original_text\nhttps://example.test/stale,text")
  await flushPromises()
  expect(screen.getByText(/2/, { selector: ".preview span" })).toBeInTheDocument()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()

  await user.click(screen.getByRole("tab", { name: "JSON 文件" }))
  const jsonInput = screen.getAllByLabelText("JSON 文件").find((item) => item.tagName === "INPUT")!
  const staleJson = new File(["old"], "old.json", { type: "application/json" })
  const newestJson = new File(["new"], "new.json", { type: "application/json" })
  Object.defineProperty(staleJson, "text", { value: () => oldJson.promise })
  Object.defineProperty(newestJson, "text", { value: () => Promise.resolve('{"rows":[{"source_url":"https://example.test/new-1","original_text":"text"},{"source_url":"https://example.test/new-2","original_text":"text"}]}') })
  await user.upload(jsonInput, staleJson)
  await user.upload(jsonInput, newestJson)
  await flushPromises()
  oldJson.reject(new Error("stale read failed"))
  await flushPromises()
  expect(screen.getByText(/2/, { selector: ".preview span" })).toBeInTheDocument()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "导入公开信号" })).toBeEnabled()
})

it("revokes a live screenshot object URL on unmount", async () => {
  const user = userEvent.setup()
  const revokeUrl = vi.fn()
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn(() => "blob:unmount-preview")
    static revokeObjectURL = revokeUrl
  })
  const view = render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  await user.click(screen.getByRole("button", { name: "更多导入方式" }))
  await user.click(screen.getByRole("tab", { name: "截图" }))
  await user.upload(screen.getByLabelText("截图文件"), new File(["image"], "signal.png", { type: "image/png" }))

  view.unmount()
  expect(revokeUrl).toHaveBeenCalledTimes(1)
  expect(revokeUrl).toHaveBeenCalledWith("blob:unmount-preview")
})

it("recovers from a private screenshot upload failure and retries the unchanged intent once", async () => {
  const user = userEvent.setup()
  const randomUuid = vi.spyOn(globalThis.crypto, "randomUUID")
    .mockReturnValue("00000000-0000-4000-8000-000000000001")
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn(() => "blob:retry-preview")
    static revokeObjectURL = vi.fn()
  })
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(json({ detail: "private upload failed" }, 500))
    .mockResolvedValueOnce(json({ id: "00000000-0000-4000-8000-000000000002" }, 201))
    .mockResolvedValueOnce(json({ job_id: "job-1", ingestion_batch_id: "batch-1", status: "QUEUED" }, 202))
    .mockResolvedValueOnce(json(job("SUCCEEDED")))
  vi.stubGlobal("fetch", fetchMock)
  document.cookie = "csrftoken=token; path=/"
  const view = render(SourceImportDialog, { props: { organizationId: "org-1", open: true }, global: testApp() })
  await user.click(screen.getByRole("button", { name: "更多导入方式" }))
  await user.click(screen.getByRole("tab", { name: "截图" }))
  await user.type(screen.getByLabelText("公开链接"), "https://example.test/image")
  await user.type(screen.getByLabelText("公开原文"), "public text")
  await user.upload(screen.getByLabelText("截图文件"), new File(["image"], "signal.png", { type: "image/png" }))

  await user.click(screen.getByRole("button", { name: "导入公开信号" }))
  await flushPromises()
  expect(screen.getByRole("alert")).toHaveTextContent("服务暂时不可用，请稍后重试。")
  const recover = screen.getByRole("button", { name: "重新上传截图" })
  expect(recover).toBeVisible()
  await user.click(recover)
  expect(screen.getByLabelText("截图文件")).toHaveFocus()

  await user.click(screen.getByRole("button", { name: "导入公开信号" }))
  await flushPromises()
  const ingestionCalls = fetchMock.mock.calls.filter(([path]) => path === "/api/v1/ingestion-batches")
  expect(ingestionCalls).toHaveLength(1)
  expect(JSON.parse((ingestionCalls[0][1] as RequestInit).body as string)).toMatchObject({
    idempotency_key: "00000000-0000-4000-8000-000000000001",
  })
  expect(randomUuid).toHaveBeenCalledTimes(1)
  expect(view.emitted("completed")).toEqual([[{ batchId: "batch-1", jobId: "job-1" }]])
  view.unmount()
  randomUuid.mockRestore()
})
