import { expect, type Page, test } from "@playwright/test"

const platforms = ["Facebook", "Instagram", "LinkedIn", "TikTok", "YouTube"]
const facebookPlatformId = "10000000-0000-4000-8000-000000000601"

function localDateTime(minutesAhead: number): string {
  const date = new Date(Date.now() + minutesAhead * 60_000)
  const two = (value: number) => String(value).padStart(2, "0")
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}T${two(date.getHours())}:${two(date.getMinutes())}`
}

async function login(page: Page, username: "phasea_e2e_operator" | "phasea_e2e_reviewer") {
  await page.goto("/login")
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "退出登录" }).click()
  await expect(page).toHaveURL(/\/login$/)
}

async function selectCampaign(page: Page, campaignId: string) {
  await page.locator(".filters label").filter({ hasText: "活动" }).locator("select").selectOption(campaignId)
}

async function scheduleAndRun(page: Page, platformCode: string, accountName: string): Promise<string> {
  await page.getByRole("button", { name: "安排发布" }).click()
  const content = page.getByLabel("已审核当前内容")
  const option = content.locator("option").filter({ hasText: `· ${platformCode}` })
  await expect(option).toHaveCount(1)
  await content.selectOption(await option.getAttribute("value") ?? "")
  await page.getByLabel("可发布账户").selectOption({ label: accountName })
  await page.getByLabel("发布时间").fill(localDateTime(10))
  const responsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/publish-tasks/schedule" && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "确认安排" }).click()
  const response = await responsePromise
  expect(response.status()).toBe(201)
  const task = await response.json() as { id: string }
  await expect(page.getByRole("status")).toContainText("发布任务已安排")
  const scheduled = page.locator(".task").filter({ hasText: "SCHEDULED" }).last()
  await expect(scheduled).toBeVisible()
  await scheduled.getByRole("button", { name: "立即运行" }).click()
  return task.id
}

test("Phase A active-growth loop is role-correct and provenance-exact", async ({ page, context }) => {
  test.setTimeout(180_000)
  const campaignName = "Phase A Browser Growth"
  await login(page, "phasea_e2e_operator")

  await page.goto("/knowledge")
  for (const term of ["Helical Gear", "DIN", "Grinding", "Packaging Machinery"]) {
    await expect(page.getByText(term, { exact: true }).first()).toBeVisible()
  }
  await page.goto("/products")
  const product = page.locator("article").filter({ hasText: "Custom Helical Gear" })
  await expect(product.getByRole("list", { name: "知识标签" }).getByRole("listitem")).toHaveCount(4)
  await page.goto("/assets")
  const asset = page.locator("article").filter({ hasText: "phase-a-factory-floor.mp4" })
  await expect(asset).toContainText("关联产品：Custom Helical Gear")

  await page.goto("/content-factory")
  await page.getByRole("button", { name: "创建内容任务" }).click()
  await page.getByLabel("快速新建活动").check()
  await page.getByLabel("活动名称（必填）").fill(campaignName)
  await page.getByLabel("活动说明").fill("Browser-created industrial growth campaign")
  const campaignPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/campaigns" && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "下一步" }).click()
  const campaignResponse = await campaignPromise
  expect(campaignResponse.status()).toBe(201)
  const campaignId = (await campaignResponse.json() as { id: string }).id

  await page.getByRole("group", { name: "产品（至少一个）" }).getByRole("checkbox").first().check()
  for (const platform of platforms) await page.getByLabel(platform, { exact: true }).check()
  await page.getByLabel("phase-a-factory-floor.mp4", { exact: true }).check()
  await page.getByLabel("DIN (STANDARD)").check()
  await page.getByLabel("Packaging Machinery (INDUSTRY)").check()
  await page.getByRole("button", { name: "下一步" }).click()
  for (const [label, value] of [
    ["目标国家（必填）", "Germany"], ["客户类型（必填）", "Packaging machinery OEM"],
    ["内容目标（必填）", "Qualified industrial inquiries"], ["行动号召（必填）", "Request a quote"],
    ["落地页（必填）", "https://example.invalid/gears"], ["语言（必填）", "en"],
    ["卖点", "DIN precision, reliable delivery"], ["优势", "Grinding expertise"],
    ["关键词", "custom helical gear"], ["禁用说法", "never wears"],
  ] as const) await page.getByLabel(label, { exact: true }).fill(value)
  await page.getByRole("button", { name: "下一步" }).click()
  const briefPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/content-briefs" && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "创建需求草稿" }).click()
  const briefResponse = await briefPromise
  expect(briefResponse.status()).toBe(201)
  const briefId = (await briefResponse.json() as { id: string }).id
  const briefCard = page.locator(".workflow-card").filter({ hasText: campaignName })
  await expect(briefCard).toContainText("需求草稿")

  await logout(page)
  await login(page, "phasea_e2e_reviewer")
  await page.goto("/content-factory")
  await expect(briefCard).toContainText("需求草稿")
  await briefCard.getByRole("button", { name: "确认需求可生成" }).click()
  await expect(briefCard).toContainText("可生成")

  await logout(page)
  await login(page, "phasea_e2e_operator")
  await page.goto("/content-factory")
  const readyCard = page.locator(".workflow-card").filter({ hasText: campaignName })
  const generationPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/generate-master-content") && response.request().method() === "POST",
  )
  await readyCard.getByRole("button", { name: "开始AI生成" }).click()
  const generationResponse = await generationPromise
  expect(generationResponse.status()).toBe(202)
  const generationJobId = (await generationResponse.json() as { job_id: string }).job_id
  const jobCard = page.locator(".workflow-card").filter({ hasText: generationJobId })
  await expect(jobCard).toContainText("SUCCEEDED")
  await expect(jobCard).toContainText("生成完成")

  await logout(page)
  await login(page, "phasea_e2e_reviewer")
  await page.goto("/reviews")
  await selectCampaign(page, campaignId)
  const masterCard = page.locator(".review-card")
  await expect(masterCard).toHaveCount(1)
  await masterCard.getByRole("button", { name: "查看详情" }).click()
  await page.getByRole("button", { name: "查看AI生成记录" }).click()
  const audit = page.locator(".audit-panel")
  await expect(audit.getByText("SUCCEEDED", { exact: true })).toBeVisible()
  await expect(audit.getByText(/phase-a-e2e-content-v1/)).toBeVisible()
  await expect(audit.getByText("DIN", { exact: true })).toBeVisible()
  await expect(audit.getByText("PACKAGING_MACHINERY", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "通过", exact: true }).click()
  await expect(page.getByText("内容已通过。", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "关闭" }).click()

  await logout(page)
  await login(page, "phasea_e2e_operator")
  await page.goto("/reviews")
  await page.getByLabel("内容状态").selectOption("APPROVED")
  await selectCampaign(page, campaignId)
  await page.locator(".review-card").getByRole("button", { name: "查看详情" }).click()
  await page.getByRole("button", { name: "生成平台版本" }).click()
  for (const platform of platforms) {
    await page.getByRole("button", { name: `为 ${platform} 生成`, exact: true }).click()
    await expect(page.getByText(`已为 ${platform} 准备平台版本。`, { exact: true })).toBeVisible()
  }
  await page.getByRole("button", { name: "关闭" }).click()

  await logout(page)
  await login(page, "phasea_e2e_reviewer")
  await page.goto("/reviews")
  await page.getByRole("tab", { name: "平台版本" }).click()
  await selectCampaign(page, campaignId)
  const platformCards = page.locator(".review-card")
  await expect(platformCards).toHaveCount(5)
  for (let remaining = 5; remaining > 0; remaining -= 1) {
    await platformCards.first().getByRole("button", { name: "查看详情" }).click()
    await page.getByRole("button", { name: "通过", exact: true }).click()
    await expect(page.getByText("内容已通过。", { exact: true })).toBeVisible()
    await page.getByRole("button", { name: "关闭" }).click()
    await expect(platformCards).toHaveCount(remaining - 1)
  }

  await logout(page)
  await login(page, "phasea_e2e_operator")
  await page.goto("/publishing-calendar")
  const facebookTaskId = await scheduleAndRun(page, "FACEBOOK", "Phase A Facebook Mock")
  await expect(page.locator(".task").filter({ hasText: "SUCCEEDED" })).toHaveCount(1)
  await scheduleAndRun(page, "TIKTOK", "Phase A TikTok Mock")
  const failed = page.locator(".task").filter({ hasText: "FAILED" }).first()
  await expect(failed).toContainText("FAILED")
  await expect(failed).toContainText("Provider rejected the publish request")
  await failed.getByRole("button", { name: "重试" }).click()
  await expect(page.locator(".task").filter({ hasText: "SUCCEEDED" })).toHaveCount(2)

  await page.goto("/analytics")
  await page.getByRole("button", { name: "创建追踪链接" }).click()
  const trackingDialog = page.getByRole("dialog")
  await trackingDialog.getByLabel("已发布内容").selectOption(facebookTaskId)
  await trackingDialog.getByLabel("来源").fill("facebook")
  await trackingDialog.getByLabel("媒介").fill("social")
  await trackingDialog.getByLabel("活动标识").fill("phase-a-browser-growth")
  await trackingDialog.getByRole("button", { name: "创建", exact: true }).click()
  await expect(page.getByRole("status")).toContainText("追踪链接已创建")
  await page.getByRole("button", { name: "创建短链接" }).first().click()
  await expect(page.getByRole("status")).toContainText("短链接已创建")
  const shortPath = await page.locator("code").first().textContent()
  expect(shortPath).toMatch(/^\/r\//)
  const redirectResponse = await context.request.get(`${new URL(page.url()).origin}${shortPath}`, { maxRedirects: 0 })
  expect(redirectResponse.status()).toBe(302)
  expect(redirectResponse.headers().location).toMatch(/^https:\/\/example\.invalid\/gears\?/)

  await page.goto("/analytics")
  await page.getByLabel("活动", { exact: true }).fill(campaignId)
  await page.getByLabel("平台", { exact: true }).fill(facebookPlatformId)
  await expect(page.locator('[aria-label="总点击数"] strong')).toHaveText("1")
  const analyticsRow = page.getByRole("row").filter({ hasText: facebookPlatformId })
  await expect(analyticsRow).toContainText("1")
  expect(briefId).toBeTruthy()
})
