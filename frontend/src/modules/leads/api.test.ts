import { afterEach, expect, it, vi } from "vitest"

import { ApiError } from "../../api/client"
import {
  analyzeLeadCandidate,
  createIngestionBatch,
  createLeadReview,
  getJob,
  isActiveImportJob,
  listLeadCandidates,
  leadKeys,
  previewImport,
  safeLeadPageUrl,
  safePublicHttpUrl,
} from "./api"

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

it("keeps cursors on the lead endpoint", () => {
  expect(safeLeadPageUrl("/api/v1/lead-candidates?cursor=abc")).toBe("/api/v1/lead-candidates?cursor=abc")
  expect(safeLeadPageUrl("https://evil.example/leads")).toBeNull()
  expect(safeLeadPageUrl("/api/v1/jobs?cursor=abc")).toBeNull()
  expect(safeLeadPageUrl("//evil.example/api/v1/lead-candidates?cursor=abc")).toBeNull()
})

it("keeps organization data in every query key", () => {
  expect(leadKeys.list("org-a", { score_band: "HIGH" })[1]).toBe("org-a")
  expect(leadKeys.detail("org-b", "lead-1")[1]).toBe("org-b")
  expect(leadKeys.job("org-c", "job-1")[1]).toBe("org-c")
})

it("polls only import jobs that can still make progress", () => {
  expect(isActiveImportJob("QUEUED")).toBe(true)
  expect(isActiveImportJob("RUNNING")).toBe(true)
  expect(isActiveImportJob("RETRY_QUEUED")).toBe(true)
  expect(isActiveImportJob("SUCCEEDED")).toBe(false)
  expect(isActiveImportJob("FAILED")).toBe(false)
  expect(isActiveImportJob("CANCELED")).toBe(false)
})

it("accepts only public HTTP(S) links", () => {
  expect(safePublicHttpUrl("https://example.test/post")).toBe("https://example.test/post")
  expect(safePublicHttpUrl("mailto:hello@example.test")).toBeNull()
  expect(safePublicHttpUrl("javascript:alert(1)")).toBeNull()
  expect(safePublicHttpUrl("https://user:pass@example.test/post")).toBeNull()
  expect(safePublicHttpUrl("https://example.test/a b")).toBeNull()
})

it("submits a stable idempotency key inside the guided import", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn(async () => jsonResponse({
    job_id: "job-1", ingestion_batch_id: "batch-1", status: "QUEUED",
  }, 202))
  vi.stubGlobal("fetch", fetchMock)

  await expect(createIngestionBatch({
    mode: "PASTE",
    text: "https://example.test/post\tNeed replacement gears",
    idempotencyKey: "intent-1",
  })).resolves.toMatchObject({ job_id: "job-1" })

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/ingestion-batches",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        source_type: "PASTE",
        idempotency_key: "intent-1",
        payload: { text: "https://example.test/post\tNeed replacement gears" },
      }),
    }),
  )
})

it("maps every supported import mode without adding unsupported request fields", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn(async () => jsonResponse({
    job_id: "job-1", ingestion_batch_id: "batch-1", status: "QUEUED",
  }, 202))
  vi.stubGlobal("fetch", fetchMock)

  await createIngestionBatch({ mode: "URL", sourceUrl: "https://example.test/post", originalText: "Need gears", idempotencyKey: "url-1" })
  await createIngestionBatch({ mode: "SCREENSHOT", sourceUrl: "https://example.test/post", originalText: "Need gears", screenshotAssetId: "00000000-0000-0000-0000-000000000001", idempotencyKey: "shot-1" })
  await createIngestionBatch({ mode: "CSV", text: "source_url,original_text\nhttps://example.test/post,Need gears", importAssetId: "asset-2", idempotencyKey: "csv-1" })
  await createIngestionBatch({ mode: "JSON", text: '{"rows":[{"source_url":"https://example.test/post","original_text":"Need gears"}]}', idempotencyKey: "json-1" })

  expect(fetchMock.mock.calls.map(([, options]) => JSON.parse((options as RequestInit).body as string))).toEqual([
    { source_type: "URL", idempotency_key: "url-1", payload: { source_url: "https://example.test/post", original_text: "Need gears" } },
    { source_type: "SCREENSHOT", idempotency_key: "shot-1", payload: { source_url: "https://example.test/post", original_text: "Need gears", screenshot_asset_id: "00000000-0000-0000-0000-000000000001" } },
    { source_type: "CSV", idempotency_key: "csv-1", import_asset_id: "asset-2", payload: { text: "source_url,original_text\nhttps://example.test/post,Need gears" } },
    { source_type: "JSON", idempotency_key: "json-1", payload: { rows: [{ source_url: "https://example.test/post", original_text: "Need gears" }] } },
  ])
})

it("builds encoded filters and rejects missing API response bodies", async () => {
  const fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal("fetch", fetchMock)

  await expect(listLeadCandidates({ score_band: "HIGH", country: "United States", minimum_score: 80 }))
    .rejects.toBeInstanceOf(ApiError)
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/lead-candidates?score_band=HIGH&country=United+States&minimum_score=80",
    expect.anything(),
  )
})

it("returns row-indexed preview errors without network access", () => {
  const fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)

  expect(previewImport({
    mode: "CSV",
    text: "source_url,original_text\nhttps://example.test/post,Need gears\n,Missing URL",
    idempotencyKey: "csv-preview",
  })).toMatchObject({ validRows: 1, invalidRows: 1, messages: [{ row: 3 }] })
  expect(previewImport({ mode: "JSON", text: "{not json", idempotencyKey: "json-preview" }))
    .toMatchObject({ validRows: 0, invalidRows: 1, messages: [{ row: null }] })
  expect(previewImport({
    mode: "CSV",
    text: "source_url,original_text\nhttps://example.test/post,Need gears,unexpected value",
    idempotencyKey: "csv-surplus",
  })).toMatchObject({ validRows: 0, invalidRows: 1, messages: [{ row: 2 }] })
  expect(fetchMock).not.toHaveBeenCalled()
})

it("rejects unsupported import modes before making a request", async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)

  await expect(createIngestionBatch({ mode: "API", idempotencyKey: "unsupported" } as never))
    .rejects.toThrow("Unsupported import mode")
  expect(fetchMock).not.toHaveBeenCalled()
})

it("rejects unsafe row URLs at the request boundary without making a request", async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)
  const drafts = [
    { mode: "URL", sourceUrl: "javascript:alert(1)", originalText: "Need gears", idempotencyKey: "bad-url" },
    { mode: "SCREENSHOT", sourceUrl: "https://user:pass@example.test/post", originalText: "Need gears", screenshotAssetId: "00000000-0000-0000-0000-000000000001", idempotencyKey: "bad-shot" },
    { mode: "PASTE", text: "javascript:alert(1)\tNeed gears", idempotencyKey: "bad-paste" },
    { mode: "CSV", text: "source_url,original_text\njavascript:alert(1),Need gears", idempotencyKey: "bad-csv" },
    { mode: "JSON", text: '{"rows":[{"source_url":"javascript:alert(1)","original_text":"Need gears"}]}', idempotencyKey: "bad-json" },
  ] as const

  for (const draft of drafts) await expect(createIngestionBatch(draft)).rejects.toThrow("invalid rows")
  expect(fetchMock).not.toHaveBeenCalled()
})

it("matches backend row constraints in local previews", () => {
  expect(previewImport({
    mode: "JSON",
    text: JSON.stringify({ rows: [
      { source_url: "https://example.test/one", original_text: "x".repeat(20_001) },
      { source_url: "https://example.test/two", original_text: "Need gears", platform: "x".repeat(33) },
      { source_url: "https://example.test/three", original_text: "Need gears", signal_type: "INVALID" },
      { source_url: "https://example.test/four", original_text: "Need gears", author_name: 7 },
      { source_url: "https://example.test/five", original_text: "Need gears", published_at: "not-a-date" },
    ] }),
    idempotencyKey: "json-boundaries",
  })).toMatchObject({ validRows: 0, invalidRows: 5, messages: [{ row: 1 }, { row: 2 }, { row: 3 }, { row: 4 }, { row: 5 }] })
  expect(previewImport({
    mode: "SCREENSHOT",
    sourceUrl: "https://example.test/shot",
    originalText: "Need gears",
    screenshotAssetId: "not-a-uuid",
    idempotencyKey: "shot-boundary",
  })).toMatchObject({ validRows: 0, invalidRows: 1, messages: [{ row: 1 }] })
  expect(previewImport({
    mode: "CSV",
    text: "source_url,original_text,screenshot_asset_id\nhttps://example.test/csv,Need gears,not-a-uuid",
    idempotencyKey: "csv-boundary",
  })).toMatchObject({ validRows: 0, invalidRows: 1, messages: [{ row: 2 }] })
  expect(previewImport({
    mode: "PASTE",
    text: Array.from({ length: 10_001 }, (_, index) => `https://example.test/${index}\tNeed gears`).join("\n"),
    idempotencyKey: "paste-limit",
  })).toMatchObject({ validRows: 0, invalidRows: 1, messages: [{ row: null }] })
})

it("rejects calendar-invalid timestamps and accepts Django-compatible timezone boundaries", async () => {
  expect(previewImport({
    mode: "JSON",
    text: JSON.stringify({ rows: [
      { source_url: "https://example.test/leap", original_text: "Need gears", published_at: "2024-02-29T23:59:59.123456+14:00" },
      { source_url: "https://example.test/offset", original_text: "Need gears", published_at: "2024-02-29 00:00:00-03:30" },
      { source_url: "https://example.test/compact-offset", original_text: "Need gears", published_at: "2024-02-29T00:00:00+1430" },
      { source_url: "https://example.test/hour-positive", original_text: "Need gears", published_at: "2024-02-29T00:00:00+14" },
      { source_url: "https://example.test/hour-negative", original_text: "Need gears", published_at: "2024-02-29T00:00:00-03" },
    ] }),
    idempotencyKey: "valid-calendar-boundaries",
  })).toMatchObject({ validRows: 5, invalidRows: 0 })
  expect(previewImport({
    mode: "JSON",
    text: JSON.stringify({ rows: [
      { source_url: "https://example.test/out-of-range", original_text: "Need gears", published_at: "2026-02-28T10:00:00+24" },
      { source_url: "https://example.test/short", original_text: "Need gears", published_at: "2026-02-28T10:00:00+1" },
      { source_url: "https://example.test/ambiguous", original_text: "Need gears", published_at: "2026-02-28T10:00:00+140" },
    ] }),
    idempotencyKey: "invalid-offsets",
  })).toMatchObject({ validRows: 0, invalidRows: 3, messages: [{ row: 1 }, { row: 2 }, { row: 3 }] })

  const fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)
  const drafts = [
    { mode: "CSV", text: "source_url,original_text,published_at\nhttps://example.test/csv,Need gears,2026-02-29T10:00:00Z", idempotencyKey: "bad-leap-day" },
    { mode: "JSON", text: '{"rows":[{"source_url":"https://example.test/json","original_text":"Need gears","published_at":"2026-02-30T10:00:00Z"}]}', idempotencyKey: "bad-calendar-day" },
    { mode: "CSV", text: "source_url,original_text,published_at\nhttps://example.test/offset,Need gears,2026-02-28T10:00:00+24", idempotencyKey: "bad-offset" },
    { mode: "JSON", text: '{"rows":[{"source_url":"https://example.test/short","original_text":"Need gears","published_at":"2026-02-28T10:00:00+1"}]}', idempotencyKey: "bad-short-offset" },
  ] as const

  for (const draft of drafts) await expect(createIngestionBatch(draft)).rejects.toThrow("invalid rows")
  expect(fetchMock).not.toHaveBeenCalled()
})

it("sends expected versions and idempotency keys for analysis and review", async () => {
  document.cookie = "csrftoken=csrf-value; path=/"
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(jsonResponse({ job_id: "job-1", lead_candidate_id: "lead-1", status: "QUEUED" }, 202))
    .mockResolvedValueOnce(jsonResponse({ review_id: "review-1", lead_candidate_id: "lead-1", candidate_status: "REVIEWED", candidate_version: 3, insight_id: null, insight_version: null }, 201))
    .mockResolvedValueOnce(jsonResponse({ job_id: "job-1", status: "SUCCEEDED", type: "LEAD_ANALYZE", progress: 100, attempt: 1, max_attempts: 3, created_at: "2026-08-11T00:00:00Z", finished_at: "2026-08-11T00:01:00Z", error: null, result_reference: null }))
  vi.stubGlobal("fetch", fetchMock)

  await analyzeLeadCandidate("lead-1", { evidence_ids: ["evidence-1"], expected_version: 2, idempotency_key: "analyze-1" })
  await createLeadReview({ action: "CONFIRM", candidate_id: "lead-1", expected_version: 2, idempotency_key: "review-1", reason: "Evidence is sufficient." })
  await getJob("job-1")

  expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/lead-candidates/lead-1/analyze", expect.objectContaining({
    method: "POST", body: JSON.stringify({ evidence_ids: ["evidence-1"], expected_version: 2, idempotency_key: "analyze-1" }),
  }))
  expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/v1/lead-reviews", expect.objectContaining({
    method: "POST", body: JSON.stringify({ action: "CONFIRM", candidate_id: "lead-1", expected_version: 2, idempotency_key: "review-1", reason: "Evidence is sufficient." }),
  }))
  expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/v1/jobs/job-1", expect.anything())
})
