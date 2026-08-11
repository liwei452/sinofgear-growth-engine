import { afterEach, expect, it, vi } from "vitest"

import type { LeadCandidateDetail } from "./api"
import { buildLeadExport, downloadLeadCsv, downloadLeadJson } from "./export"

const leadDetail = {
  id: "lead-1",
  company: { name: "=ACME Gears", domain: "acme.example", country_hint: "DE", private_note: "omit me" },
  status: "REVIEWED",
  version: 3,
  created_at: "2026-08-10T00:00:00Z",
  updated_at: "2026-08-10T01:00:00Z",
  permitted_actions: ["DISMISS"],
  evidence: [{
    id: "evidence-1", source_signal_id: "signal-1", platform: "YOUTUBE",
    source_url: "https://example.test/post", original_text: "+Need replacement helical gears,\n200 pcs",
    translated_text: "需要替换斜齿轮", language: "en", availability: "AVAILABLE",
    collection_method: "MANUAL", retention_class: "STANDARD",
    captured_at: "2026-08-10T00:00:00Z", public_published_at: "2026-08-09T00:00:00Z",
  }],
  requirements: [{
    id: "requirement-1", requirement_code: "HELICAL_GEAR", requirement_label: "斜齿轮",
    capability_code: "GEAR_HOBBING", capability_label: "滚齿加工",
    capability_knowledge_evidence_id: "knowledge-1", source_evidence_id: "evidence-1",
    extracted_value: "200", unit: "pcs",
  }],
  review_history: [],
  insight_history: [],
  latest_insight: {
    id: "insight-1", source_insight_id: null, origin: "AI", score: 88, score_band: "HIGH",
    high_value_eligible: false, explanation: "明确提出替换需求", dimensions: {},
    gates: { traceable_source: true, capability_evidence: false },
    extracted_requirement_values: {}, ai_audit: { prompt: "private audit input", input_snapshot: { secret: true } },
    ai_confidence: "0.9000", company_match_confidence: "0.6000", evidence_confidence: "0.4000",
    review_reason: "人工确认了公开需求", human_correction: { company_name: "ACME Gears" },
    reviewed_at: "2026-08-11T00:00:00Z", reviewed_by: 7, version: 2,
    created_at: "2026-08-10T00:00:00Z",
  },
} satisfies LeadCandidateDetail

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.addEventListener("load", () => resolve(String(reader.result)))
    reader.addEventListener("error", () => reject(reader.error))
    reader.readAsText(blob)
  })
}

function readBlobBytes(blob: Blob): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.addEventListener("load", () => resolve(new Uint8Array(reader.result as ArrayBuffer)))
    reader.addEventListener("error", () => reject(reader.error))
    reader.readAsArrayBuffer(blob)
  })
}

function stubObjectUrls(createObjectURL: ReturnType<typeof vi.fn>, revokeObjectURL: ReturnType<typeof vi.fn>): void {
  const BrowserURL = URL
  class URLWithObjectUrls extends BrowserURL {}
  URLWithObjectUrls.createObjectURL = createObjectURL
  URLWithObjectUrls.revokeObjectURL = revokeObjectURL
  vi.stubGlobal("URL", URLWithObjectUrls)
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ""
})

it("exports the judgment together with immutable source evidence without private audit input", () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date("2026-08-11T08:00:00Z"))

  const value = buildLeadExport(leadDetail)

  expect(value).toMatchObject({
    version: "1.0",
    exported_at: "2026-08-11T08:00:00.000Z",
    candidate: { id: "lead-1", company_name: "=ACME Gears", country: "DE" },
    insight: {
      conclusion: "明确提出替换需求", score: 88, score_band: "HIGH",
      ai_confidence: "0.9000", human_correction: { company_name: "ACME Gears" },
      uncertainty: ["capability_evidence"],
    },
  })
  expect(value.source_evidence[0]).toMatchObject({
    url: "https://example.test/post",
    content: "+Need replacement helical gears,\n200 pcs",
    platform: "YOUTUBE",
  })
  expect(JSON.stringify(value)).not.toContain("private audit input")
  expect(JSON.stringify(value)).not.toContain("input_snapshot")
  expect(JSON.stringify(value)).not.toContain("private_note")
})

it("downloads safe quoted CSV with a BOM and revokes its object URL", async () => {
  const createObjectURL = vi.fn(() => "blob:lead-csv")
  const revokeObjectURL = vi.fn()
  stubObjectUrls(createObjectURL, revokeObjectURL)
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined)

  downloadLeadCsv(leadDetail)

  const blob = createObjectURL.mock.calls[0]?.[0] as Blob
  const csv = await readBlob(blob)
  expect([...await readBlobBytes(blob)].slice(0, 3)).toEqual([0xef, 0xbb, 0xbf])
  expect(csv).toContain("\"'=ACME Gears\"")
  expect(csv).toContain("\"'+Need replacement helical gears,\n200 pcs\"")
  expect(csv).toContain("https://example.test/post")
  expect(click).toHaveBeenCalledOnce()
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:lead-csv")
  expect(document.querySelector("a[download]")).not.toBeInTheDocument()
})

it("downloads allowlisted JSON and revokes its object URL", async () => {
  const createObjectURL = vi.fn(() => "blob:lead-json")
  const revokeObjectURL = vi.fn()
  stubObjectUrls(createObjectURL, revokeObjectURL)
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined)

  downloadLeadJson(leadDetail)

  const json = await readBlob(createObjectURL.mock.calls[0]?.[0] as Blob)
  expect(JSON.parse(json).source_evidence[0].content).toContain("replacement helical gears")
  expect(json).not.toContain("private audit input")
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:lead-json")
})
