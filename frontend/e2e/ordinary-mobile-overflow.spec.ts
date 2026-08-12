import { expect, type Page, test } from "@playwright/test"

const password = "PhaseA-E2E-Only!"
const longProductName = `Campaign-HIGH-ACTIVE-${"X".repeat(240)}`

async function login(page: Page): Promise<void> {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_reviewer")
  await page.getByLabel("密码").fill(password)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

test("ordinary routes stay within a real 390px viewport with representative long content", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page)

  await expect(page.getByRole("button", { name: "打开导航" })).toBeVisible()
  const sidebar = page.getByTestId("app-sidebar")
  await expect(sidebar).toHaveAttribute("aria-hidden", "true")
  await page.getByRole("button", { name: "打开导航" }).click()
  await expect(sidebar).not.toHaveAttribute("aria-hidden", "true")
  await page.keyboard.press("Escape")
  await expect(sidebar).toHaveAttribute("aria-hidden", "true")

  await page.route("**/api/v1/products**", async (route) => {
    const response = await route.fetch()
    const body = await response.json() as { results?: Array<Record<string, unknown>> }
    if (body.results?.[0]) body.results[0].name_zh = longProductName
    await route.fulfill({ response, json: body })
  })

  const routes = [
    { path: "/", heading: /今天(?:至少)?有 \d+ 件事需要你决定/ },
    { path: "/promotion", heading: "你今天想推广什么？" },
    { path: "/lead-radar", heading: "客户机会" },
    { path: "/analytics", heading: "效果" },
    { path: "/company-profile", heading: "AI 对公司的了解" },
  ]

  for (const route of routes) {
    await page.goto(route.path)
    await expect(page.locator("main")).toBeVisible()
    if (route.path === "/company-profile") await expect(page.getByText(longProductName, { exact: true })).toBeVisible()

    const width = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }))
    expect(width.scrollWidth, `${route.path} must not overflow horizontally`).toBeLessThanOrEqual(width.clientWidth + 1)
  }
})
