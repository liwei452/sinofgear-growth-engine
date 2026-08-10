import { expect, type APIResponse, type Page, test } from "@playwright/test"

const password = "PhaseA-E2E-Only!"

type SeedUser =
  | "phasea_e2e_admin"
  | "phasea_e2e_operator"
  | "phasea_e2e_reviewer"
  | "phasea_e2e_viewer"

type EvidencePage = {
  results: Array<{ id: string; original_text: string; source_url: string }>
}

async function login(page: Page, username: SeedUser): Promise<void> {
  await page.goto("/login")
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill(password)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function logout(page: Page): Promise<void> {
  await page.getByRole("button", { name: "退出登录" }).click()
  await expect(page).toHaveURL(/\/login$/)
}

async function expectOk(response: APIResponse): Promise<APIResponse> {
  const body = await response.text()
  expect(response.status(), body).toBeGreaterThanOrEqual(200)
  expect(response.status(), body).toBeLessThan(300)
  return response
}

async function csrfToken(page: Page): Promise<string> {
  const cookie = (await page.context().cookies()).find((item) => item.name === "csrftoken")
  expect(cookie, "an authenticated browser context must have a CSRF cookie").toBeDefined()
  return cookie!.value
}

async function createCandidateFromEvidence(
  page: Page,
  evidenceId: string,
  companyName: string,
): Promise<string> {
  const response = await page.request.post("/api/v1/lead-candidates", {
    data: {
      company_name: companyName,
      company_domain: "browser-prospect.example",
      country_hint: "DE",
      evidence_ids: [evidenceId],
    },
    headers: { "X-CSRFToken": await csrfToken(page) },
  })
  await expectOk(response)
  return (await response.json() as { id: string }).id
}

async function completeBeginnerPromotion(page: Page): Promise<void> {
  await page.getByRole("link", { name: "推广", exact: true }).click()
  await expect(page.getByRole("heading", { name: "你今天想推广什么？" })).toBeVisible()
  await expect(page.getByRole("list", { name: "推广流程" })).toContainText("选择推广目标")
  await expect(page.getByRole("list", { name: "推广流程" })).toContainText("确认 AI 方案")
  await expect(page.getByRole("list", { name: "推广流程" })).toContainText("批准后执行")
  await expect(page.getByRole("heading", { name: "内容需求" })).toHaveCount(0)

  await page.getByRole("button", { name: "让 AI 给我方案" }).click()
  const wizard = page.getByRole("dialog", { name: "创建内容任务" })
  await wizard.getByLabel("快速新建活动").check()
  await wizard.getByLabel("活动名称（必填）").fill("Task 11D Browser Promotion")
  await wizard.getByLabel("活动说明").fill("A real beginner promotion journey created by browser acceptance.")
  const campaignResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/v1/campaigns"
      && response.request().method() === "POST",
  )
  await wizard.getByRole("button", { name: "下一步" }).click()
  expect((await campaignResponse).status()).toBe(201)

  await wizard.getByRole("group", { name: "产品（至少一个）" }).getByRole("checkbox").first().check()
  await wizard.getByRole("group", { name: "平台（至少一个）" }).getByRole("checkbox").first().check()
  await wizard.getByRole("button", { name: "下一步" }).click()

  for (const [label, value] of [
    ["目标国家（必填）", "Germany"],
    ["客户类型（必填）", "Packaging machinery OEM"],
    ["内容目标（必填）", "Qualified industrial inquiries"],
    ["行动号召（必填）", "Request a quote"],
    ["落地页（必填）", "https://example.invalid/task-11d-gears"],
    ["语言（必填）", "en"],
    ["卖点", "DIN precision"],
    ["优势", "Grinding expertise"],
    ["关键词", "replacement helical gear"],
    ["禁用说法", "never wears"],
  ] as const) await wizard.getByLabel(label, { exact: true }).fill(value)
  await wizard.getByRole("button", { name: "下一步" }).click()

  const briefResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/v1/content-briefs"
      && response.request().method() === "POST",
  )
  await wizard.getByRole("button", { name: "创建需求草稿" }).click()
  expect((await briefResponse).status()).toBe(201)
  await expect(page.getByRole("status")).toContainText("推广方案已保存，等待有权限的同事确认。")
}

test("ordinary cockpit has five entries and completes a beginner promotion", async ({ page }) => {
  await login(page, "phasea_e2e_operator")
  await expect(page.getByRole("heading", { name: "今天需要你决定" })).toBeVisible()

  const navigation = page.getByRole("navigation", { name: "主导航" })
  await expect(navigation.getByRole("link")).toHaveCount(5)
  for (const name of ["今天", "推广", "客户机会", "效果", "公司资料"]) {
    await expect(navigation.getByRole("link", { name, exact: true })).toBeVisible()
  }
  await expect(navigation.getByRole("link", { name: "知识库", exact: true })).toHaveCount(0)

  await completeBeginnerPromotion(page)
})

test("a beginner imports a public signal and reads the same evidence in an opportunity", async ({ page }) => {
  const sourceUrl = "https://example.com/task-11d/public-post"
  const originalText = "We need 200 replacement helical gears for a packaging machine."
  const companyName = "Task 11D Packaging GmbH"
  await login(page, "phasea_e2e_operator")

  await page.getByRole("link", { name: "客户机会", exact: true }).click()
  await page.getByRole("button", { name: "添加公开线索" }).first().click()
  await page.getByRole("tab", { name: "批量粘贴" }).click()
  await page.getByLabel("公开链接和原文").fill(`${sourceUrl}\t${originalText}`)
  const ingestionResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/v1/ingestion-batches"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "导入公开信号" }).click()
  expect((await ingestionResponse).status()).toBe(202)
  await expect(page.getByText("已完成公开信息导入。", { exact: true })).toBeVisible()

  const evidenceResponse = await expectOk(await page.request.get("/api/v1/source-evidences"))
  const evidencePage = await evidenceResponse.json() as EvidencePage
  const evidence = evidencePage.results.find((item) =>
    item.source_url === sourceUrl && item.original_text === originalText,
  )
  expect(evidence, "the production importer must persist the browser-submitted evidence").toBeDefined()

  const forgedScope = await page.request.post("/api/v1/lead-candidates", {
    data: {
      organization_id: "20000000-0000-4000-8000-000000000002",
      company_name: "Foreign organization override",
      evidence_ids: [evidence!.id],
    },
    headers: { "X-CSRFToken": await csrfToken(page) },
  })
  expect(forgedScope.status()).toBe(400)
  expect(JSON.stringify(await forgedScope.json())).not.toContain(originalText)
  await createCandidateFromEvidence(page, evidence!.id, companyName)

  await page.getByRole("button", { name: "关闭" }).click()
  await page.reload()
  const opportunity = page.locator("article").filter({ hasText: companyName })
  await expect(opportunity).toHaveCount(1)
  await opportunity.getByRole("button", { name: "查看依据" }).click()
  const detail = page.getByRole("dialog", { name: "机会依据" })
  await expect(detail.getByText(originalText, { exact: true })).toBeVisible()
  await expect(detail.getByRole("link", { name: "打开公开来源" })).toHaveAttribute("href", sourceUrl)
  await expect(detail.getByRole("button", { name: "重新分析" })).toBeVisible()
  await expect(detail.getByRole("button", { name: "确认机会" })).toHaveCount(0)
})

test("mobile navigation traps focus, closes on Escape, and keeps five ordinary entries", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page, "phasea_e2e_viewer")

  const menu = page.getByRole("button", { name: "打开导航" })
  await menu.click()
  const sidebar = page.getByTestId("app-sidebar")
  await expect(sidebar).not.toHaveAttribute("aria-hidden", "true")
  await expect(page.getByRole("link", { name: "SinofGear 首页" })).toBeFocused()
  await expect(sidebar.getByRole("navigation", { name: "主导航" }).getByRole("link")).toHaveCount(5)

  await page.keyboard.press("Shift+Tab")
  await expect(page.getByRole("button", { name: "打开高级功能" })).toBeFocused()
  await page.keyboard.press("Escape")
  await expect(sidebar).toHaveAttribute("aria-hidden", "true")
  await expect(page.getByRole("button", { name: "打开导航" })).toBeFocused()
})

test("advanced mode persists while read-only permissions keep mutation controls hidden", async ({ page }) => {
  await login(page, "phasea_e2e_viewer")
  await page.getByRole("link", { name: "客户机会", exact: true }).click()
  await expect(page.getByRole("button", { name: "添加公开线索" })).toHaveCount(0)
  const forbiddenImport = await page.request.post("/api/v1/ingestion-batches", {
    data: {
      source_type: "PASTE",
      idempotency_key: "task-11d-read-only-forbidden",
      payload: { text: "https://example.invalid/forbidden\tMust not be imported" },
    },
    headers: { "X-CSRFToken": await csrfToken(page) },
  })
  expect(forbiddenImport.status()).toBe(403)

  await page.getByRole("button", { name: "打开高级功能" }).click()
  const navigation = page.getByRole("navigation", { name: "主导航" })
  await expect(navigation.getByRole("link", { name: "知识库", exact: true })).toBeVisible()
  await expect(navigation.getByRole("link", { name: "平台账户", exact: true })).toBeVisible()
  await navigation.getByRole("link", { name: "知识库", exact: true }).click()
  await expect(page).toHaveURL(/\/knowledge$/)
  await page.reload()
  await expect(navigation.getByRole("link", { name: "知识库", exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "返回普通功能" })).toBeVisible()
  await expect.poll(() => page.evaluate(() => localStorage.getItem("sinofgear-navigation-mode-v1")))
    .toBe("advanced")

  await page.getByRole("button", { name: "返回普通功能" }).click()
  await page.reload()
  await expect(navigation.getByRole("link")).toHaveCount(5)
  await expect(page.getByRole("button", { name: "打开高级功能" })).toBeVisible()

  await logout(page)
  await login(page, "phasea_e2e_reviewer")
  await page.goto("/lead-radar")
  await expect(page.getByRole("button", { name: "添加公开线索" })).toHaveCount(0)
})
