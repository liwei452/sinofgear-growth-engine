import { ApiError, apiRequest } from "../../api/client"
import { getCursorPage, type CursorPage } from "../content/api"

const required=<T>(value:T|undefined):T=>{if(value===undefined)throw new ApiError(0,"服务响应不完整，请重试。");return value}
export type SummaryRow={date:string;campaign_id:string;platform_id:string;country:string;product_id:string;clicks:number}
export type Summary={count:number;total_clicks:number;next:string|null;previous:string|null;results:SummaryRow[]}
export type TrackingLink={id:string;destination:string;full_url:string;utm_source:string;utm_medium:string;utm_campaign:string;utm_content?:string;campaign_id:string;platform_id:string;product_id:string;published_post_id:string;created_at:string}
export type ShortLink={id:string;tracking_link_id:string;code:string;status:string;redirect_path:string;created_at:string}
export const analyticsKeys={all:(org:string)=>["analytics",org] as const,summary:(org:string,filters:Record<string,string>)=>[...analyticsKeys.all(org),"summary",filters] as const,tracking:(org:string)=>[...analyticsKeys.all(org),"tracking"] as const,short:(org:string)=>[...analyticsKeys.all(org),"short"] as const}
const query=(path:string,input:Record<string,string|undefined>)=>{const p=new URLSearchParams();Object.entries(input).forEach(([k,v])=>{if(v)p.set(k,v)});return `${path}?${p}`}
export const getChannelSummary=async(filters:Record<string,string|undefined>):Promise<Summary>=>required(await apiRequest(query("/api/v1/analytics/channel-summary",filters)))
export const listTrackingLinks=async():Promise<CursorPage<TrackingLink>>=>required(await apiRequest("/api/v1/tracking-links"))
export const getTrackingPage=(url:string)=>getCursorPage<TrackingLink>(url,"/api/v1/tracking-links")
export const createTrackingLink=async(input:Record<string,string>,key:string):Promise<TrackingLink>=>required(await apiRequest("/api/v1/tracking-links",{method:"POST",headers:{"Idempotency-Key":key},body:input}))
export const listShortLinks=async():Promise<CursorPage<ShortLink>>=>required(await apiRequest("/api/v1/short-links"))
export const getShortPage=(url:string)=>getCursorPage<ShortLink>(url,"/api/v1/short-links")
export const createShortLink=async(tracking_link_id:string,key:string):Promise<ShortLink>=>required(await apiRequest("/api/v1/short-links",{method:"POST",headers:{"Idempotency-Key":key},body:{tracking_link_id}}))
