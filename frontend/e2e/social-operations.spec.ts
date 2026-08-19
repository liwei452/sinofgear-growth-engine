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
  await page.getByRole("link", { name: title }).click()
  await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible()
}

test("mission social lane keeps publishing gated without approved packages", async ({ page }) => {
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

  await createMission(page, "E2E 社媒任务")

  await page.locator('nav[aria-label="任务分区"]').getByRole("link", { name: "社媒增长" }).click()
  await expect(page.getByRole("heading", { name: "发布准备" })).toBeVisible()

  // No approved channel packages yet: the lane explains the prerequisite and
  // offers no publish action.
  await expect(page.getByText("还没有渠道内容包。先在“总览”里审核平台内容。")).toBeVisible()
  await expect(page.getByRole("button", { name: "批准并发布" })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "下载发布包" })).toHaveCount(0)
  expect(publishCalls).toBe(0)

  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByRole("heading", { name: "发布准备" })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})
