import { ApiError, apiRequest } from "../../api/client"
import { getCursorPage, type CursorPage } from "../content/api"

export type Asset = { id:string; asset_type:string; original_filename:string; mime_type:string; size_bytes:number; checksum:string; language:string; status:string; tags:string[]; metadata_json:Record<string,unknown>; created_at:string; products:Array<{id:string;name_en:string;status:string}> }
export type AssetFilters = { type?:string; status?:string; product?:string; tag?:string }
const path = "/api/v1/assets"
const required = <T>(value:T|undefined):T => { if(value===undefined) throw new ApiError(0,"服务响应不完整，请重试。"); return value }
const query = (filters:AssetFilters) => { const params=new URLSearchParams(); Object.entries(filters).forEach(([key,value])=>{if(value)params.set(key,value)}); return `${path}${params.size?`?${params}`:""}` }
export const assetKeys={all:(organizationId:string)=>["assets",organizationId] as const,list:(organizationId:string,filters:AssetFilters)=>[...assetKeys.all(organizationId),"list",filters] as const}
export const listAssets=async(filters:AssetFilters={}):Promise<CursorPage<Asset>>=>required(await apiRequest<CursorPage<Asset>>(query(filters)))
export const getAssetPage=(url:string)=>getCursorPage<Asset>(url,path)
export const uploadAsset=async(input:{file:File;asset_type:string;language:string;tags:string[]}):Promise<Asset>=>{const body=new FormData();body.append("file",input.file);body.append("asset_type",input.asset_type);body.append("language",input.language);body.append("tags",JSON.stringify([...new Set(input.tags.map(tag=>tag.trim()).filter(Boolean))]));body.append("metadata_json","{}");return required(await apiRequest<Asset>(path,{method:"POST",body}))}
export const linkAssetProduct=async(assetId:string,productId:string):Promise<Asset>=>required(await apiRequest<Asset>(`${path}/${assetId}/link-product`,{method:"POST",body:{product_id:productId}}))
export const getAssetDownload=async(assetId:string):Promise<{url:string;expires_in:number}>=>required(await apiRequest(`${path}/${assetId}/download-url`,{method:"POST",body:{}}))
