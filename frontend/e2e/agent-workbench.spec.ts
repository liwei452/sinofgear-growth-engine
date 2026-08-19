import { expect, type Page, test } from "@playwright/test"

async function login(page: Page) {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_admin")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function createRunningMission(page: Page, title: string) {
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

  await page.getByRole("link", { name: title }).click()
  await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible()

  // Generate the execution plan, then approve it to put the mission into RUNNING.
  const generateResponse = page.waitForResponse(response => (
    new URL(response.url()).pathname.endsWith("/generate-plan")
      && response.request().method() === "POST"
  ))
  await page.getByRole("button", { name: "生成执行计划" }).click()
  expect([200, 201]).toContain((await generateResponse).status())

  await expect(page.getByRole("button", { name: "批准并启动" })).toBeVisible()
  const approveResponse = page.waitForResponse(response => (
    new URL(response.url()).pathname.endsWith("/approve-plan")
      && response.request().method() === "POST"
  ))
  await page.getByRole("button", { name: "批准并启动" }).click()
  expect([200, 201]).toContain((await approveResponse).status())
  await expect(page.getByRole("button", { name: "暂停" })).toBeVisible()
}

test("operator starts the content-strategy agent from the mission lane", async ({ page }) => {
  await login(page)
  await createRunningMission(page, "E2E 策略任务")

  const lane = page.locator('section[aria-label="执行线"]')
  await expect(lane.getByRole("heading", { name: "社媒增长" })).toBeVisible()

  const strategyResponse = page.waitForResponse(response => (
    new URL(response.url()).pathname.endsWith("/start-content-strategy")
      && response.request().method() === "POST"
  ))
  await lane.getByRole("button", { name: "开始内容策略" }).click()
  expect([200, 201]).toContain((await strategyResponse).status())

  // The mission page must stay truthful: no error surface, lane stages visible.
  await expect(page.locator('[role="alert"]')).toHaveCount(0)
  await expect(lane.getByText("内容计划")).toBeVisible()
  await expect(lane.getByText("人工审核")).toBeVisible()

  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByRole("heading", { name: "客户开发" })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})
