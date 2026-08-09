import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError, apiRequest } from "./client"

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

describe("apiRequest", () => {
  it("includes the session cookie and handles a 204 response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)

    await expect(apiRequest("/api/v1/auth/me")).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/me",
      expect.objectContaining({ credentials: "include", method: "GET" }),
    )
  })

  it("bootstraps CSRF and sends its cookie on unsafe requests", async () => {
    const fetchMock = vi.fn()
      .mockImplementationOnce(async () => {
        document.cookie = "csrftoken=csrf-value; path=/"
        return new Response(null, { status: 204 })
      })
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)

    await apiRequest("/api/v1/auth/logout", { method: "POST" })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/auth/csrf",
      expect.objectContaining({ credentials: "include", method: "GET" }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/auth/logout",
      expect.objectContaining({
        credentials: "include",
        method: "POST",
        headers: expect.objectContaining({ "X-CSRFToken": "csrf-value" }),
      }),
    )
  })

  it("maps detail, message, and recovery_action without exposing internals", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: "请求无法完成",
      message: "内部消息",
      recovery_action: "请刷新后重试",
      stack: "secret stack",
    }), { status: 500, headers: { "Content-Type": "application/json" } })))

    const error = await apiRequest("/api/v1/failure").catch((reason) => reason)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 500,
      userMessage: "请求无法完成",
      recoveryAction: "请刷新后重试",
    })
    expect(String(error)).not.toContain("secret stack")
  })

  it.each([
    [401, "登录状态已失效，请重新登录。"],
    [403, "你暂时没有权限执行此操作。"],
    [503, "服务暂时不可用，请稍后重试。"],
  ])("maps status %s to a recoverable Chinese message", async (status, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })))

    await expect(apiRequest("/api/v1/failure")).rejects.toMatchObject({
      status,
      userMessage: message,
    })
  })

  it("maps network failures to a recoverable Chinese message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")))

    await expect(apiRequest("/api/v1/failure")).rejects.toMatchObject({
      status: 0,
      userMessage: "网络连接失败，请检查网络后重试。",
    })
  })
})
