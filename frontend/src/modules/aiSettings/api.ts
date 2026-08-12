import { queryOptions } from "@tanstack/vue-query"

import { ApiError, apiRequest } from "../../api/client"
import type { components } from "../../api/generated/schema"

export type AIProviderConfiguration = components["schemas"]["AIProviderConfiguration"]
export type AIProviderConfigurationWrite = components["schemas"]["AIProviderConfigurationWrite"]
export type AIProviderConfigurationTestResult = components["schemas"]["AIProviderConfigurationTestResult"]

const required = <T>(value: T | undefined): T => {
  if (value === undefined) throw new ApiError(0, "服务响应不完整，请重试。")
  return value
}

export const aiSettingsKeys = {
  all: ["ai-provider-configuration"] as const,
  configuration: (organizationId: string) => ["ai-provider-configuration", organizationId] as const,
}

export function aiProviderConfigurationQueryOptions(organizationId: string, allowed = true) {
  return queryOptions({
    queryKey: aiSettingsKeys.configuration(organizationId),
    queryFn: async () => required(await apiRequest<AIProviderConfiguration>("/api/v1/ai-provider-configuration")),
    enabled: Boolean(organizationId) && allowed,
    staleTime: 30_000,
  })
}

export async function testAIProviderConfiguration(apiKey?: string): Promise<AIProviderConfigurationTestResult> {
  return required(await apiRequest<AIProviderConfigurationTestResult>(
    "/api/v1/ai-provider-configuration/test",
    { method: "POST", body: apiKey ? { api_key: apiKey } : {} },
  ))
}

export async function saveAIProviderConfiguration(input: AIProviderConfigurationWrite): Promise<AIProviderConfiguration> {
  return required(await apiRequest<AIProviderConfiguration>(
    "/api/v1/ai-provider-configuration", { method: "PUT", body: input },
  ))
}

export async function deleteAIProviderConfiguration(): Promise<AIProviderConfiguration> {
  return required(await apiRequest<AIProviderConfiguration>(
    "/api/v1/ai-provider-configuration", { method: "DELETE" },
  ))
}
