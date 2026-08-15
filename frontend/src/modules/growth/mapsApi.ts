import { apiRequest } from "../../api/client"

export type GoogleMapsCity = {
  name: string
  country_code: string
}

export type GoogleMapsDiscoveryConfig = {
  api_key_configured: boolean
  enabled: boolean
  cities: GoogleMapsCity[]
  keywords: string[]
  radius_km: number
  daily_quota: number
  schedule_time: string
  next_run_at: string | null
  last_succeeded_at: string | null
  consecutive_failures: number
  last_error_code: string
}

export type GoogleMapsDiscoveryConfigInput = {
  api_key?: string
  enabled?: boolean
  cities?: GoogleMapsCity[]
  keywords?: string[]
  radius_km?: number
  daily_quota?: number
  schedule_time?: string
}

export type GoogleMapsDiscoveryRunResult = {
  config_id: string
  trigger: string
  fetched_count: number
  created_count: number
  duplicate_count: number
  skipped_count: number
}

export async function getGoogleMapsDiscoveryConfig(): Promise<GoogleMapsDiscoveryConfig> {
  const result = await apiRequest<GoogleMapsDiscoveryConfig>(
    "/api/v1/growth/maps-discovery/config",
  )
  if (!result) throw new Error("谷歌地图数据源配置响应为空。")
  return result
}

export async function updateGoogleMapsDiscoveryConfig(
  input: GoogleMapsDiscoveryConfigInput,
): Promise<GoogleMapsDiscoveryConfig> {
  const result = await apiRequest<GoogleMapsDiscoveryConfig>(
    "/api/v1/growth/maps-discovery/config",
    { method: "PUT", body: input },
  )
  if (!result) throw new Error("保存谷歌地图数据源配置失败。")
  return result
}

export async function runGoogleMapsDiscovery(): Promise<GoogleMapsDiscoveryRunResult> {
  const result = await apiRequest<GoogleMapsDiscoveryRunResult>(
    "/api/v1/growth/maps-discovery/run",
    { method: "POST" },
  )
  if (!result) throw new Error("运行谷歌地图自动发现失败。")
  return result
}
