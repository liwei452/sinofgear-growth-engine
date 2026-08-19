import { expect, type Page, test } from "@playwright/test"

async function login(page: Page) {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_admin")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

test("administrator connects a manual platform account without exposing secrets", async ({ page }) => {
  let publishCalls = 0
  await login(page)
  await page.route("**/api/v1/growth/publish-batches", route => {
    publishCalls += 1
    return route.abort()
  })
  await page.route("**/api/v1/growth/missions/*/publish", route => {
    publishCalls += 1
    return route.abort()
  })

  await page.goto("/platform-accounts")
  await expect(page.getByRole("heading", { name: "平台账户" })).toBeVisible()
  await expect(page.getByText("这里只展示安全的连接摘要，不会显示或回填密钥。")).toBeVisible()

  await page.getByRole("button", { name: "连接平台账户" }).click()
  const dialog = page.getByRole("dialog", { name: "连接平台账户" })
  await dialog.getByLabel("平台", { exact: true }).selectOption({ index: 1 })
  await dialog.getByLabel("显示名称").fill("E2E 手动渠道")
  await dialog.getByLabel("平台账户标识").fill("e2e-manual-account-001")
  await dialog.getByLabel("发布方式").selectOption("MANUAL")

  // Manual publishing never asks for a credential reference.
  await expect(dialog.getByLabel("凭据引用")).toHaveCount(0)

  const connectResponse = page.waitForResponse(response => (
    new URL(response.url()).pathname === "/api/v1/social-accounts/connect"
      && response.request().method() === "POST"
  ))
  await dialog.getByRole("button", { name: "保存连接" }).click()
  expect([200, 201]).toContain((await connectResponse).status())

  await expect(page.getByRole("status")).toContainText("平台账户已连接")
  const card = page.getByRole("article").filter({ hasText: "E2E 手动渠道" })
  await expect(card).toBeVisible()
  await expect(card).toContainText("手动发布")
  await expect(card).toContainText("未配置凭据")

  // Connecting an account must never trigger a publish request.
  expect(publishCalls).toBe(0)
})
