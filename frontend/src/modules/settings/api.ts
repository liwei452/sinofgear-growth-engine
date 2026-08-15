import { apiRequest } from "../../api/client"

export type ProductAIStatus = {
  mode: "FAKE_OFFLINE" | "CONFIGURATION_REQUIRED" | "CONFIGURED_AI"
  provider_label: string
  model: string
  configured: boolean
  real_requests_enabled: boolean
}

export async function getProductAIStatus(): Promise<ProductAIStatus> {
  const result = await apiRequest<ProductAIStatus>("/api/v1/ai/provider-status")
  if (!result) throw new Error("产品 AI 状态响应为空。")
  return result
}
