import { ApiError, apiRequest } from "../../api/client"
import type { components } from "../../api/generated/schema"

const required=<T>(value:T|undefined):T=>{if(value===undefined)throw new ApiError(0,"服务响应不完整，请重试。");return value}
export type Platform = components["schemas"]["Platform"]
export type SocialAccount = components["schemas"]["SocialAccountRead"]
export type BufferConnection = components["schemas"]["BufferProviderConnectionRead"]
export type BufferSyncResult = components["schemas"]["BufferProviderConnectionSync"]
export type Credential={id:string;platform_id:string;granted_scopes:string[];expires_at:string|null;configured:boolean}
export const platformAccountKeys={all:(org:string)=>["platform-accounts",org] as const,accounts:(org:string)=>[...platformAccountKeys.all(org),"accounts"] as const,credentials:(org:string)=>[...platformAccountKeys.all(org),"credentials"] as const,buffer:(org:string)=>[...platformAccountKeys.all(org),"buffer"] as const}
export const listPlatforms=async():Promise<Platform[]>=>required(await apiRequest<{results:Platform[]}>("/api/v1/platforms")).results
export const listSocialAccounts=async():Promise<SocialAccount[]>=>required(await apiRequest<{results:SocialAccount[]}>("/api/v1/social-accounts")).results
export const listCredentials=async():Promise<Credential[]>=>required(await apiRequest<{results:Credential[]}>("/api/v1/connector-credentials")).results
export const createCredential=async(input:{platform:string;secret_reference:string;granted_scopes:string[]}):Promise<Credential>=>required(await apiRequest("/api/v1/connector-credentials",{method:"POST",body:{...input,expires_at:null}}))
export const createSocialAccount=async(input:{platform:string;credential?:string|null;external_id:string;display_name:string;publish_mode:string;status:string}):Promise<SocialAccount>=>required(await apiRequest("/api/v1/social-accounts",{method:"POST",body:input}))
export const connectSocialAccount=async(input:{platform:string;external_id:string;display_name:string;publish_mode:string;status:string;secret_reference?:string}):Promise<SocialAccount>=>required(await apiRequest("/api/v1/social-accounts/connect",{method:"POST",body:input}))
export const updateSocialAccount=async(id:string,input:{credential?:string|null;display_name?:string;publish_mode?:string;status?:string}):Promise<SocialAccount>=>required(await apiRequest(`/api/v1/social-accounts/${id}`,{method:"PATCH",body:input}))

export async function getBufferConnection(): Promise<BufferConnection | null> {
  try {
    return required(await apiRequest<BufferConnection>("/api/v1/provider-connections/buffer"))
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export const connectBuffer = async (input: components["schemas"]["BufferProviderConnectionCreate"]): Promise<BufferConnection> =>
  required(await apiRequest<BufferConnection>("/api/v1/provider-connections/buffer", { method: "POST", body: input }))

export const rotateBufferKey = async (apiKey: string): Promise<BufferConnection> =>
  required(await apiRequest<BufferConnection>("/api/v1/provider-connections/buffer", { method: "PATCH", body: { api_key: apiKey } }))

export const probeBufferConnection = async (): Promise<BufferConnection> =>
  required(await apiRequest<BufferConnection>("/api/v1/provider-connections/buffer/probe", { method: "POST" }))

export const syncBufferChannels = async (): Promise<BufferSyncResult> =>
  required(await apiRequest<BufferSyncResult>("/api/v1/provider-connections/buffer/sync", { method: "POST" }))

export const disconnectBuffer = async (): Promise<BufferConnection> =>
  required(await apiRequest<BufferConnection>("/api/v1/provider-connections/buffer/disconnect", { method: "POST", body: { confirm: true } }))
