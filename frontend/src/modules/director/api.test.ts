import { afterEach, describe, expect, it, vi } from "vitest"

import { decideProposal, directorKeys, getCockpit } from "./api"

const json = (data: unknown, status = 200): Response => new Response(JSON.stringify(data), {
  status,
  headers: { "Content-Type": "application/json" },
})

const cockpit = {
  decisions: [{
    id: "proposal-1", type: "CONTENT_APPROVAL", title: "5 条内容已经准备好",
    explanation: "内容来自已确认的产品资料", priority: 80, version: 3,
    actions: ["APPROVE", "REQUEST_ADJUSTMENT", "REJECT"],
  }],
  active_work: [{
    job_id: "job-1", label: "正在生成平台内容", status: "RUNNING", progress: 65,
    progress_is_determinate: true,
  }],
  recent_outcomes: [{ kind: "PUBLISHING", label: "内容发布", value: "4", detail: "最近 30 天真实完成记录" }],
  generated_at: "2026-08-12T12:00:00Z",
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "csrftoken=; Max-Age=0; path=/"
})

describe("Growth Director API", () => {
  it("uses an organization-scoped query key and forwards cancellation", async () => {
    const signal = new AbortController().signal
    const fetchMock = vi.fn().mockResolvedValue(json(cockpit))
    vi.stubGlobal("fetch", fetchMock)

    await expect(getCockpit({ signal })).resolves.toEqual(cockpit)
    expect(directorKeys.cockpit("org-1")).toEqual(["director", "org-1", "cockpit"])
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/director/cockpit",
      expect.objectContaining({ signal, credentials: "include", method: "GET" }),
    )
  })

  it("sends an optimistic version with a Director decision", async () => {
    document.cookie = "csrftoken=test-token; path=/"
    const fetchMock = vi.fn().mockResolvedValue(json({ id: "proposal-1", status: "APPROVED", version: 4 }))
    vi.stubGlobal("fetch", fetchMock)

    await decideProposal("proposal-1", { action: "APPROVE", expected_version: 3, comment: "" })

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/director/proposals/proposal-1/decisions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ action: "APPROVE", expected_version: 3, comment: "" }),
      }),
    )
  })

  it.each([
    [undefined, "服务响应不完整"],
    [{ ...cockpit, decisions: [{ ...cockpit.decisions[0], actions: ["DELETE"] }] }, "服务响应格式不正确"],
    [{ ...cockpit, active_work: [{ ...cockpit.active_work[0], progress: 101 }] }, "服务响应格式不正确"],
  ])("rejects missing or invalid cockpit responses", async (payload, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      payload === undefined ? new Response(null, { status: 204 }) : json(payload),
    ))
    await expect(getCockpit()).rejects.toThrow(message)
  })
})
