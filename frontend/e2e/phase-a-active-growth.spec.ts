import { expect, type BrowserContext, type Page, test } from "@playwright/test"

const platforms = ["Facebook", "Instagram", "LinkedIn", "TikTok", "YouTube"]
const facebookPlatformId = "10000000-0000-4000-8000-000000000601"
const linkedinPlatformId = "10000000-0000-4000-8000-000000000603"
const seededCampaignId = "10000000-0000-4000-8000-000000000301"

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
  await page.getByLabel("推广计划").selectOption(campaignId)
}

async function openAnalyticsOperations(page: Page) {
  const operations = page.locator("details.operations")
  if (!await operations.evaluate(element => (element as HTMLDetailsElement).open)) {
    await operations.locator("summary").click()
  }
}

async function scheduleAndRun(
  page: Page,
  platformCode: string,
  accountName: string,
  platformContentId?: string,
): Promise<string> {
  await page.getByRole("button", { name: "安排发布" }).click()
  const content = page.getByLabel("已审核当前内容")
  if (platformContentId) {
    await content.selectOption(platformContentId)
  } else {
    const option = content.locator("option").filter({ hasText: `· ${platformCode}` })
    await expect(option).toHaveCount(1)
    await content.selectOption(await option.getAttribute("value") ?? "")
  }
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

async function createTrackingAndShort(
  page: Page,
  taskId: string,
  source: string,
  campaignMarker: string,
): Promise<string> {
  await openAnalyticsOperations(page)
  const existingPaths = new Set(await page.locator("code").allTextContents())
  await page.getByRole("button", { name: "创建追踪链接" }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByLabel("已发布内容").selectOption(taskId)
  await dialog.getByLabel("来源").fill(source)
  await dialog.getByLabel("媒介").fill("social")
  await dialog.getByLabel("活动标识").fill(campaignMarker)
  await dialog.getByRole("button", { name: "创建", exact: true }).click()
  await expect(page.getByRole("status")).toContainText("追踪链接已创建")
  const tracking = page.locator("article.link-row").filter({ hasText: campaignMarker })
  await expect(tracking).toHaveCount(1)
  await tracking.getByRole("button", { name: "创建短链接" }).click()
  await expect(page.getByRole("status")).toContainText("短链接已创建")
  await expect.poll(async () => (await page.locator("code").allTextContents()).length).toBe(existingPaths.size + 1)
  const newPath = (await page.locator("code").allTextContents()).find(path => !existingPaths.has(path))
  expect(newPath).toMatch(/^\/r\//)
  return newPath!
}

async function visitShortLink(
  context: BrowserContext,
  origin: string,
  shortPath: string,
  destinationPath: string,
  source: string,
  campaignMarker: string,
) {
  const visitor = await context.newPage()
  await visitor.route("https://example.invalid/**", route => route.fulfill({ status: 204 }))
  const redirectPromise = visitor.waitForResponse(response =>
    new URL(response.url()).pathname === shortPath && response.status() === 302,
  )
  const navigation = visitor.goto(`${origin}${shortPath}`, { waitUntil: "commit" }).catch(error => error as Error)
  const redirect = await redirectPromise
  expect(redirect.status()).toBe(302)
  const location = redirect.headers()["location"]
  expect(location).toBeTruthy()
  const destination = new URL(location!)
  expect(`${destination.origin}${destination.pathname}`).toBe(`https://example.invalid${destinationPath}`)
  expect(destination.searchParams.get("utm_source")).toBe(source)
  expect(destination.searchParams.get("utm_medium")).toBe("social")
  expect(destination.searchParams.get("utm_campaign")).toBe(campaignMarker)
  await navigation
  await visitor.close()
}

test("Phase A active-growth loop is role-correct and provenance-exact", async ({ page, context }) => {
  test.setTimeout(180_000)
  const internalObjectNames = /Campaign|ContentBrief|MasterContent|PlatformContent/
  let seededLinkedInContentId = ""
  await login(page, "phasea_e2e_operator")

  await page.goto("/knowledge")
  for (const term of ["Helical Gear", "DIN", "Grinding", "Packaging Machinery"]) {
    await expect(page.getByText(term, { exact: true }).first()).toBeVisible()
  }
  await page.goto("/products")
  const product = page.locator("article").filter({ hasText: "Custom Helical Gear" })
  const productConcepts = product.getByRole("list", { name: "知识标签" }).locator("code")
  await expect(productConcepts).toHaveCount(4)
  expect((await productConcepts.allTextContents()).sort()).toEqual(
    ["HELICAL_GEAR", "DIN", "GRINDING", "PACKAGING_MACHINERY"].sort(),
  )
  await page.goto("/assets")
  const asset = page.locator("article").filter({ hasText: "phase-a-factory-floor.mp4" })
  await expect(asset).toContainText("关联产品：Custom Helical Gear")

  await page.goto("/promotion")
  await expect(page.getByRole("heading", { name: "你今天想推广什么？" })).toBeVisible()
  const seededGenerate = page.getByRole("button", { name: "生成推广内容" })
  await expect(seededGenerate).toBeEnabled()
  const seededGenerationPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/generate-master-content") && response.request().method() === "POST",
  )
  await seededGenerate.click()
  const seededGenerationResponse = await seededGenerationPromise
  expect(seededGenerationResponse.status()).toBe(202)
  await expect(page.getByRole("link", { name: "查看并确认" })).toBeVisible({ timeout: 15_000 })

  await page.getByRole("button", { name: "开始新的推广" }).click()
  const wizard = page.getByRole("dialog", { name: "制定推广方案" })
  await wizard.getByLabel("定制斜齿轮", { exact: true }).check()
  await wizard.getByRole("button", { name: "保存产品并继续" }).click()
  await wizard.getByLabel("目标市场（必选）").selectOption({ label: "德国" })
  await wizard.getByLabel("目标客户（必选）").selectOption({ label: "工业采购" })
  await wizard.getByLabel("推广目标（必选）").selectOption({ label: "获取询盘" })
  await wizard.getByLabel("希望客户下一步（必选）").selectOption({ label: "立即询价" })
  await wizard.getByLabel("内容语言（必选）").selectOption("en")
  await wizard.getByLabel("落地页（可选）").fill("https://example.invalid/gears")
  for (const platform of platforms) await wizard.getByLabel(platform, { exact: true }).check()
  await wizard.getByRole("button", { name: "保存目标并查看素材" }).click()
  await wizard.getByLabel("phase-a-factory-floor.mp4", { exact: true }).check()
  await wizard.getByLabel("Helical Gear (PRODUCT_TYPE)").check()
  await wizard.getByLabel("Grinding (PROCESS)").check()
  await wizard.getByLabel("DIN (STANDARD)").check()
  await wizard.getByLabel("Packaging Machinery (INDUSTRY)").check()
  await wizard.getByLabel("补充卖点（简短填写）").fill("DIN precision, reliable delivery")
  await wizard.getByLabel("补充优势（简短填写）").fill("Grinding expertise")
  await wizard.getByLabel("关键词（逗号分隔）").fill("custom helical gear")
  await wizard.getByLabel("不能使用的说法（可选）").fill("never wears")
  await wizard.getByRole("button", { name: "查看并确认方案" }).click()
  await expect(wizard.getByRole("heading", { name: "确认方案" })).toBeVisible()
  const campaignPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/campaigns" && response.request().method() === "POST",
  )
  const briefPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/content-briefs" && response.request().method() === "POST",
  )
  await wizard.getByRole("button", { name: "保存推广方案" }).click()
  const campaignResponse = await campaignPromise
  expect(campaignResponse.status()).toBe(201)
  const campaignPayload = await campaignResponse.json() as { id: string; name: string }
  const campaignId = campaignPayload.id
  const briefResponse = await briefPromise
  expect(briefResponse.status()).toBe(201)
  const briefPayload = await briefResponse.json() as {
    id: string
    concept_links: Array<{ role: string; concept_id: string }>
  }
  const briefId = briefPayload.id
  expect(briefPayload.concept_links.map(link => link.role).sort()).toEqual([
    "MANUFACTURING_PROCESS", "PRODUCT_TYPE", "STANDARD", "TARGET_INDUSTRY",
  ])
  await expect(page.getByRole("status")).toContainText("推广方案已保存，等待有权限的同事确认。")
  await expect(page.locator("body")).not.toContainText(internalObjectNames)

  await logout(page)
  await login(page, "phasea_e2e_reviewer")
  await page.goto("/promotion")
  const readyPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/ready") && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "确认方案可生成" }).click()
  const readyResponse = await readyPromise
  expect(readyResponse.status(), await readyResponse.text()).toBe(200)
  await expect(page.getByRole("status")).toContainText("需求已确认，可以开始生成。")
  await expect(page.locator("body")).not.toContainText(internalObjectNames)

  await logout(page)
  await login(page, "phasea_e2e_operator")
  await page.goto("/promotion")
  const generate = page.getByRole("button", { name: "生成推广内容" })
  await expect(generate).toBeEnabled()
  const generationPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/generate-master-content") && response.request().method() === "POST",
  )
  await generate.click()
  const generationResponse = await generationPromise
  expect(generationResponse.status()).toBe(202)
  await expect(page.getByRole("link", { name: "查看并确认" })).toBeVisible({ timeout: 15_000 })
  await expect(page.locator("body")).not.toContainText(internalObjectNames)
  await page.getByRole("link", { name: "查看并确认" }).click()
  await expect(page).toHaveURL(/\/reviews$/)
  await expect(page.getByRole("heading", { name: "审核中心", level: 1 })).toBeVisible()
  await expect(page.locator("body")).not.toContainText(internalObjectNames)

  await logout(page)
  await login(page, "phasea_e2e_reviewer")
  await page.goto("/reviews")
  await selectCampaign(page, campaignId)
  const masterCard = page.locator(".review-card")
  await expect(masterCard).toHaveCount(1)
  await masterCard.getByRole("button", { name: "查看并确认" }).click()
  await page.getByRole("button", { name: "查看AI生成记录" }).click()
  const audit = page.locator(".audit-panel")
  await expect(audit.getByText("已完成", { exact: true })).toBeVisible()
  await audit.getByText("高级模型记录", { exact: true }).click()
  await expect(audit.getByText(/phase-a-e2e-content-v1/)).toBeVisible()
  await expect(audit.getByText("HELICAL_GEAR", { exact: true })).toBeVisible()
  await expect(audit.getByText("GRINDING", { exact: true })).toBeVisible()
  await expect(audit.getByText("DIN", { exact: true })).toBeVisible()
  await expect(audit.getByText("PACKAGING_MACHINERY", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "批准发布", exact: true }).click()
  await expect(page.getByText("内容已通过。", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "关闭" }).click()
  await selectCampaign(page, seededCampaignId)
  const seededMasterCard = page.locator(".review-card")
  await expect(seededMasterCard).toHaveCount(1)
  await seededMasterCard.getByRole("button", { name: "查看并确认" }).click()
  await page.getByRole("button", { name: "批准发布", exact: true }).click()
  await expect(page.getByText("内容已通过。", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "关闭" }).click()

  await logout(page)
  await login(page, "phasea_e2e_operator")
  await page.goto("/reviews")
  await page.getByLabel("内容状态").selectOption("APPROVED")
  await selectCampaign(page, campaignId)
  await page.locator(".review-card").getByRole("button", { name: "查看并确认" }).click()
  await page.getByRole("button", { name: "生成渠道版本" }).click()
  for (const platform of platforms) {
    await page.getByRole("button", { name: `为 ${platform} 生成`, exact: true }).click()
    await expect(page.getByText(`已为 ${platform} 准备平台版本。`, { exact: true })).toBeVisible()
  }
  await page.getByRole("button", { name: "关闭" }).click()
  await selectCampaign(page, seededCampaignId)
  const seededApprovedCard = page.locator(".review-card")
  await expect(seededApprovedCard).toHaveCount(1)
  await seededApprovedCard.getByRole("button", { name: "查看并确认" }).click()
  await page.getByRole("button", { name: "生成渠道版本" }).click()
  const seededLinkedInPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/generate-platform-content")
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "为 LinkedIn 生成", exact: true }).click()
  const seededLinkedInResponse = await seededLinkedInPromise
  expect(seededLinkedInResponse.status()).toBe(201)
  seededLinkedInContentId = (await seededLinkedInResponse.json() as { id: string }).id
  await expect(page.getByText("已为 LinkedIn 准备平台版本。", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "关闭" }).click()

  await logout(page)
  await login(page, "phasea_e2e_reviewer")
  await page.goto("/reviews")
  await page.getByRole("tab", { name: "渠道文案" }).click()
  await selectCampaign(page, campaignId)
  const platformCards = page.locator(".review-card")
  await expect(platformCards).toHaveCount(5)
  for (let remaining = 5; remaining > 0; remaining -= 1) {
    await platformCards.first().getByRole("button", { name: "查看并确认" }).click()
    await page.getByRole("button", { name: "批准发布", exact: true }).click()
    await expect(page.getByText("内容已通过。", { exact: true })).toBeVisible()
    await page.getByRole("button", { name: "关闭" }).click()
    await expect(platformCards).toHaveCount(remaining - 1)
  }
  await selectCampaign(page, seededCampaignId)
  const seededPlatformCard = page.locator(".review-card")
  await expect(seededPlatformCard).toHaveCount(1)
  await seededPlatformCard.getByRole("button", { name: "查看并确认" }).click()
  await page.getByRole("button", { name: "批准发布", exact: true }).click()
  await expect(page.getByText("内容已通过。", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "关闭" }).click()

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
  const linkedinTaskId = await scheduleAndRun(
    page, "LINKEDIN", "Phase A LinkedIn Mock", seededLinkedInContentId,
  )
  await expect(page.locator(".task").filter({ hasText: "SUCCEEDED" })).toHaveCount(3)

  await page.goto("/analytics")
  const origin = new URL(page.url()).origin
  const facebookShortPath = await createTrackingAndShort(
    page, facebookTaskId, "facebook", "phase-a-browser-growth",
  )
  const linkedinShortPath = await createTrackingAndShort(
    page, linkedinTaskId, "linkedin", "phase-a-seeded-growth",
  )
  await visitShortLink(context, origin, facebookShortPath, "/gears", "facebook", "phase-a-browser-growth")
  await visitShortLink(
    context, origin, linkedinShortPath, "/custom-helical-gear", "linkedin", "phase-a-seeded-growth",
  )

  await page.goto("/analytics")
  await openAnalyticsOperations(page)
  await expect(page.locator('[aria-label="总点击数"] strong')).toHaveText("2")
  const unfilteredRows = page.getByRole("table", { name: "渠道点击明细" }).getByRole("row")
  await expect(unfilteredRows).toHaveCount(3)
  await page.getByLabel("活动", { exact: true }).fill(campaignId)
  await page.getByLabel("平台", { exact: true }).fill(facebookPlatformId)
  await expect(page.locator('[aria-label="总点击数"] strong')).toHaveText("1")
  const analyticsTable = page.getByRole("table", { name: "渠道点击明细" })
  await expect(analyticsTable.getByRole("row")).toHaveCount(2)
  const analyticsRow = analyticsTable.getByRole("row").nth(1)
  await expect(analyticsRow).toContainText(campaignPayload.name)
  await expect(analyticsRow).toContainText("Facebook")
  await expect(analyticsRow).toContainText("1")
  await expect(page.locator("body")).not.toContainText(campaignId)
  await expect(page.locator("body")).not.toContainText(facebookPlatformId)
  await page.getByLabel("活动", { exact: true }).fill(seededCampaignId)
  await page.getByLabel("平台", { exact: true }).fill(linkedinPlatformId)
  await expect(page.locator('[aria-label="总点击数"] strong')).toHaveText("1")
  await expect(analyticsTable.getByRole("row")).toHaveCount(2)
  const seededAnalyticsRow = analyticsTable.getByRole("row").nth(1)
  await expect(seededAnalyticsRow).toContainText("Phase A Helical Gear Growth")
  await expect(seededAnalyticsRow).toContainText("LinkedIn")
  await expect(seededAnalyticsRow).toContainText("1")
  await expect(page.locator("body")).not.toContainText(seededCampaignId)
  await expect(page.locator("body")).not.toContainText(linkedinPlatformId)
  expect(briefId).toBeTruthy()
})
