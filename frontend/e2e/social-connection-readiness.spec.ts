import { expect, type Page, test } from "@playwright/test"


async function login(page: Page) {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_admin")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}


test("five-channel fixture authorization returns to account picker without publishing", async ({ page }) => {
  let connected = false
  let publishCalls = 0
  const sessionId = "30000000-0000-4000-8000-000000000099"
  const candidateId = "40000000-0000-4000-8000-000000000099"

  await login(page)
  await page.route("**/api/v1/growth/workspace", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [],
      follow_ups: [], outreach_drafts: [], field_provenance: [], metric_receipts: [],
      publish_batches: [], channel_packages: [], market_pilots: { markets: [] },
      connectors: [
        { channel: "FACEBOOK", status: connected ? "CONNECTED" : "NOT_CONNECTED", connection_label: connected ? "已连接" : "未连接", recovery_action: connected ? "" : "连接账号", mode: connected ? "OFFICIAL" : "", account_id: connected ? "50000000-0000-4000-8000-000000000099" : "", publication_mode: "PUBLIC" },
        { channel: "INSTAGRAM", status: "CONFIGURATION_REQUIRED", connection_label: "未配置", recovery_action: "连接账号", mode: "", publication_mode: "UNAVAILABLE" },
        { channel: "LINKEDIN", status: "WAITING_PLATFORM_REVIEW", connection_label: "等待平台审核", recovery_action: "", mode: "", publication_mode: "UNAVAILABLE" },
        { channel: "TIKTOK", status: "PRIVATE_ONLY", connection_label: "仅私密发布", recovery_action: "", mode: "OFFICIAL", publication_mode: "PRIVATE_ONLY" },
        { channel: "YOUTUBE", status: "WAITING_PLATFORM_REVIEW", connection_label: "等待平台审核", recovery_action: "", mode: "OFFICIAL", publication_mode: "UPLOAD" },
      ],
    }),
  }))
  await page.route("**/api/v1/platform-connections/FACEBOOK/authorize", route => route.fulfill({
    status: 201,
    contentType: "application/json",
    body: JSON.stringify({
      status: "AUTHORIZATION_REQUIRED",
      authorization_url: "https://fixture.invalid/oauth",
      expires_at: "2026-08-15T16:00:00Z",
    }),
  }))
  await page.route("https://fixture.invalid/oauth", route => route.fulfill({
    status: 200,
    contentType: "text/html",
    body: `<a href="${new URL(page.url()).origin}/promotion?connection_session=${sessionId}&connection_status=ready">Fixture authorization complete</a>`,
  }))
  await page.route(`**/api/v1/platform-connection-sessions/${sessionId}`, route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      id: sessionId, platform: "FACEBOOK", platform_name: "Facebook",
      expires_at: "2026-08-15T16:00:00Z",
      candidates: [{
        candidate_id: candidateId, display_name: "Fixture Company Page",
        channel: "FACEBOOK", capability_label: "可发布", publication_mode: "PUBLIC",
      }],
    }),
  }))
  await page.route(`**/api/v1/platform-connection-sessions/${sessionId}/confirm`, async route => {
    connected = true
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ platform: "FACEBOOK", status: "CONNECTED", connection_label: "已连接", recovery_action: "", mode: "OFFICIAL" }),
    })
  })
  await page.route("**/api/v1/growth/publish-batches", route => {
    publishCalls += 1
    return route.abort()
  })

  await page.goto("/promotion")
  const readiness = page.getByRole("region", { name: "社媒账号连接状态" })
  for (const label of ["Facebook Page", "Instagram Business", "LinkedIn Company Page", "TikTok", "YouTube"]) {
    await expect(readiness.getByText(label, { exact: true })).toBeVisible()
  }
  await readiness.getByRole("button", { name: "连接 Facebook 账号" }).click()
  await page.getByRole("link", { name: "Fixture authorization complete" }).click()
  await expect(page.getByRole("heading", { name: "选择要用于发布的账号" })).toBeVisible()
  await page.getByRole("button", { name: "使用此账号" }).click()
  await expect(page.getByRole("status")).toContainText("Fixture Company Page 已连接")
  await page.reload()
  await expect(page.getByRole("region", { name: "社媒账号连接状态" })).toContainText("已连接")
  expect(publishCalls).toBe(0)
})
