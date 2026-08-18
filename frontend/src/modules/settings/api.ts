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

export type AIProviderConfig = {
  provider: "deepseek"
  model: "deepseek-chat" | "deepseek-reasoner"
  configured: boolean
  enabled: boolean
  daily_budget_micros: number | null
  daily_spent_micros: number
  daily_reserved_micros: number
  price_table_version: string
  last_tested_at: string | null
  last_success_at: string | null
  last_error_code: string
}

export type AIProviderConfigInput = {
  provider: "deepseek"
  model: AIProviderConfig["model"]
  enabled: boolean
  daily_budget_micros: number | null
  api_key?: string
}

export type AIProviderConnectionResult = { ok: boolean; latency_ms: number }

export async function getAIProviderConfig(): Promise<AIProviderConfig> {
  const result = await apiRequest<AIProviderConfig>("/api/v1/ai/provider-config")
  if (!result) throw new Error("AI 模型配置响应为空。")
  return result
}

export async function saveAIProviderConfig(input: AIProviderConfigInput): Promise<AIProviderConfig> {
  const result = await apiRequest<AIProviderConfig>("/api/v1/ai/provider-config", {
    method: "PUT",
    body: input,
  })
  if (!result) throw new Error("AI 模型配置保存响应为空。")
  return result
}

export async function testAIProviderConfig(): Promise<AIProviderConnectionResult> {
  const result = await apiRequest<AIProviderConnectionResult>("/api/v1/ai/provider-config/test", {
    method: "POST",
  })
  if (!result) throw new Error("AI 模型连接测试响应为空。")
  return result
}

export async function deleteAIProviderConfig(): Promise<void> {
  await apiRequest<void>("/api/v1/ai/provider-config", {
    method: "DELETE",
  })
}
