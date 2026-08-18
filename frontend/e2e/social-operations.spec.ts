import { expect, type Page, test } from "@playwright/test"

async function login(page: Page) {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_operator")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

test("operator sees five channels and uses a manual package without publishing", async ({ page }) => {
  let publishCalls = 0
  await login(page)
  await page.route("**/api/v1/growth/workspace", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      target_accounts: [], contacts: [], intent_signals: [], inbound_leads: [], follow_ups: [],
      outreach_drafts: [], opportunity_reviews: [], crm_handoffs: [], reactivations: [],
      publish_batches: [], metric_receipts: [], field_provenance: [], connectors: [],
      channel_packages: [{
        id: "fixture-youtube-package", account_id: null, channel: "YOUTUBE",
        payload: { title: "Fixture YouTube package" }, status: "APPROVED", is_demo: false,
        data_label: "Reviewed", delivery: "MANUAL_ONLY", created_at: "2026-08-18T08:00:00Z",
        updated_at: "2026-08-18T08:00:00Z",
      }],
    }),
  }))
  await page.route("**/api/v1/growth/channel-packages/fixture-youtube-package/manual-export", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ package_id: "fixture-youtube-package", channel: "YOUTUBE", mode: "MANUAL_PACKAGE", data_label: "Reviewed", delivery: "MANUAL_ONLY", filename: "youtube-manual-package.json", payload: { title: "Fixture YouTube package" } }),
  }))
  await page.route("**/api/v1/growth/publish-batches", route => {
    publishCalls += 1
    return route.abort()
  })

  await page.goto("/promotion")
  for (const channel of ["Facebook", "Instagram", "LinkedIn", "TikTok", "YouTube"]) {
    await expect(page.getByRole("article", { name: `${channel} 渠道` })).toBeVisible()
  }
  await expect(page.getByRole("article", { name: "Facebook 渠道" }).getByRole("link", { name: "查看配置指引" })).toHaveAttribute("href", "/settings")
  await page.getByRole("article", { name: "YouTube 渠道" }).getByRole("button", { name: "下载发布包" }).click()
  await expect(page.getByRole("status")).toContainText("未触发任何平台发布请求")
  expect(publishCalls).toBe(0)

  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByRole("heading", { name: "社媒运营" })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})
