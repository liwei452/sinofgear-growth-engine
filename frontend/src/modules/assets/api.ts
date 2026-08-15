import { ApiError, apiRequest } from "../../api/client"
import { getCursorPage, type CursorPage } from "../content/api"

export type Asset = { id:string; asset_type:string; original_filename:string; mime_type:string; size_bytes:number; checksum:string; language:string; status:string; tags:string[]; metadata_json:Record<string,unknown>; created_at:string; products:Array<{id:string;name_en:string;status:string}> }
export type AssetFilters = { type?:string; status?:string; product?:string; tag?:string }
export type AssetFact = { id:string; product:string; asset:string; category:string; field_name:string; value:string; confidence:string; source_page:number|null; source_region:number[]|null; source_excerpt:string; risk_level:"STANDARD"|"HIGH"; review_status:"SUGGESTED"|"VERIFIED"|"REJECTED"; provider_label:string; is_demo:boolean; reviewed_by:string|null; reviewed_at:string|null; review_note:string; created_at:string; updated_at:string }
export type AssetUnderstanding = { job:{id:string;status:string;progress:number;attempt:number;max_attempts:number;error:unknown}; facts:AssetFact[]; warnings:string[]; is_partial:boolean; provider_label:string }
const path = "/api/v1/assets"
const required = <T>(value:T|undefined):T => { if(value===undefined) throw new ApiError(0,"服务响应不完整，请重试。"); return value }
const query = (filters:AssetFilters) => { const params=new URLSearchParams(); Object.entries(filters).forEach(([key,value])=>{if(value)params.set(key,value)}); return `${path}${params.size?`?${params}`:""}` }
export const assetKeys={all:(organizationId:string)=>["assets",organizationId] as const,list:(organizationId:string,filters:AssetFilters)=>[...assetKeys.all(organizationId),"list",filters] as const}
export const listAssets=async(filters:AssetFilters={}):Promise<CursorPage<Asset>>=>required(await apiRequest<CursorPage<Asset>>(query(filters)))
export const getAssetPage=(url:string)=>getCursorPage<Asset>(url,path)
const casefold = (value:string) => value.normalize("NFKC").trim().toLocaleLowerCase().replaceAll("ß","ss").replaceAll("ς","σ")
export const normalizeAssetTags = (tags:string[]) => [...new Set(tags.map(casefold).filter(Boolean))]
export const uploadAsset=async(input:{file:File;asset_type:string;language:string;tags:string[]}):Promise<Asset>=>{const body=new FormData();body.append("file",input.file);body.append("asset_type",input.asset_type);body.append("language",input.language);body.append("tags",JSON.stringify(normalizeAssetTags(input.tags)));body.append("metadata_json","{}");return required(await apiRequest<Asset>(path,{method:"POST",body}))}
export const linkAssetProduct=async(assetId:string,productId:string):Promise<Asset>=>required(await apiRequest<Asset>(`${path}/${assetId}/link-product`,{method:"POST",body:{product_id:productId}}))
export const archiveAsset=async(assetId:string):Promise<Asset>=>required(await apiRequest<Asset>(`${path}/${assetId}/archive`,{method:"POST",body:{}}))
export const restoreAsset=async(assetId:string):Promise<Asset>=>required(await apiRequest<Asset>(`${path}/${assetId}/restore`,{method:"POST",body:{}}))
export const getAssetDownload=async(assetId:string):Promise<{url:string;expires_in:number}>=>required(await apiRequest(`${path}/${assetId}/download-url`,{method:"POST",body:{}}))
export const startAssetUnderstanding=async(assetId:string,productId:string,externalTextConsent=false):Promise<AssetUnderstanding>=>required(await apiRequest<AssetUnderstanding>(`${path}/${assetId}/understanding`,{method:"POST",body:{product_id:productId,external_text_consent:externalTextConsent}}))
export const getAssetUnderstanding=async(assetId:string):Promise<AssetUnderstanding>=>required(await apiRequest<AssetUnderstanding>(`${path}/${assetId}/understanding`))
export const retryAssetUnderstanding=async(assetId:string,externalTextConsent=false):Promise<AssetUnderstanding>=>required(await apiRequest<AssetUnderstanding>(`${path}/${assetId}/understanding/retry`,{method:"POST",body:{external_text_consent:externalTextConsent}}))
export const reviewAssetFact=async(factId:string,decision:"APPROVE"|"REJECT",note=""):Promise<AssetFact>=>required(await apiRequest<AssetFact>(`${path}/facts/${factId}/review`,{method:"POST",body:{decision,note}}))

export function resolveAssetDownloadUrl(
  result:{url:string;expires_in:number},
  allowedOrigins:string[],
):URL {
  if (!Number.isFinite(result.expires_in) || result.expires_in <= 0 || result.url.startsWith("//")) {
    throw new ApiError(0,"下载地址已失效。")
  }
  let target:URL
  try { target=new URL(result.url) } catch { throw new ApiError(0,"下载地址无效。") }
  const allowed=new Set(allowedOrigins.map(origin=>new URL(origin).origin))
  if (!["http:","https:"].includes(target.protocol)
    || target.username || target.password || !allowed.has(target.origin)) {
    throw new ApiError(0,"下载地址不在允许的来源中。")
  }
  return target
}
