import { expect, type Page, test } from "@playwright/test"

async function login(page: Page) {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_admin")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function createMission(page: Page, title: string) {
  await page.goto("/missions")
  await page.getByRole("button", { name: "创建增长任务" }).click()
  const dialog = page.getByRole("dialog", { name: "创建增长任务" })
  await dialog.getByLabel("任务名称").fill(title)
  await dialog.getByLabel("任务目标").fill("Expand verified industrial gear opportunities")
  await dialog.getByLabel("目标国家（逗号分隔）").fill("DE")
  await dialog.getByLabel("目标行业（逗号分隔）").fill("mining equipment")
  await dialog.getByLabel("主推产品").selectOption({ index: 1 })
  await dialog.getByLabel("开始日期").fill("2026-08-01")
  await dialog.getByLabel("结束日期").fill("2026-09-30")
  await dialog.getByRole("button", { name: "创建任务" }).click()
  await expect(page.getByRole("heading", { name: title })).toBeVisible()
}

test("growth mission operating flow", async ({ page }) => {
  await login(page)

  await expect(page.getByRole("heading", { name: "今日", level: 1 })).toBeVisible()
  await page.getByRole("link", { name: "增长任务" }).click()
  await expect(page.getByRole("heading", { name: "增长任务" })).toBeVisible()

  await createMission(page, "E2E mission")

  await page.getByRole("link", { name: "E2E mission" }).click()
  await expect(page.getByRole("heading", { name: "E2E mission", level: 1 })).toBeVisible()
  await expect(page.getByRole("heading", { name: "客户开发" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "社媒增长" })).toBeVisible()
  await expect(page.locator('nav[aria-label="任务分区"]')).toBeVisible()

  await page.goto("/attribution")
  await expect(page.getByRole("heading", { name: "数据归因" })).toBeVisible()
})
