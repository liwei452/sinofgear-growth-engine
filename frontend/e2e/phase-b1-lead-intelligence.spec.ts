import { expect, type APIResponse, type Page, test } from "@playwright/test"
import { readFile } from "node:fs/promises"

const password = "PhaseA-E2E-Only!"
const bridgeCompany = "Phase B1 Browser Packaging"
const bridgeUrl = "https://example.com/phase-b1/public-signal"
const bridgeText = "We need 200 replacement helical gears for a packaging machine, DIN 6 if possible."

type CandidateList = {
  results: Array<{ id: string; company_name: string; version: number }>
}

type CandidateDetail = {
  id: string
  version: number
  company: { name: string }
  evidence: Array<{ id: string; original_text: string }>
}

async function login(page: Page, username: string): Promise<void> {
  await page.goto("/login")
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill(password)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function logout(page: Page): Promise<void> {
  await page.getByRole("button", { name: "退出登录" }).click()
  await expect(page).toHaveURL(/\/login$/)
}

async function expectOk(response: APIResponse): Promise<APIResponse> {
  const body = await response.text()
  expect(response.status(), body).toBeGreaterThanOrEqual(200)
  expect(response.status(), body).toBeLessThan(300)
  return response
}

async function csrfToken(page: Page): Promise<string> {
  const cookie = (await page.context().cookies()).find((item) => item.name === "csrftoken")
  expect(cookie).toBeDefined()
  return cookie!.value
}

test("collects, analyzes, explains, and reviews a public lead through the real UI", async ({ page }) => {
  await login(page, "phasea_e2e_operator")
  await page.getByRole("link", { name: "客户机会", exact: true }).click()
  await page.getByRole("button", { name: "添加公开线索" }).first().click()
  await page.getByRole("tab", { name: "批量粘贴" }).click()
  await page.getByLabel("公开链接和原文").fill(`${bridgeUrl}\t${bridgeText}`)
  const importResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/v1/ingestion-batches"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "导入公开信号" }).click()
  expect((await importResponse).status()).toBe(202)
  await expect(page.getByText("已完成公开信息导入。", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "关闭" }).click()

  const opportunity = page.locator("article.opportunity-card").filter({ hasText: bridgeCompany })
  await expect(opportunity).toHaveCount(1)
  await opportunity.getByRole("button", { name: "查看依据" }).click()
  const detail = page.getByRole("dialog", { name: "机会依据" })
  await expect(detail.getByText(bridgeText, { exact: true })).toBeVisible()
  await expect(detail.getByRole("link", { name: "打开公开来源" })).toHaveAttribute("href", bridgeUrl)

  const analyzeResponse = page.waitForResponse((response) =>
    /\/api\/v1\/lead-candidates\/[0-9a-f-]+\/analyze$/.test(new URL(response.url()).pathname)
      && response.request().method() === "POST",
  )
  await detail.getByRole("button", { name: "重新分析" }).click()
  const acceptedAnalysis = await analyzeResponse
  expect(acceptedAnalysis.status()).toBe(202)
  const acceptedAnalysisBody = await acceptedAnalysis.json() as { job_id: string }
  await expect.poll(async () => {
    const job = await page.request.get(`/api/v1/jobs/${acceptedAnalysisBody.job_id}`)
    return await job.json() as { status: string; error?: unknown }
  }, { timeout: 20_000, message: "lead analysis must reach a terminal success" })
    .toMatchObject({ status: "SUCCEEDED", error: null })
  await expect(detail.getByText("分析已完成", { exact: true })).toBeVisible({ timeout: 20_000 })
  await expect(detail.getByText(bridgeText, { exact: true })).toBeVisible()
  await detail.getByRole("button", { name: "关闭机会依据" }).click()

  await logout(page)
  await login(page, "phasea_e2e_reviewer")
  await page.goto("/lead-radar")
  const reviewOpportunity = page.locator("article.opportunity-card").filter({ hasText: bridgeCompany })
  await expect(reviewOpportunity).toHaveCount(1)
  await reviewOpportunity.getByRole("button", { name: "查看依据" }).click()
  const reviewDetail = page.getByRole("dialog", { name: "机会依据" })
  await expect(reviewDetail.getByText(bridgeText, { exact: true })).toBeVisible()
  await reviewDetail.getByRole("button", { name: "确认值得跟进" }).click()
  const reason = "公开需求、数量、应用和精度要求均有原始证据。"
  await reviewDetail.getByLabel("处理原因").fill(reason)
  const reviewResponsePromise = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/v1/lead-reviews"
      && response.request().method() === "POST",
  )
  await reviewDetail.getByRole("button", { name: "确认值得跟进" }).click()
  const reviewResponse = await reviewResponsePromise
  expect(reviewResponse.status()).toBe(201)
  expect((await reviewResponse.json() as { candidate_status: string }).candidate_status).toBe("REVIEWED")
  await expect(reviewDetail.getByText("处理结果已保存", { exact: true })).toBeVisible()
  await reviewDetail.getByRole("button", { name: "关闭机会依据" }).click()

  await logout(page)
  await login(page, "phasea_e2e_admin")
  await page.goto("/lead-radar")
  const handoffOpportunity = page.locator("article.opportunity-card").filter({ hasText: bridgeCompany })
  await handoffOpportunity.getByRole("button", { name: "查看依据" }).click()
  const handoffDetail = page.getByRole("dialog", { name: "机会依据" })
  await handoffDetail.getByRole("button", { name: "交给 CRM" }).click()
  const handoff = handoffDetail.getByRole("region", { name: "CRM 与导出" })
  await expect(handoff.getByRole("status")).toHaveText("CRM 尚未配置，当前不会发送客户资料。")
  await handoff.getByRole("button", { name: "交给 CRM" }).click()
  await expect(handoff).not.toContainText(/交接成功|发送成功|已发送/)

  const downloadPromise = page.waitForEvent("download")
  await handoff.getByRole("button", { name: "下载 JSON" }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/^lead-[0-9a-f-]+\.json$/)
  const downloadPath = await download.path()
  expect(downloadPath).not.toBeNull()
  const exported = JSON.parse(await readFile(downloadPath!, "utf8")) as {
    candidate: { company_name: string }
    source_evidence: Array<{ content: string }>
  }
  expect(exported.candidate.company_name).toBe(bridgeCompany)
  expect(exported.source_evidence.map((item) => item.content)).toContain(bridgeText)
})

test("the primary organization cannot create or analyze with real foreign evidence", async ({ page }) => {
  await login(page, "phaseb1_e2e_foreign")
  const foreignListResponse = await expectOk(
    await page.request.get("/api/v1/lead-candidates?page_size=50"),
  )
  const foreignList = await foreignListResponse.json() as CandidateList
  const foreignCandidate = foreignList.results.find(
    (candidate) => candidate.company_name === bridgeCompany,
  )
  expect(foreignCandidate).toBeDefined()
  const foreignDetailResponse = await expectOk(
    await page.request.get(`/api/v1/lead-candidates/${foreignCandidate!.id}`),
  )
  const foreignDetail = await foreignDetailResponse.json() as CandidateDetail
  const foreignEvidence = foreignDetail.evidence[0]
  expect(foreignEvidence).toBeDefined()
  await logout(page)

  await login(page, "phasea_e2e_operator")
  const ownListResponse = await expectOk(
    await page.request.get("/api/v1/lead-candidates?page_size=50"),
  )
  const ownList = await ownListResponse.json() as CandidateList
  expect(ownList.results.map((candidate) => candidate.id)).not.toContain(foreignCandidate!.id)
  const ownCandidate = ownList.results.find(
    (candidate) => candidate.company_name === bridgeCompany,
  )
  expect(ownCandidate).toBeDefined()
  const ownDetailResponse = await expectOk(
    await page.request.get(`/api/v1/lead-candidates/${ownCandidate!.id}`),
  )
  const ownDetail = await ownDetailResponse.json() as CandidateDetail

  const forbiddenRead = await page.request.get(
    `/api/v1/lead-candidates/${foreignCandidate!.id}`,
  )
  expect(forbiddenRead.status()).toBe(404)
  expect(await forbiddenRead.text()).not.toContain(foreignEvidence!.original_text)

  const token = await csrfToken(page)
  const forbiddenCreate = await page.request.post(
    "/api/v1/lead-candidates",
    {
      data: {
        company_name: "Foreign evidence probe",
        evidence_ids: [foreignEvidence!.id],
      },
      headers: { "X-CSRFToken": token },
    },
  )
  expect(forbiddenCreate.status()).toBe(404)
  const forbiddenCreateBody = await forbiddenCreate.text()
  expect(forbiddenCreateBody).not.toContain(foreignDetail.company.name)
  expect(forbiddenCreateBody).not.toContain(foreignEvidence!.original_text)

  const forbiddenAnalyze = await page.request.post(
    `/api/v1/lead-candidates/${ownCandidate!.id}/analyze`,
    {
      data: {
        evidence_ids: [foreignEvidence!.id],
        expected_version: ownDetail.version,
        idempotency_key: "phase-b1-e2e-foreign-analysis-denied",
      },
      headers: { "X-CSRFToken": token },
    },
  )
  expect(forbiddenAnalyze.status()).toBe(404)
  const forbiddenBody = await forbiddenAnalyze.text()
  expect(forbiddenBody).not.toContain(foreignDetail.company.name)
  expect(forbiddenBody).not.toContain(foreignEvidence!.original_text)
})
