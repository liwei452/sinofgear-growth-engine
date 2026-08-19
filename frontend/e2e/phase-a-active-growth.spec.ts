import { expect, type Page, test } from "@playwright/test"

async function login(page: Page, username: string) {
  await page.goto("/login")
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function expectNoSeededDemo(page: Page) {
  await expect(page.getByText("PackTech GmbH")).toHaveCount(0)
  await expect(page.getByText("NordMotion AB")).toHaveCount(0)
}

test("operator workspace is role-correct across the consolidated pages", async ({ page }) => {
  await login(page, "phasea_e2e_operator")

  // Reference data pages load for operators without demo leakage.
  await page.goto("/knowledge")
  await expect(page.getByRole("heading", { name: "知识库" })).toBeVisible()
  await expectNoSeededDemo(page)

  await page.goto("/products")
  await expect(page.getByRole("heading", { name: "产品库" })).toBeVisible({ timeout: 15000 })
  await expectNoSeededDemo(page)

  await page.goto("/assets")
  await expect(page.getByRole("heading", { name: "素材库" })).toBeVisible()
  await expectNoSeededDemo(page)

  // Legacy workflow URLs now consolidate onto missions.
  for (const legacy of ["/promotion", "/opportunities", "/reviews", "/publishing-calendar"]) {
    await page.goto(legacy)
    await expect(page).toHaveURL(/\/missions$/)
  }

  // Administrator-only areas bounce operators back to the dashboard.
  await page.goto("/settings")
  await expect(page).toHaveURL(/\/\?blocked=administrator/)
  await page.goto("/company")
  await expect(page).toHaveURL(/\/\?blocked=administrator/)

  // Operators keep read access to missions and attribution.
  await page.goto("/missions")
  await expect(page.getByRole("heading", { name: "增长任务" })).toBeVisible()
  await expect(page.getByRole("button", { name: "创建增长任务" })).toHaveCount(0)
  await page.goto("/attribution")
  await expect(page.getByRole("heading", { name: "数据归因" })).toBeVisible()
})

test("administrator workspace reaches the governed configuration areas", async ({ page }) => {
  await login(page, "phasea_e2e_admin")

  await page.goto("/settings")
  await expect(page.getByRole("heading", { name: "设置中心" })).toBeVisible()
  await page.goto("/company")
  await expect(page.getByRole("heading", { name: "我的公司" })).toBeVisible()
  await page.goto("/missions")
  await expect(page.getByRole("heading", { name: "增长任务" })).toBeVisible()
  await expect(page.getByRole("button", { name: "创建增长任务" })).toBeVisible()
})
