import { ApiError, apiRequest } from "../../api/client"
import type { components } from "../../api/generated/schema"

export type LeadCandidateList = components["schemas"]["LeadCandidateList"]
export type LeadCandidateDetail = components["schemas"]["LeadCandidateDetail"]
export type LeadCandidatePage = components["schemas"]["LeadCandidatePage"]
export type IngestionBatchCreate = components["schemas"]["IngestionBatchCreate"]
export type IngestionAccepted = components["schemas"]["IngestionAccepted"]
export type Job = components["schemas"]["Job"]
export type LeadAnalyzeRequest = components["schemas"]["LeadAnalyzeRequest"]
export type LeadAnalyzeAccepted = components["schemas"]["LeadAnalyzeAccepted"]
export type LeadReviewCreate = components["schemas"]["LeadReviewCreate"]
export type LeadReviewResult = components["schemas"]["LeadReviewResult"]

export type LeadFilters = {
  status?: LeadCandidateList["status"]
  score_band?: "HIGH" | "LOW" | "OBSERVE" | "WATCH"
  minimum_score?: number
  platform?: string
  country?: string
  review_state?: "REVIEWED" | "UNREVIEWED"
  created_after?: string
  created_before?: string
  page_size?: number
}

export type ImportDraft =
  | { mode: "URL"; sourceUrl: string; originalText: string; idempotencyKey: string }
  | { mode: "SCREENSHOT"; sourceUrl: string; originalText: string; screenshotAssetId: string; idempotencyKey: string }
  | { mode: "CSV"; text: string; importAssetId?: string; idempotencyKey: string }
  | { mode: "JSON"; text: string; importAssetId?: string; idempotencyKey: string }
  | { mode: "PASTE"; text: string; idempotencyKey: string }

export type ImportPreviewMessage = { row: number | null; message: string }
export type ImportPreview = {
  validRows: number
  invalidRows: number
  messages: ImportPreviewMessage[]
}

const leadPath = "/api/v1/lead-candidates"
const supportedImportModes = new Set<ImportDraft["mode"]>(["URL", "SCREENSHOT", "CSV", "JSON", "PASTE"])
const maxImportRows = 10_000
const maxOriginalTextChars = 20_000
const supportedSignalTypes = new Set([
  "COMMENT", "POST_AUTHOR", "CHANNEL_OWNER", "PROFILE_MATCH", "MENTION", "HASHTAG_MATCH",
])
const supportedCsvHeaders = new Set([
  "platform", "source_url", "signal_type", "original_text", "author_name", "published_at", "screenshot_asset_id",
])

export const leadKeys = {
  all: (organizationId: string) => ["leads", organizationId] as const,
  list: (organizationId: string, filters: LeadFilters) => [...leadKeys.all(organizationId), "list", filters] as const,
  detail: (organizationId: string, candidateId: string) => [...leadKeys.all(organizationId), "detail", candidateId] as const,
  job: (organizationId: string, jobId: string) => [...leadKeys.all(organizationId), "job", jobId] as const,
}

function required<T>(value: T | undefined, message = "The server returned no data. Please try again."): T {
  if (value === undefined) throw new ApiError(0, message)
  return value
}

function queryUrl(path: string, filters: Record<string, unknown>): string {
  const parameters = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") parameters.set(key, String(value))
  }
  const query = parameters.toString()
  return query ? `${path}?${query}` : path
}

export function safeLeadPageUrl(value: string | null): string | null {
  if (!value) return null
  let target: URL
  try {
    target = new URL(value, window.location.origin)
  } catch {
    return null
  }
  if (target.origin !== window.location.origin || target.pathname !== leadPath) return null
  return `${target.pathname}${target.search}`
}

export function safePublicHttpUrl(value: string): string | null {
  if (typeof value !== "string" || !value || [...value].some((character) => character.charCodeAt(0) <= 32)) return null
  try {
    const url = new URL(value)
    if (url.protocol !== "http:" && url.protocol !== "https:") return null
    if (!url.hostname || url.username || url.password) return null
    return url.href
  } catch {
    return null
  }
}

function invalid(row: number | null, message: string): ImportPreviewMessage {
  return { row, message }
}

function isUuid(value: unknown): boolean {
  return typeof value === "string"
    && /^\{?[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\}?$/i.test(value)
}

function isIsoDateTime(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?$/.test(value)) return false
  return !Number.isNaN(Date.parse(value.replace(",", ".")))
}

function validateRow(raw: unknown, row: number, screenshotRequired = false): ImportPreviewMessage | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid(row, "This row must be an object.")
  const record = raw as Record<string, unknown>
  if (typeof record.source_url !== "string" || !safePublicHttpUrl(record.source_url)) {
    return invalid(row, "Provide a public HTTP or HTTPS source URL.")
  }
  if (typeof record.original_text !== "string" || !record.original_text.trim()) {
    return invalid(row, "Provide the public source text.")
  }
  if (record.original_text.length > maxOriginalTextChars) {
    return invalid(row, `Shorten the public source text to ${maxOriginalTextChars} characters.`)
  }
  const platform = record.platform ?? "MANUAL"
  if (typeof platform !== "string" || !platform.trim() || platform.trim().length > 32) {
    return invalid(row, "Provide a platform name of at most 32 characters.")
  }
  const signalType = record.signal_type ?? "MENTION"
  if (typeof signalType !== "string" || !supportedSignalTypes.has(signalType.trim().toUpperCase())) {
    return invalid(row, "Use a supported public signal type.")
  }
  const authorName = record.author_name ?? ""
  if (typeof authorName !== "string" || authorName.length > 255) {
    return invalid(row, "Use a public author name of at most 255 characters.")
  }
  const publishedAt = record.published_at
  if (publishedAt !== undefined && publishedAt !== null && publishedAt !== ""
    && (typeof publishedAt !== "string" || !isIsoDateTime(publishedAt))) {
    return invalid(row, "Use an ISO 8601 publication timestamp.")
  }
  const screenshotAssetId = record.screenshot_asset_id
  if (screenshotRequired && (screenshotAssetId === undefined || screenshotAssetId === null || screenshotAssetId === "")) {
    return invalid(row, "Attach the private screenshot asset.")
  }
  if (screenshotAssetId !== undefined && screenshotAssetId !== null && screenshotAssetId !== "" && !isUuid(screenshotAssetId)) {
    return invalid(row, "Attach a valid private screenshot asset.")
  }
  return null
}

function previewRows(rows: unknown[], startRow: number, screenshotRequired = false): ImportPreview {
  if (rows.length > maxImportRows) {
    return { validRows: 0, invalidRows: 1, messages: [invalid(null, `Reduce the import to ${maxImportRows} rows or fewer.`)] }
  }
  const messages = rows.flatMap((row, index) => {
    const issue = validateRow(row, startRow + index, screenshotRequired)
    return issue ? [issue] : []
  })
  return { validRows: rows.length - messages.length, invalidRows: messages.length, messages }
}

function parseCsv(text: string): { headers: string[]; rows: string[][] } | ImportPreviewMessage {
  const rows: string[][] = []
  let row: string[] = []
  let field = ""
  let quoted = false
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        field += '"'
        index += 1
      } else if (character === '"') {
        quoted = false
      } else {
        field += character
      }
      continue
    }
    if (character === '"') {
      if (field) return invalid(rows.length + 1, "CSV quotes must start at the beginning of a field.")
      quoted = true
    } else if (character === ",") {
      row.push(field)
      field = ""
    } else if (character === "\n") {
      row.push(field.replace(/\r$/, ""))
      rows.push(row)
      row = []
      field = ""
    } else {
      field += character
    }
  }
  if (quoted) return invalid(rows.length + 1, "CSV contains an unclosed quoted field.")
  if (field || row.length) {
    row.push(field.replace(/\r$/, ""))
    rows.push(row)
  }
  const [headers = [], ...dataRows] = rows
  return { headers, rows: dataRows }
}

function previewCsv(text: string): ImportPreview {
  const parsed = parseCsv(text.replace(/^\uFEFF/, ""))
  if ("row" in parsed) return { validRows: 0, invalidRows: 1, messages: [parsed] }
  if (!parsed.headers.length || parsed.headers.some((header) => !supportedCsvHeaders.has(header)) || new Set(parsed.headers).size !== parsed.headers.length) {
    return { validRows: 0, invalidRows: 1, messages: [invalid(1, "CSV must include unique supported headers.")] }
  }
  if (parsed.rows.length > maxImportRows) {
    return { validRows: 0, invalidRows: 1, messages: [invalid(null, `Reduce the import to ${maxImportRows} rows or fewer.`)] }
  }
  const messages: ImportPreviewMessage[] = []
  let validRows = 0
  parsed.rows.forEach((values, index) => {
    if (values.length > parsed.headers.length) {
      messages.push(invalid(index + 2, "Remove values without matching CSV headers."))
      return
    }
    const issue = validateRow(
      Object.fromEntries(parsed.headers.map((header, column) => [header, values[column] ?? ""])),
      index + 2,
    )
    if (issue) messages.push(issue)
    else validRows += 1
  })
  return { validRows, invalidRows: messages.length, messages }
}

function previewJson(text: string): ImportPreview {
  const payload = jsonPayload(text)
  if (!payload) return { validRows: 0, invalidRows: 1, messages: [invalid(null, "JSON must contain a rows list.")] }
  return previewRows(payload.rows as unknown[], 1)
}

function jsonPayload(text: string): Record<string, unknown> | null {
  let payload: unknown
  try {
    payload = JSON.parse(text)
  } catch {
    return null
  }
  if (!payload || typeof payload !== "object" || !Array.isArray((payload as { rows?: unknown }).rows)) {
    return null
  }
  return payload as Record<string, unknown>
}

export function previewImport(draft: ImportDraft): ImportPreview {
  switch (draft.mode) {
    case "URL":
      return previewRows([{ source_url: draft.sourceUrl, original_text: draft.originalText }], 1)
    case "SCREENSHOT":
      return previewRows([{
        source_url: draft.sourceUrl,
        original_text: draft.originalText,
        screenshot_asset_id: draft.screenshotAssetId,
      }], 1, true)
    case "PASTE": {
      const rows = draft.text.split(/\r?\n/).flatMap((line) => line.trim() ? [line] : [])
      if (rows.length > maxImportRows) {
        return { validRows: 0, invalidRows: 1, messages: [invalid(null, `Reduce the import to ${maxImportRows} rows or fewer.`)] }
      }
      const messages: ImportPreviewMessage[] = []
      let validRows = 0
      draft.text.split(/\r?\n/).forEach((line, index) => {
        if (!line.trim()) return
        const [sourceUrl, ...text] = line.split("\t")
        const issue = validateRow({ source_url: sourceUrl, original_text: text.join("\t") }, index + 1)
        if (issue) messages.push(issue)
        else validRows += 1
      })
      return { validRows, invalidRows: rows.length - validRows, messages }
    }
    case "CSV":
      return previewCsv(draft.text)
    case "JSON":
      return previewJson(draft.text)
  }
}

function ingestionPayload(draft: ImportDraft): IngestionBatchCreate {
  if (!supportedImportModes.has(draft.mode)) throw new Error("Unsupported import mode")
  const preview = previewImport(draft)
  if (!preview.validRows || preview.invalidRows) throw new Error("Import contains invalid rows.")
  switch (draft.mode) {
    case "URL":
      return {
        source_type: "URL",
        idempotency_key: draft.idempotencyKey,
        payload: { source_url: draft.sourceUrl, original_text: draft.originalText },
      }
    case "SCREENSHOT":
      return {
        source_type: "SCREENSHOT",
        idempotency_key: draft.idempotencyKey,
        payload: {
          source_url: draft.sourceUrl,
          original_text: draft.originalText,
          screenshot_asset_id: draft.screenshotAssetId,
        },
      }
    case "CSV":
      return {
        source_type: "CSV",
        idempotency_key: draft.idempotencyKey,
        ...(draft.importAssetId ? { import_asset_id: draft.importAssetId } : {}),
        payload: { text: draft.text },
      }
    case "JSON": {
      const payload = jsonPayload(draft.text)
      if (!payload) throw new Error("Import contains invalid rows.")
      return {
        source_type: "JSON",
        idempotency_key: draft.idempotencyKey,
        ...(draft.importAssetId ? { import_asset_id: draft.importAssetId } : {}),
        payload,
      }
    }
    case "PASTE":
      return { source_type: "PASTE", idempotency_key: draft.idempotencyKey, payload: { text: draft.text } }
  }
}

export async function listLeadCandidates(filters: LeadFilters = {}): Promise<LeadCandidatePage> {
  return required(await apiRequest<LeadCandidatePage>(queryUrl(leadPath, filters)))
}

export async function getLeadCandidate(candidateId: string): Promise<LeadCandidateDetail> {
  return required(await apiRequest<LeadCandidateDetail>(`${leadPath}/${encodeURIComponent(candidateId)}`))
}

export async function createIngestionBatch(draft: ImportDraft): Promise<IngestionAccepted> {
  return required(await apiRequest<IngestionAccepted>("/api/v1/ingestion-batches", {
    method: "POST",
    body: ingestionPayload(draft),
  }))
}

export async function getJob(jobId: string): Promise<Job> {
  return required(await apiRequest<Job>(`/api/v1/jobs/${encodeURIComponent(jobId)}`))
}

export async function analyzeLeadCandidate(
  candidateId: string,
  input: LeadAnalyzeRequest,
): Promise<LeadAnalyzeAccepted> {
  return required(await apiRequest<LeadAnalyzeAccepted>(`${leadPath}/${encodeURIComponent(candidateId)}/analyze`, {
    method: "POST",
    body: input,
  }))
}

export async function createLeadReview(input: LeadReviewCreate): Promise<LeadReviewResult> {
  return required(await apiRequest<LeadReviewResult>("/api/v1/lead-reviews", { method: "POST", body: input }))
}
