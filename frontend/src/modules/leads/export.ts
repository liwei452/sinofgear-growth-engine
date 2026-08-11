import { safePublicHttpUrl, type LeadCandidateDetail } from "./api"

type LeadExportCandidate = {
  id: string
  version: number
  status: LeadCandidateDetail["status"]
  company_name: string
  company_domain: string
  country: string
  requirements: Array<{
    label: string
    value: string
    unit: string
    capability: string
    source_evidence_id: string
  }>
}

type LeadExportInsight = null | {
  conclusion: string
  score: number
  score_band: string
  high_value_eligible: boolean
  ai_confidence: string
  company_match_confidence: string
  evidence_confidence: string
  uncertainty: string[]
  review_reason: string
  human_correction: unknown
  reviewed_at: string | null
}

type LeadExportEvidence = {
  id: string
  source_signal_id: string
  url: string | null
  content: string
  translated_content: string
  platform: string
  language: string
  availability: string
  collection_method: string
  retention_class: string
  captured_at: string
  published_at: string | null
}

export type LeadExportV1 = {
  version: "1.0"
  exported_at: string
  candidate: LeadExportCandidate
  insight: LeadExportInsight
  source_evidence: LeadExportEvidence[]
}

function stringField(value: unknown, key: string): string {
  if (!value || typeof value !== "object") return ""
  const field = (value as Record<string, unknown>)[key]
  return typeof field === "string" ? field : ""
}

function explanationText(value: unknown): string {
  if (typeof value === "string" && value.trim()) return value.trim()
  if (value && typeof value === "object") {
    for (const key of ["summary", "reason", "text"]) {
      const text = (value as Record<string, unknown>)[key]
      if (typeof text === "string" && text.trim()) return text.trim()
    }
  }
  return ""
}

export function buildLeadExport(detail: LeadCandidateDetail): LeadExportV1 {
  const latest = detail.latest_insight
  return {
    version: "1.0",
    exported_at: new Date().toISOString(),
    candidate: {
      id: detail.id,
      version: detail.version,
      status: detail.status,
      company_name: stringField(detail.company, "name"),
      company_domain: stringField(detail.company, "domain"),
      country: stringField(detail.company, "country_hint"),
      requirements: detail.requirements.map((requirement) => ({
        label: requirement.requirement_label,
        value: requirement.extracted_value,
        unit: requirement.unit,
        capability: requirement.capability_label ?? "",
        source_evidence_id: requirement.source_evidence_id,
      })),
    },
    insight: latest ? {
      conclusion: explanationText(latest.explanation),
      score: latest.score,
      score_band: latest.score_band,
      high_value_eligible: latest.high_value_eligible,
      ai_confidence: latest.ai_confidence,
      company_match_confidence: latest.company_match_confidence,
      evidence_confidence: latest.evidence_confidence,
      uncertainty: Object.entries(latest.gates)
        .filter(([, passed]) => passed === false)
        .map(([gate]) => gate),
      review_reason: latest.review_reason,
      human_correction: latest.human_correction,
      reviewed_at: latest.reviewed_at,
    } : null,
    source_evidence: detail.evidence.map((evidence) => ({
      id: evidence.id,
      source_signal_id: evidence.source_signal_id,
      url: safePublicHttpUrl(evidence.source_url),
      content: evidence.original_text,
      translated_content: evidence.translated_text,
      platform: evidence.platform,
      language: evidence.language,
      availability: evidence.availability,
      collection_method: evidence.collection_method,
      retention_class: evidence.retention_class,
      captured_at: evidence.captured_at,
      published_at: evidence.public_published_at,
    })),
  }
}

function protectCsvFormula(value: string): string {
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0
    const isControl = codePoint <= 31 || (codePoint >= 127 && codePoint <= 159)
    if (isControl || /[\s\p{White_Space}]/u.test(character)) continue
    return "=+-@".includes(character) ? `'${value}` : value
  }
  return value
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined
    ? ""
    : typeof value === "string" ? value : JSON.stringify(value)
  return `"${protectCsvFormula(text).replaceAll('"', '""')}"`
}

function buildLeadCsv(detail: LeadCandidateDetail): string {
  const value = buildLeadExport(detail)
  const headers = [
    "export_version", "exported_at", "candidate_id", "candidate_version", "status",
    "company_name", "company_domain", "country", "conclusion", "score", "score_band",
    "ai_confidence", "company_match_confidence", "evidence_confidence", "uncertainty",
    "review_reason", "human_correction", "evidence_id", "source_signal_id", "source_url",
    "source_content", "translated_content", "platform", "language", "availability",
    "collection_method", "retention_class", "captured_at", "published_at",
  ]
  const evidenceRows: Array<LeadExportEvidence | null> = value.source_evidence.length
    ? value.source_evidence : [null]
  const rows = evidenceRows.map((evidence) => [
    value.version, value.exported_at, value.candidate.id, value.candidate.version, value.candidate.status,
    value.candidate.company_name, value.candidate.company_domain, value.candidate.country,
    value.insight?.conclusion ?? "", value.insight?.score ?? "", value.insight?.score_band ?? "",
    value.insight?.ai_confidence ?? "", value.insight?.company_match_confidence ?? "",
    value.insight?.evidence_confidence ?? "", value.insight?.uncertainty.join(" | ") ?? "",
    value.insight?.review_reason ?? "", value.insight?.human_correction ?? "",
    evidence?.id ?? "", evidence?.source_signal_id ?? "", evidence?.url ?? "", evidence?.content ?? "",
    evidence?.translated_content ?? "", evidence?.platform ?? "", evidence?.language ?? "",
    evidence?.availability ?? "", evidence?.collection_method ?? "", evidence?.retention_class ?? "",
    evidence?.captured_at ?? "", evidence?.published_at ?? "",
  ])
  return `\uFEFF${[headers, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n")}`
}

function download(content: string, type: string, filename: string): void {
  const objectUrl = URL.createObjectURL(new Blob([content], { type }))
  const anchor = document.createElement("a")
  anchor.href = objectUrl
  anchor.download = filename
  anchor.hidden = true
  document.body.append(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
    URL.revokeObjectURL(objectUrl)
  }
}

export function downloadLeadJson(detail: LeadCandidateDetail): void {
  download(JSON.stringify(buildLeadExport(detail), null, 2), "application/json;charset=utf-8", `lead-${detail.id}.json`)
}

export function downloadLeadCsv(detail: LeadCandidateDetail): void {
  download(buildLeadCsv(detail), "text/csv;charset=utf-8", `lead-${detail.id}.csv`)
}
