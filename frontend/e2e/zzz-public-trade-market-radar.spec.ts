import { expect, type Page, test } from "@playwright/test"


async function login(page: Page) {
  await page.goto("/login")
  await page.locator("input").nth(0).fill("phasea_e2e_operator")
  await page.locator("input").nth(1).fill("PhaseA-E2E-Only!")
  await page.locator('button[type="submit"]').click()
  await expect(page).toHaveURL(/\/$/)
}


test("public trade radar keeps aggregate evidence separate from candidate buyers", async ({ page }) => {
  await login(page)
  const before = await page.evaluate(async () => {
    const response = await fetch("/api/v1/growth/workspace")
    const payload = await response.json()
    return payload.discovery?.candidate_count ?? 0
  })

  await page.goto("/opportunities")
  const createForm = page.locator(".market-create-form")
  if (await createForm.isVisible()) {
    await createForm.locator("input").nth(0).fill("印度尼西亚")
    await createForm.locator("input").nth(1).fill("IDN")
    await createForm.locator("select").selectOption("CUSTOMS_STRONG")
    const marketResponse = page.waitForResponse(response => (
      new URL(response.url()).pathname === "/api/v1/growth/markets/watch"
      && response.request().method() === "POST"
    ))
    await createForm.locator('button[type="submit"]').click()
    expect((await marketResponse).status()).toBe(201)
    await expect(createForm).toBeHidden()
  }

  const panel = page.locator(".trade-evidence-panel")
  await expect(panel).toContainText("官方公开贸易证据")
  const indicatorResponse = page.waitForResponse(response => (
    new URL(response.url()).pathname === "/api/v1/growth/trade-indicators"
    && response.request().method() === "GET"
  ))
  await panel.getByRole("button", { name: "查看市场贸易证据" }).click()
  expect((await indicatorResponse).status()).toBe(200)
  await expect(panel).toContainText("当前没有官方贸易快照")
  await expect(panel).toContainText("宏观贸易仅用于市场判断，不是具体买家证据。")

  const syncResponse = page.waitForResponse(response => (
    new URL(response.url()).pathname === "/api/v1/growth/trade-syncs"
    && response.request().method() === "POST"
  ))
  await panel.getByRole("button", { name: "同步公开贸易数据" }).click()
  expect((await syncResponse).status()).toBe(201)
  await expect(panel).toContainText("Demo / Fake 数据")
  await expect(panel).toContainText("25.00%")
  await expect(panel).toContainText("(本期 - 上年同期) / 上年同期 × 100%")
  const source = panel.getByRole("link", { name: "查看 UN Comtrade 原始来源" }).first()
  await expect(source).toHaveAttribute("href", /^https:\/\/comtradeplus\.un\.org\//)

  await page.reload()
  const restored = page.locator(".trade-evidence-panel")
  await restored.getByRole("button", { name: "查看市场贸易证据" }).click()
  await expect(restored).toContainText("Demo / Fake 数据")
  await expect(restored.getByRole("link", { name: "查看 UN Comtrade 原始来源" }).first()).toBeVisible()

  const after = await page.evaluate(async () => {
    const response = await fetch("/api/v1/growth/workspace")
    const payload = await response.json()
    return payload.discovery?.candidate_count ?? 0
  })
  expect(after).toBe(before)
})
