import type { ChannelPackage } from "./api"

export type PackageFactEvidence = {
  id: string
  fieldName: string
  value: string
  sourceFilename: string
  sourcePage: number | null
  sourceExcerpt: string
}

export function safePackageText(value: unknown, maxLength: number): string {
  return typeof value === "string" ? value.trim().slice(0, maxLength) : ""
}

export function payloadText(
  channelPackage: ChannelPackage | undefined,
  field: string,
  maxLength = 2_000,
): string {
  const value = channelPackage?.payload[field]
  return typeof value === "string" ? value.trim().slice(0, maxLength) : ""
}

export function payloadList(channelPackage: ChannelPackage | undefined, field: string): string[] {
  const value = channelPackage?.payload[field]
  if (!Array.isArray(value)) return []
  return value.slice(0, 50).flatMap(item => (
    typeof item === "string" && item.trim() ? [item.trim().slice(0, 500)] : []
  ))
}

export function payloadShots(channelPackage: ChannelPackage | undefined): string[] {
  const value = channelPackage?.payload.shot_list
  if (!Array.isArray(value)) return []
  return value.slice(0, 20).flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [item.trim().slice(0, 500)]
    if (!item || typeof item !== "object" || Array.isArray(item)) return []
    const shot = item as Record<string, unknown>
    const visual = typeof shot.visual === "string" ? shot.visual.trim().slice(0, 300) : ""
    const onScreenText = typeof shot.on_screen_text === "string" ? shot.on_screen_text.trim().slice(0, 300) : ""
    const scene = typeof shot.scene === "string" ? shot.scene.trim().slice(0, 64) : ""
    return visual ? [[scene, visual, onScreenText].filter(Boolean).join(" · ")] : []
  })
}

export function packageFactEvidence(channelPackage: ChannelPackage | undefined): PackageFactEvidence[] {
  const raw = channelPackage?.payload.verified_fact_evidence
  if (!Array.isArray(raw)) return []
  return raw.slice(0, 50).flatMap((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return []
    const fact = entry as Record<string, unknown>
    const id = safePackageText(fact.fact_id, 36)
    const fieldName = safePackageText(fact.field_name, 100)
    const value = safePackageText(fact.value, 500)
    const sourceFilename = safePackageText(fact.source_filename, 255)
    const sourceExcerpt = safePackageText(fact.source_excerpt, 500)
    const sourcePage = typeof fact.source_page === "number" && Number.isSafeInteger(fact.source_page)
      && fact.source_page > 0 ? fact.source_page : null
    if (!id || !fieldName || !value || !sourceFilename || !sourceExcerpt) return []
    if (fact.is_demo === true) return []
    return [{ id, fieldName, value, sourceFilename, sourcePage, sourceExcerpt }]
  })
}
