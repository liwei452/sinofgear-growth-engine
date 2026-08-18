import { test, expect } from "@playwright/test"

test("growth mission operating flow", async ({ page }) => {
  await page.goto("/login")

  // Seeded local records are assumed by the launcher; this spec documents the
  // role-based path without calling external email or social services.
  await expect(page.getByRole("heading", { name: "今日待办" })).toBeVisible()
  await page.getByRole("link", { name: "增长任务" }).click()
  await expect(page.getByRole("heading", { name: "增长任务" })).toBeVisible()
  await page.getByText("E2E mission").click()
  await expect(page.getByRole("heading", { name: "客户开发" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "社媒增长" })).toBeVisible()
  await page.getByRole("link", { name: "数据归因" }).click()
  await expect(page.getByRole("heading", { name: "数据归因" })).toBeVisible()
  await expect(page.getByRole("button", { name: "录入指标" })).toHaveCount(0)
})
