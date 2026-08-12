import { expect, type Page, test } from "@playwright/test"

const password = "PhaseA-E2E-Only!"
const runtimeKey = (kind: "valid" | "invalid" | "balance" | "retry") =>
  ["s", "k-", `${kind}-placeholder`].join("")

async function login(page: Page, username: string) {
  await page.context().clearCookies()
  await page.reload()
  await page.goto("/login")
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill(password)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "退出登录" }).click()
  await expect(page).toHaveURL(/\/login$/)
}

async function openSettings(page: Page, expectPage = true) {
  await page.evaluate(() => localStorage.setItem(
    "sinofgear-navigation-mode-v1", "advanced",
  ))
  await page.goto("/ai-settings")
  if (expectPage) await expect(page.getByTestId("deepseek-settings-page")).toBeVisible()
}

test.afterEach(async ({ page }) => {
  await page.evaluate(() => localStorage.removeItem("sinofgear-navigation-mode-v1"))
})

async function testKey(page: Page, key: string) {
  let input = page.getByLabel(/API Key/)
  if (await input.count() === 0) {
    await page.getByRole("button", { name: "更换 API Key" }).click()
    input = page.getByLabel(/API Key/)
  }
  await input.fill(key)
  await page.getByRole("button", { name: "先测试连接" }).click()
  return input
}

async function connect(page: Page) {
  const input = await testKey(page, runtimeKey("valid"))
  const modal = page.getByRole("dialog", { name: /修改 DeepSeek 设置/ })
  await expect(input).toHaveValue("")
  await input.fill(runtimeKey("valid"))
  if (await modal.isVisible()) {
    await expect(modal.getByRole("button", { name: "测试并保存设置" })).toBeEnabled()
  } else {
    await expect(page.getByRole("status")).toContainText("连接测试成功")
  }
  await page.getByRole("button", { name: /保存并启用|测试并保存设置/ }).click()
  await expect(page.getByText("DeepSeek 已安全连接")).toBeVisible()
  await expect(page.locator("body")).not.toContainText(runtimeKey("valid"))
}

test("DeepSeek setup is isolated by permission and organization and never reveals keys", async ({ page }) => {
  await login(page, "phasea_e2e_viewer")
  await openSettings(page, false)
  await expect(page).not.toHaveURL(/\/ai-settings$/)
  await logout(page)

  await login(page, "phasea_e2e_admin")
  await openSettings(page)
  await expect(page.getByTestId("deepseek-settings-page")).toBeVisible()

  for (const kind of ["invalid", "balance", "retry"] as const) {
    const input = await testKey(page, runtimeKey(kind))
    await expect(page.getByRole("alert")).toBeVisible()
    await expect(input).toHaveValue("")
    await expect(page.locator("body")).not.toContainText(runtimeKey(kind))
  }

  await connect(page)
  await logout(page)
  await login(page, "phaseb1_e2e_foreign")
  await openSettings(page)
  await page.getByRole("button", { name: "删除连接" }).click()
  await page.getByRole("dialog", { name: /确认删除/ })
    .getByRole("button", { name: "确认删除" }).click()
  await expect(page.getByText("DeepSeek 尚未连接")).toBeVisible()
  await logout(page)

  await login(page, "phasea_e2e_admin")
  await openSettings(page)
  await expect(page.getByText("DeepSeek 已安全连接")).toBeVisible()
  await page.getByRole("button", { name: "删除连接" }).click()
  await page.getByRole("dialog", { name: /确认删除/ })
    .getByRole("button", { name: "确认删除" }).click()
  await expect(page.getByText("DeepSeek 尚未连接")).toBeVisible()
  await connect(page)
})

test("ordinary content and lead decisions use guarded DeepSeek orchestration", async ({ page }) => {
  await login(page, "phasea_e2e_admin")
  await openSettings(page)
  await connect(page)

  await page.goto("/promotion")
  const contentResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/generate-master-content")
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "生成推广内容" }).click()
  expect((await contentResponse).status()).toBe(202)
  await expect(page.getByRole("link", { name: "查看并确认" })).toBeVisible({ timeout: 20_000 })

  await page.goto("/lead-radar")
  const opportunity = page.locator("article.opportunity-card")
    .filter({ hasText: "Phase B1 Browser Packaging" })
  await opportunity.getByRole("button", { name: "查看依据" }).click()
  const dialog = page.getByRole("dialog", { name: "机会依据" })
  const leadResponse = page.waitForResponse(response =>
    /\/api\/v1\/lead-candidates\/[0-9a-f-]+\/analyze$/.test(new URL(response.url()).pathname),
  )
  await dialog.getByRole("button", { name: "重新分析" }).click()
  expect((await leadResponse).status()).toBe(202)
  await expect(dialog.getByText("分析已完成", { exact: true })).toBeVisible({ timeout: 20_000 })

  const audit = await page.request.get("/api/v1/ai-runs?page_size=50")
  expect(audit.status()).toBe(200)
  const serialized = JSON.stringify(await audit.json())
  expect(serialized).toContain("deepseek-v4-flash")
  expect(serialized).not.toContain("reasoning_content")
  expect(serialized).not.toContain(runtimeKey("valid"))
})
