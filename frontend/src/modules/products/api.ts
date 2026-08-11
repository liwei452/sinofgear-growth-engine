import { ApiError, apiRequest, apiRequestWithMeta, type ApiRequestOptions } from "../../api/client"

export type ProductStatus = "DRAFT" | "ACTIVE" | "ARCHIVED"
export type ProductConceptRole = "TYPE" | "MATERIAL" | "PROCESS" | "STANDARD" | "APPLICATION" | "PARAMETER" | "CAPABILITY"

export type ProductConceptSummary = {
  id: string
  code: string
  concept_type: string
  label_zh: string
  label_en: string
  version: number
}

export type ProductConceptLink = {
  id: string
  role: ProductConceptRole
  version: number
  concept: ProductConceptSummary
}

export type Product = {
  id: string
  organization: string
  name_zh: string
  name_en: string
  module_min: string
  module_max: string
  tooth_count_min: number
  tooth_count_max: number
  pressure_angle: string
  accuracy_grade: string
  heat_treatment: string
  surface_treatment: string
  manufacturing_capabilities: string[]
  inspection_capabilities: string[]
  moq: number
  lead_time: string
  landing_page_url: string
  status: ProductStatus
  version: number
  internal_notes: string
  concept_links: ProductConceptLink[]
  created_at: string
  updated_at: string
}

export type ProductInput = {
  name_zh: string
  name_en: string
  module_min: string
  module_max: string
  tooth_count_min: number
  tooth_count_max: number
  pressure_angle: string
  accuracy_grade: string
  heat_treatment: string
  surface_treatment: string
  manufacturing_capabilities: string[]
  inspection_capabilities: string[]
  moq: number
  lead_time: string
  landing_page_url: string
  status: ProductStatus
  internal_notes: string
  concept_links: Array<{ role: ProductConceptRole; concept_id: string }>
}

export type ProductFilters = {
  status?: ProductStatus
  type?: string
  material?: string
  application?: string
}

export type ProductPage = {
  next: string | null
  previous: string | null
  results: Product[]
}

export const productQueryKeys = {
  all: (organizationId: string) => ["products", organizationId] as const,
  lists: (organizationId: string) => ["products", organizationId, "list"] as const,
  list: (organizationId: string, filters: ProductFilters) =>
    ["products", organizationId, "list", filters] as const,
  detail: (organizationId: string, id: string) =>
    ["products", organizationId, "detail", id] as const,
}

function listUrl(filters: ProductFilters): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  const query = params.toString()
  return `/api/v1/products${query ? `?${query}` : ""}`
}

export function safeProductPageUrl(value: string | null): string | null {
  if (!value) return null
  let target: URL
  try {
    target = new URL(value, window.location.origin)
  } catch {
    return null
  }
  if (target.origin !== window.location.origin || target.pathname !== "/api/v1/products") {
    return null
  }
  return `${target.pathname}${target.search}`
}

export async function listProducts(
  filters: ProductFilters = {},
  options: Pick<ApiRequestOptions, "signal"> = {},
): Promise<ProductPage> {
  const page = await apiRequest<ProductPage>(listUrl(filters), options)
  if (!page) throw new ApiError(0, "产品列表响应为空，请重试。")
  return page
}

export async function getProductPage(
  url: string,
  options: Pick<ApiRequestOptions, "signal"> = {},
): Promise<ProductPage> {
  const safeUrl = safeProductPageUrl(url)
  if (!safeUrl) throw new ApiError(0, "分页地址无效，请从产品列表重新开始。")
  const page = await apiRequest<ProductPage>(safeUrl, { signal: options.signal })
  if (!page) throw new ApiError(0, "产品列表响应为空，请重试。")
  return page
}

export async function getProduct(id: string): Promise<{ product: Product; etag: string }> {
  const { data, response } = await apiRequestWithMeta<Product>(`/api/v1/products/${id}`)
  const etag = response.headers.get("ETag")
  if (!data || !etag) throw new ApiError(0, "产品详情缺少版本信息，请重新加载。")
  return { product: data, etag }
}

export async function createProduct(input: ProductInput): Promise<{ product: Product; etag: string }> {
  const { data, response } = await apiRequestWithMeta<Product>("/api/v1/products", {
    method: "POST",
    body: input,
  })
  const etag = response.headers.get("ETag")
  if (!data || !etag) throw new ApiError(0, "新建产品响应不完整，请刷新列表确认。")
  return { product: data, etag }
}

export async function patchProduct(
  id: string,
  input: Partial<ProductInput>,
  etag: string,
): Promise<{ product: Product; etag: string }> {
  const { data, response } = await apiRequestWithMeta<Product>(`/api/v1/products/${id}`, {
    method: "PATCH",
    headers: { "If-Match": etag },
    body: input,
  })
  const nextEtag = response.headers.get("ETag")
  if (!data || !nextEtag) throw new ApiError(0, "产品更新响应不完整，请重新加载。")
  return { product: data, etag: nextEtag }
}
