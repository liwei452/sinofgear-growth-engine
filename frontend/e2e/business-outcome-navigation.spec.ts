import { expect, type Page, test } from "@playwright/test"

const password = "PhaseA-E2E-Only!"

async function login(page: Page, username = "phasea_e2e_admin") {
  await page.goto("/login")
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill(password)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}

test.describe("business outcome navigation", () => {
  test("desktop has the five permission-aware primary destinations and one main landmark", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await login(page)

    const navigation = page.getByRole("navigation", { name: "主导航" })
    await expect(navigation.getByRole("link")).toHaveCount(5)
    await page.getByRole("link", { name: "客户机会" }).click()
    await expect(page).toHaveURL(/\/opportunities/)
    await expect(page.getByRole("heading", { name: "客户机会" })).toBeVisible()
    for (const destination of [
      "/", "/promotion", "/opportunities", "/content-factory", "/analytics", "/company", "/settings",
    ]) {
      await page.goto(destination)
      await expect(page.locator("main")).toHaveCount(1)
    }
    await expectNoHorizontalOverflow(page)
  })

  test("mobile drawer closes with Escape and restores focus to its trigger", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await login(page)

    const trigger = page.getByRole("button", { name: "打开导航" })
    await trigger.click()
    await expect(page.getByTestId("app-sidebar")).toHaveClass(/app-sidebar-open/)
    await page.keyboard.press("Escape")
    await expect(page.getByTestId("app-sidebar")).not.toHaveClass(/app-sidebar-open/)
    await expect(trigger).toBeFocused()
    await expectNoHorizontalOverflow(page)
  })

  test("legacy mission deep links remain authenticated and reachable", async ({ page }) => {
    await login(page)
    await page.goto("/missions/00000000-0000-4000-8000-000000000999?view=customer")
    await expect(page).toHaveURL(/\/missions\/00000000-0000-4000-8000-000000000999\?view=customer/)
    await expect(page.getByRole("heading", { name: "增长任务" })).toBeVisible()
  })

  test("opportunity filters and the selected candidate survive refresh and Back", async ({ page }) => {
    await login(page)
    await page.goto("/opportunities")
    const company = "Northstar Gearworks"
    await page.getByRole("button", { name: "导入候选名单" }).click()
    await page.getByLabel("候选名单内容").fill([
      "company_name,country,website,industry",
      `${company},Germany,https://example.invalid/northstar-gears,industrial gears`,
    ].join("\n"))
    await page.getByRole("button", { name: "导入并进入人工审核" }).click()
    await expect(page.getByText(company, { exact: true })).toBeVisible()

    await page.getByRole("searchbox", { name: "搜索客户机会" }).fill("Northstar")
    await page.getByLabel("阶段").selectOption("CANDIDATE")
    await page.getByLabel("排序").selectOption("newest")
    await page.getByRole("button", { name: `查看 ${company} 的证据` }).click()
    await expect(page).toHaveURL(/stage=CANDIDATE&sort=newest&q=Northstar&selected=/)
    await page.reload()
    await expect(page.getByRole("heading", { name: company })).toBeVisible()

    await page.goto("/promotion")
    await page.goBack()
    await expect(page).toHaveURL(/\/opportunities\?stage=CANDIDATE&sort=newest&q=Northstar&selected=/)
    await expect(page.getByRole("heading", { name: company })).toBeVisible()
  })

  test("a manually imported candidate moves from review through enrichment and follow-up to an unsent contact draft", async ({ page }) => {
    await login(page)
    await page.goto("/opportunities")
    const company = "Orbit Drive Components"
    const requests: string[] = []
    page.on("request", request => requests.push(new URL(request.url()).pathname))

    await page.getByRole("button", { name: "导入候选名单" }).click()
    await page.getByLabel("候选名单内容").fill([
      "company_name,country,website,industry",
      `${company},France,https://example.invalid/orbit-drive,gear manufacturing`,
    ].join("\n"))
    await page.getByRole("button", { name: "导入并进入人工审核" }).click()
    await page.getByRole("button", { name: `查看 ${company} 的证据` }).click()
    await page.getByRole("button", { name: "人工接受候选" }).click()
    await expect(page.getByRole("button", { name: "准备资料补全" })).toBeVisible()
    await page.getByRole("button", { name: "准备资料补全" }).click()
    await expect(page.getByRole("button", { name: "加入跟进" })).toBeVisible()
    await page.getByRole("button", { name: "加入跟进" }).click()
    await expect(page.getByRole("button", { name: "生成联系草稿" })).toBeVisible()
    await page.getByRole("button", { name: "生成联系草稿" }).click()
    await expect(page.getByText("状态为未发送。", { exact: false })).toBeVisible()
    expect(requests.some(path => /\/publish-tasks\/[^/]+\/run$|\/outreach.*send/.test(path))).toBe(false)
  })

  test("users without lead-management permission do not see the protected opportunities destination", async ({ page }) => {
    await login(page, "phasea_e2e_viewer")
    const navigation = page.getByRole("navigation", { name: "主导航" })
    await expect(navigation.getByRole("link", { name: "今日" })).toBeVisible()
    await expect(navigation.getByRole("link", { name: "开始推广" })).toBeVisible()
    await expect(navigation.getByRole("link", { name: "客户机会" })).toHaveCount(0)
    await expect(navigation.getByRole("link", { name: "内容与发布" })).toBeVisible()
    await expect(navigation.getByRole("link", { name: "效果" })).toBeVisible()
  })
})
