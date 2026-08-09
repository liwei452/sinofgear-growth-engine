import { expect, type Page, test } from "@playwright/test"

const platforms = ["Facebook", "Instagram", "LinkedIn", "TikTok", "YouTube"]

function localDateTime(minutesAhead: number): string {
  const date = new Date(Date.now() + minutesAhead * 60_000)
  const two = (value: number) => String(value).padStart(2, "0")
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}T${two(date.getHours())}:${two(date.getMinutes())}`
}

async function scheduleAndRun(page: Page, platformCode: string, accountName: string) {
  await page.getByRole("button", { name: "安排发布" }).click()
  const content = page.getByLabel("已审核当前内容")
  const option = content.locator("option").filter({ hasText: `· ${platformCode}` })
  await expect(option).toHaveCount(1)
  await content.selectOption(await option.getAttribute("value") ?? "")
  await page.getByLabel("可发布账户").selectOption({ label: accountName })
  await page.getByLabel("发布时间").fill(localDateTime(10))
  await page.getByRole("button", { name: "确认安排" }).click()
  await expect(page.getByRole("status")).toContainText("发布任务已安排")
  const scheduled = page.locator(".task").filter({ hasText: "SCHEDULED" }).last()
  await expect(scheduled).toBeVisible()
  await scheduled.getByRole("button", { name: "立即运行" }).click()
}

test("Phase A active-growth loop, including publish failure recovery, works through the UI", async ({ page, context }) => {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_admin")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)

  await page.goto("/knowledge")
  for (const term of ["Helical Gear", "DIN", "Grinding", "Packaging Machinery"]) {
    await expect(page.getByText(term, { exact: true }).first()).toBeVisible()
  }
  await page.goto("/products")
  await expect(page.getByText("Custom Helical Gear", { exact: true })).toBeVisible()
  await page.goto("/assets")
  await expect(page.getByText("phase-a-factory-floor.mp4", { exact: true })).toBeVisible()

  await page.goto("/content-factory")
  const briefCard = page.locator(".workflow-card").filter({ hasText: "Phase A Helical Gear Growth" })
  await expect(briefCard).toContainText("可生成")
  await briefCard.getByRole("button", { name: "开始AI生成" }).click()
  await expect(page.getByText("生成完成", { exact: true })).toBeVisible()

  await page.goto("/reviews")
  const masterCard = page.locator(".review-card").first()
  await expect(masterCard).toBeVisible()
  await masterCard.getByRole("button", { name: "查看详情" }).click()
  await page.getByRole("button", { name: "查看AI生成记录" }).click()
  await expect(page.getByText(/phase-a-e2e-content-v1/)).toBeVisible()
  await page.getByText("安全字段摘要", { exact: true }).click()
  await expect(page.getByText(/ontology_snapshot/)).toBeVisible()
  await page.getByRole("button", { name: "通过", exact: true }).click()
  await expect(page.getByText("内容已通过。", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "生成平台版本" }).click()
  for (const platform of platforms) {
    await page.getByRole("button", { name: `为 ${platform} 生成`, exact: true }).click()
    await expect(page.getByText(`已为 ${platform} 准备平台版本。`, { exact: true })).toBeVisible()
  }
  await page.getByRole("button", { name: "关闭" }).click()

  await page.getByRole("tab", { name: "平台版本" }).click()
  const platformCards = page.locator(".review-card")
  await expect(platformCards).toHaveCount(5)
  for (let remaining = 5; remaining > 0; remaining -= 1) {
    await platformCards.first().getByRole("button", { name: "查看详情" }).click()
    await page.getByRole("button", { name: "通过", exact: true }).click()
    await expect(page.getByText("内容已通过。", { exact: true })).toBeVisible()
    await page.getByRole("button", { name: "关闭" }).click()
    await expect(platformCards).toHaveCount(remaining - 1)
  }

  await page.goto("/publishing-calendar")
  await scheduleAndRun(page, "FACEBOOK", "Phase A Facebook Mock")
  await expect(page.locator(".task").filter({ hasText: "SUCCEEDED" }).first()).toBeVisible()

  await scheduleAndRun(page, "TIKTOK", "Phase A TikTok Mock")
  const failed = page.locator(".task").filter({ hasText: "FAILED" }).first()
  await expect(failed).toContainText("Provider rejected the publish request")
  await failed.getByRole("button", { name: "重试" }).click()
  await expect(page.locator(".task").filter({ hasText: "SUCCEEDED" })).toHaveCount(2)

  await page.goto("/analytics")
  await page.getByRole("button", { name: "创建追踪链接" }).click()
  const published = page.getByRole("dialog").locator("select").first()
  await published.selectOption({ index: 1 })
  await page.getByLabel("来源").fill("facebook")
  await page.getByLabel("媒介").fill("social")
  await page.getByLabel("活动标识").fill("phase-a-e2e")
  await page.getByRole("button", { name: "创建", exact: true }).click()
  await expect(page.getByRole("status")).toContainText("追踪链接已创建")
  await page.getByRole("button", { name: "创建短链接" }).first().click()
  await expect(page.getByRole("status")).toContainText("短链接已创建")
  const shortPath = await page.locator("code").first().textContent()
  expect(shortPath).toMatch(/^\/r\//)
  const visitor = await context.newPage()
  await visitor.route("https://example.invalid/**", (route) => route.fulfill({ status: 200, body: "landing" }))
  await visitor.goto(shortPath ?? "/").catch(() => undefined)
  await visitor.close()
  await page.goto("/analytics")
  await expect(page.locator('[aria-label="总点击数"] strong')).toHaveText("1")
})
