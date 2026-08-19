import { expect, type Page, test } from "@playwright/test"

async function login(page: Page, username = "phasea_e2e_admin") {
  await page.goto("/login")
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function expectNoSeededDemo(page: Page) {
  await expect(page.getByText("PackTech GmbH")).toHaveCount(0)
  await expect(page.getByText("NordMotion AB")).toHaveCount(0)
  await expect(page.getByText(/Demo \/ Fake|Demo\/Fake/)).toHaveCount(0)
}

test("formal workspace stays clean and persists only explicitly recorded data", async ({ page }) => {
  await login(page)

  // Settings stay reachable from the user menu and keep the truthful
  // offline-AI disclosure.
  await page.getByRole("button", { name: "打开用户菜单" }).click()
  await page.getByRole("menuitem", { name: "设置" }).click()
  await expect(page).toHaveURL(/\/settings\?from=/)
  await expect(page.getByRole("heading", { name: "设置中心" })).toBeVisible()
  await expect(page.getByText("Fake / 离线演示 · 未启用真实请求")).toBeVisible()
  await page.getByRole("link", { name: "返回工作台" }).click()
  await expect(page).toHaveURL(/\/$/)

  // The dashboard starts empty and shows no seeded demo data.
  await expect(page.getByRole("heading", { name: "今日待办", level: 1 })).toBeVisible()
  await expect(page.getByText("没有需要人工处理的事项")).toBeVisible()
  await expectNoSeededDemo(page)

  // Missions list starts empty; the administrator owns the single creation
  // entry point and no demo missions are seeded.
  await page.goto("/missions")
  await expect(page.getByRole("heading", { name: "增长任务" })).toBeVisible()
  await expect(page.getByText("还没有增长任务")).toBeVisible()
  await expect(page.getByRole("button", { name: "创建增长任务" })).toBeVisible()
  await expectNoSeededDemo(page)

  // Attribution stays empty without explicitly recorded results.
  await page.goto("/attribution")
  await expect(page.getByRole("heading", { name: "数据归因" })).toBeVisible()
  await expectNoSeededDemo(page)

  // Company facts stay empty until an owner uploads evidence.
  await page.goto("/company")
  await expect(page.getByRole("heading", { name: "我的公司" })).toBeVisible()
  await expect(page.getByText("还没有已保存的公司事实")).toBeVisible()
  await expect(page.getByText("ISO 9001")).toHaveCount(0)
  await expectNoSeededDemo(page)
})
