const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"])

type ErrorPayload = {
  detail?: unknown
  message?: unknown
  recovery_action?: unknown
  errors?: unknown
  code?: unknown
  recovery_code?: unknown
  current_version?: unknown
}

type ApiErrorMetadata = {
  fieldErrors?: Record<string, string[]>
  code?: string
  currentVersion?: number
}

export class ApiError extends Error {
  readonly status: number
  readonly userMessage: string
  readonly recoveryAction?: string
  readonly fieldErrors?: Record<string, string[]>
  readonly code?: string
  readonly currentVersion?: number

  constructor(
    status: number,
    userMessage: string,
    recoveryAction?: string,
    metadata: ApiErrorMetadata = {},
  ) {
    super(userMessage)
    this.name = "ApiError"
    this.status = status
    this.userMessage = userMessage
    this.recoveryAction = recoveryAction
    this.fieldErrors = metadata.fieldErrors
    this.code = metadata.code
    this.currentVersion = metadata.currentVersion
  }
}

export type ApiRequestOptions = Omit<RequestInit, "body" | "credentials"> & {
  body?: unknown
}

export type ApiResponse<T> = { data: T | undefined; response: Response }

function cookieValue(name: string): string | undefined {
  const prefix = `${encodeURIComponent(name)}=`
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length)
}

function statusMessage(status: number): string {
  if (status === 401) return "登录状态已失效，请重新登录。"
  if (status === 403) return "你暂时没有权限执行此操作。"
  if (status >= 500) return "服务暂时不可用，请稍后重试。"
  return "请求未能完成，请检查后重试。"
}

function fieldErrors(value: unknown): Record<string, string[]> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined
  const normalized: Record<string, string[]> = {}
  for (const [field, messages] of Object.entries(value)) {
    if (!Array.isArray(messages)) continue
    const safeMessages = messages.filter((message): message is string => typeof message === "string")
    if (safeMessages.length) normalized[field] = safeMessages
  }
  return Object.keys(normalized).length ? normalized : undefined
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  if (response.status >= 500) {
    return new ApiError(
      response.status,
      statusMessage(response.status),
      "请稍后重试；若问题持续，请联系管理员。",
    )
  }
  let payload: ErrorPayload = {}
  if (response.headers.get("Content-Type")?.includes("application/json")) {
    try {
      payload = await response.json() as ErrorPayload
    } catch {
      payload = {}
    }
  }
  const detail = typeof payload.detail === "string" ? payload.detail : undefined
  const message = typeof payload.message === "string" ? payload.message : undefined
  const recovery = typeof payload.recovery_action === "string"
    ? payload.recovery_action
    : undefined
  return new ApiError(
    response.status,
    detail ?? message ?? statusMessage(response.status),
    recovery,
    {
      fieldErrors: fieldErrors(payload.errors),
      code: typeof payload.code === "string"
        ? payload.code
        : typeof payload.recovery_code === "string"
          ? payload.recovery_code
          : undefined,
      currentVersion: typeof payload.current_version === "number"
        ? payload.current_version
        : undefined,
    },
  )
}

export async function ensureCsrfCookie(): Promise<void> {
  if (cookieValue("csrftoken")) return
  let response: Response
  try {
    response = await fetch("/api/v1/auth/csrf", {
      credentials: "include",
      method: "GET",
      headers: { Accept: "application/json" },
    })
  } catch {
    throw new ApiError(0, "网络连接失败，请检查网络后重试。")
  }
  if (!response.ok) throw await errorFromResponse(response)
}

async function request(
  path: string,
  options: ApiRequestOptions = {},
): Promise<Response> {
  const method = (options.method ?? "GET").toUpperCase()
  if (!SAFE_METHODS.has(method)) await ensureCsrfCookie()

  const headers: Record<string, string> = { Accept: "application/json" }
  new Headers(options.headers).forEach((value, key) => { headers[key] = value })
  if (!SAFE_METHODS.has(method)) {
    const csrfToken = cookieValue("csrftoken")
    if (!csrfToken) throw new ApiError(0, "安全验证失败，请刷新页面后重试。")
    headers["X-CSRFToken"] = decodeURIComponent(csrfToken)
  }
  let body: BodyInit | undefined
  if (options.body !== undefined) {
    if (options.body instanceof FormData) {
      body = options.body
    } else {
      headers["Content-Type"] = "application/json"
      body = JSON.stringify(options.body)
    }
  }

  let response: Response
  try {
    response = await fetch(path, {
      ...options,
      body,
      credentials: "include",
      headers,
      method,
    })
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(0, "网络连接失败，请检查网络后重试。")
  }
  if (!response.ok) throw await errorFromResponse(response)
  return response
}

export async function apiRequestWithMeta<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<ApiResponse<T>> {
  const response = await request(path, options)
  let data: T | undefined
  if (response.status === 204) return { data: undefined, response }
  if (response.headers.get("Content-Type")?.includes("application/json")) {
    data = await response.json() as T
  } else {
    data = await response.text() as T
  }
  return { data, response }
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T | undefined> {
  return (await apiRequestWithMeta<T>(path, options)).data
}
