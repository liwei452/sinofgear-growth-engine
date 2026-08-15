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

async function login(page: Page, username: "phasea_e2e_admin" | "phasea_e2e_operator" | "phasea_e2e_reviewer") {
  await page.goto("/login")
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "打开用户菜单" }).click()
  await page.getByRole("menuitem", { name: "退出登录" }).click()
  await expect(page).toHaveURL(/\/login$/)
}

async function selectCampaign(page: Page, campaignId: string) {
  await page.locator(".filters label").filter({ hasText: "活动" }).locator("select").selectOption(campaignId)
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
  const campaignName = "Phase A Browser Growth"
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

  await page.goto("/content-factory")
  const seededReadyCard = page.locator(".workflow-card").filter({ hasText: "Phase A Helical Gear Growth" })
  const seededGenerationPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/generate-master-content") && response.request().method() === "POST",
  )
  await seededReadyCard.getByRole("button", { name: "开始AI生成" }).click()
  await expect(page.getByText("Fake / 离线演示生成").first()).toBeVisible()
  await expect(page.getByText("该结果必须人工审核，不能视为真实模型结论。")).toBeVisible()
  const seededGenerationResponse = await seededGenerationPromise
  expect(seededGenerationResponse.status()).toBe(202)
  const seededGenerationJobId = (await seededGenerationResponse.json() as { job_id: string }).job_id
  const seededJobCard = page.locator(".workflow-card").filter({ hasText: seededGenerationJobId })
  await expect(seededJobCard).toContainText("SUCCEEDED")
  await expect(seededJobCard).toContainText("生成完成")
  await expect(page.locator(".generated-result")).toBeVisible()
  const seededSubmitPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/submit-review") && response.request().method() === "POST",
  )
  await page.locator(".generated-result").getByRole("button", { name: "提交审核" }).click()
  expect((await seededSubmitPromise).status()).toBe(200)

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
  await page.getByLabel("Helical Gear (PRODUCT_TYPE)").check()
  await page.getByLabel("Grinding (PROCESS)").check()
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
  const briefPayload = await briefResponse.json() as {
    id: string
    concept_links: Array<{ role: string; concept_id: string }>
  }
  const briefId = briefPayload.id
  expect(briefPayload.concept_links.map(link => link.role).sort()).toEqual([
    "MANUFACTURING_PROCESS", "PRODUCT_TYPE", "STANDARD", "TARGET_INDUSTRY",
  ])
  const briefCard = page.locator(".workflow-card").filter({ hasText: campaignName })
  await expect(briefCard).toContainText("需求草稿")

  await logout(page)
  await login(page, "phasea_e2e_reviewer")
  await page.goto("/content-factory")
  await expect(briefCard).toContainText("需求草稿")
  const readyResponsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/ready") && response.request().method() === "POST",
  )
  await briefCard.getByRole("button", { name: "确认需求可生成" }).click()
  const readyResponse = await readyResponsePromise
  expect(readyResponse.status(), await readyResponse.text()).toBe(200)
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
  await expect(page.locator(".generated-result")).toBeVisible()
  const submitReviewPromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/submit-review") && response.request().method() === "POST",
  )
  await page.locator(".generated-result").getByRole("button", { name: "提交审核" }).click()
  const submitReviewResponse = await submitReviewPromise
  expect(submitReviewResponse.status(), await submitReviewResponse.text()).toBe(200)

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
  await expect(audit.getByText("HELICAL_GEAR", { exact: true })).toBeVisible()
  await expect(audit.getByText("GRINDING", { exact: true })).toBeVisible()
  await expect(audit.getByText("DIN", { exact: true })).toBeVisible()
  await expect(audit.getByText("PACKAGING_MACHINERY", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "通过", exact: true }).click()
  await expect(page.getByText("内容已通过。", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "关闭" }).click()
  await selectCampaign(page, seededCampaignId)
  const seededMasterCard = page.locator(".review-card")
  await expect(seededMasterCard).toHaveCount(1)
  await seededMasterCard.getByRole("button", { name: "查看详情" }).click()
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
  await selectCampaign(page, seededCampaignId)
  const seededApprovedCard = page.locator(".review-card")
  await expect(seededApprovedCard).toHaveCount(1)
  await seededApprovedCard.getByRole("button", { name: "查看详情" }).click()
  await page.getByRole("button", { name: "生成平台版本" }).click()
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
  await selectCampaign(page, seededCampaignId)
  const seededPlatformCard = page.locator(".review-card")
  await expect(seededPlatformCard).toHaveCount(1)
  await seededPlatformCard.getByRole("button", { name: "查看详情" }).click()
  await page.getByRole("button", { name: "通过", exact: true }).click()
  await expect(page.getByText("内容已通过。", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "关闭" }).click()

  await logout(page)
  await login(page, "phasea_e2e_operator")
  await page.goto("/reviews")
  await page.getByRole("tab", { name: "平台版本" }).click()
  await page.getByLabel("内容状态").selectOption("APPROVED")
  await selectCampaign(page, campaignId)
  const approvedPlatformCards = page.locator(".review-card")
  await expect(approvedPlatformCards).toHaveCount(5)
  let preparedPackages = 0
  for (let index = 0; index < 5; index += 1) {
    await approvedPlatformCards.nth(index).getByRole("button", { name: "查看详情" }).click()
    const prepareButton = page.getByRole("button", { name: "加入一键发布" })
    if (await prepareButton.count()) {
      const prepareResponse = page.waitForResponse(response =>
        new URL(response.url()).pathname.includes("/growth/channel-packages/from-platform-content/")
          && response.request().method() === "POST",
      )
      await prepareButton.click()
      expect((await prepareResponse).status()).toBe(201)
      await expect(page.getByText("已加入推广页的一键发布准备，仍需逐渠道审核。", { exact: true }))
        .toBeVisible()
      preparedPackages += 1
    }
    await page.getByRole("button", { name: "关闭" }).click()
  }
  expect(preparedPackages).toBe(4)

  await page.reload()
  await page.getByRole("tab", { name: "平台版本" }).click()
  await page.getByLabel("内容状态").selectOption("APPROVED")
  await selectCampaign(page, campaignId)
  let persistedPrepared = 0
  for (let index = 0; index < 5; index += 1) {
    await page.locator(".review-card").nth(index).getByRole("button", { name: "查看详情" }).click()
    if (await page.getByRole("button", { name: "已加入发布准备" }).count()) persistedPrepared += 1
    await page.getByRole("button", { name: "关闭" }).click()
  }
  expect(persistedPrepared).toBe(4)

  const workspaceResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/workspace"
      && response.request().method() === "GET",
  )
  await page.goto("/promotion")
  const preparedWorkspace = await (await workspaceResponse).json() as {
    channel_packages: Array<{
      source_platform_content_id: string | null
      channel: string
      status: string
      payload: { verified_fact_evidence: unknown[] }
    }>
  }
  const prepared = preparedWorkspace.channel_packages.filter(item => item.source_platform_content_id)
  expect(prepared).toHaveLength(4)
  expect(prepared.map(item => item.channel).sort()).toEqual(["FACEBOOK", "INSTAGRAM", "LINKEDIN", "TIKTOK"])
  expect(prepared.every(item => item.status === "AWAITING_REVIEW")).toBe(true)
  expect(prepared.every(item => Array.isArray(item.payload.verified_fact_evidence))).toBe(true)

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

  await logout(page)
  await login(page, "phasea_e2e_admin")
  await page.goto("/admin/analytics")
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

  await page.goto("/admin/analytics")
  await expect(page.locator('[aria-label="总点击数"] strong')).toHaveText("2")
  const unfilteredRows = page.getByRole("table", { name: "渠道点击明细" }).getByRole("row")
  await expect(unfilteredRows).toHaveCount(3)
  await page.getByLabel("活动", { exact: true }).fill(campaignId)
  await page.getByLabel("平台", { exact: true }).fill(facebookPlatformId)
  await expect(page.locator('[aria-label="总点击数"] strong')).toHaveText("1")
  const analyticsRow = page.getByRole("row").filter({ hasText: facebookPlatformId })
  await expect(analyticsRow).toContainText(campaignId)
  await expect(analyticsRow).toContainText("1")
  await page.getByLabel("活动", { exact: true }).fill(seededCampaignId)
  await page.getByLabel("平台", { exact: true }).fill(linkedinPlatformId)
  await expect(page.locator('[aria-label="总点击数"] strong')).toHaveText("1")
  const seededAnalyticsRow = page.getByRole("row").filter({ hasText: linkedinPlatformId })
  await expect(seededAnalyticsRow).toContainText(seededCampaignId)
  await expect(seededAnalyticsRow).toContainText("1")
  expect(briefId).toBeTruthy()
})
