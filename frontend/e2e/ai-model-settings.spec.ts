import { expect, type Page, test } from "@playwright/test"

async function login(page: Page) {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_admin")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

test("administrator configures and tests DeepSeek without exposing the key", async ({ page }) => {
  const secret = "fixture-e2e-key-never-persist"
  let configured = false
  let savedRequest: Record<string, unknown> = {}
  await login(page)
  await page.route("**/api/v1/ai/provider-config/test", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ ok: true, latency_ms: 12 }),
  }))
  await page.route("**/api/v1/ai/provider-config", async route => {
    const method = route.request().method()
    if (method === "PUT") {
      savedRequest = route.request().postDataJSON() as Record<string, unknown>
      configured = true
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        provider: "deepseek", model: "deepseek-chat", configured, enabled: configured,
        daily_budget_micros: 500_000, daily_spent_micros: 0, daily_reserved_micros: 0,
        price_table_version: "deepseek-usd-2026-08-18", last_tested_at: null,
        last_success_at: null, last_error_code: "",
      }),
    })
  })

  await page.goto("/settings/ai-model")
  await page.getByLabel("API Key").fill(secret)
  await page.getByRole("button", { name: "保存配置" }).click()
  await expect(page.getByRole("status")).toContainText("配置已安全保存")
  expect(savedRequest.api_key).toBe(secret)
  await expect(page.getByLabel("API Key")).toHaveValue("")
  await page.getByRole("button", { name: "测试连接" }).click()
  await expect(page.getByRole("status")).toContainText("连接成功")
  await expect(page.getByText("已启用真实模型")).toBeVisible()
  expect(await page.locator("body").innerText()).not.toContain(secret)
  expect(await page.evaluate(key => ({ local: localStorage.getItem(key), session: sessionStorage.getItem(key) }), secret)).toEqual({ local: null, session: null })

  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByRole("heading", { name: "AI 模型" })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})
