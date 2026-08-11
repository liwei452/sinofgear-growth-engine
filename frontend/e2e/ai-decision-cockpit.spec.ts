import { expect, type APIResponse, type Page, test } from "@playwright/test"

const password = "PhaseA-E2E-Only!"

type SeedUser =
  | "phasea_e2e_admin"
  | "phasea_e2e_operator"
  | "phasea_e2e_reviewer"
  | "phasea_e2e_viewer"
  | "phaseb1_e2e_foreign"

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

async function createCandidateFixtureFromEvidence(
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

test("ordinary cockpit has exactly five entries and opens a decision on the correct page", async ({ page }) => {
  await login(page, "phasea_e2e_operator")
  await expect(page.getByRole("heading", { name: /今天(?:至少)?有 \d+ 件事需要你决定/ })).toBeVisible()

  const navigation = page.getByRole("navigation", { name: "主导航" })
  await expect(navigation.getByRole("link")).toHaveCount(5)
  for (const name of ["今天", "推广", "客户机会", "效果", "我的公司"]) {
    await expect(navigation.getByRole("link", { name, exact: true })).toBeVisible()
  }
  await expect(navigation.getByRole("link", { name: "知识库", exact: true })).toHaveCount(0)

  const decisions = page.getByRole("region", { name: "需要你决定" })
  await decisions.getByRole("button", { name: "查看并决定" }).first().click()
  await expect(page).toHaveURL(/\/lead-radar$/)
  await expect(page.getByRole("heading", { name: "客户机会", level: 1 })).toBeVisible()
})

test("ordinary results state a conclusion and My Company exposes a real missing-information task", async ({ page }) => {
  await login(page, "phasea_e2e_operator")
  await page.getByRole("link", { name: "效果", exact: true }).click()
  const conclusion = page.getByRole("region", { name: "AI 结论" })
  await expect(conclusion).toContainText(/点击|数据/)
  await expect(conclusion).not.toContainText("正在读取效果数据")

  await logout(page)
  await login(page, "phaseb1_e2e_foreign")
  await page.getByRole("link", { name: "我的公司", exact: true }).click()
  await expect(page.getByRole("heading", { name: "AI 对公司的了解", level: 1 })).toBeVisible()
  const gaps = page.getByRole("region", { name: "建议补充" })
  await expect(gaps).toContainText("补充产品")
  await expect(gaps.getByRole("link", { name: "去产品库补充产品" })).toHaveAttribute("href", "/products")
})

test("a beginner imports a public signal and reads the same evidence through a pre-Task12 fixture", async ({ page }) => {
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

  // Task 11D runs before parent Task 12 supplies import-to-candidate orchestration.
  // Use the public production API only to bridge that missing fixture relationship;
  // every user-facing evidence interaction below remains a browser UI action.
  await createCandidateFixtureFromEvidence(page, evidence!.id, companyName)

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
  const organization = page.getByText("Phase A E2E Only", { exact: true })
  await expect(organization).toBeVisible()
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
  await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible()
  await expect(organization).toBeVisible()
  await expect.poll(() => page.evaluate(() => localStorage.getItem("sinofgear-navigation-mode-v1")))
    .toBe("advanced")

  await page.getByRole("button", { name: "返回普通功能" }).click()
  await page.reload()
  await expect(navigation.getByRole("link")).toHaveCount(5)
  await expect(page.getByRole("button", { name: "打开高级功能" })).toBeVisible()
  await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible()
  await expect(organization).toBeVisible()

  await logout(page)
  await login(page, "phasea_e2e_reviewer")
  await page.goto("/lead-radar")
  await expect(page.getByRole("button", { name: "添加公开线索" })).toHaveCount(0)
})

for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 820, height: 1180 },
  { name: "mobile", width: 390, height: 844 },
] as const) {
  test(`ordinary shell and routes stay bounded at ${viewport.name} ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await login(page, "phasea_e2e_operator")

    const sidebar = page.getByTestId("app-sidebar")
    if (viewport.width <= 860) {
      await expect(sidebar).toHaveAttribute("aria-hidden", "true")
      await page.getByRole("button", { name: "打开导航" }).click()
      await expect(sidebar.getByRole("navigation", { name: "主导航" }).getByRole("link")).toHaveCount(5)
      await page.keyboard.press("Escape")
      await expect(sidebar).toHaveAttribute("aria-hidden", "true")
    } else {
      await expect(sidebar).not.toHaveAttribute("aria-hidden", "true")
      await expect(sidebar.getByRole("navigation", { name: "主导航" }).getByRole("link")).toHaveCount(5)
    }

    const routes = [
      { path: "/", heading: /今天(?:至少)?有 \d+ 件事需要你决定/, stableApi: "/api/v1/lead-candidates" },
      { path: "/promotion", heading: "你今天想推广什么？", stableApi: "/api/v1/products" },
      { path: "/lead-radar", heading: "客户机会", stableApi: "/api/v1/lead-candidates" },
      { path: "/analytics", heading: "效果", stableApi: "/api/v1/analytics/channel-summary" },
      { path: "/company-profile", heading: "AI 对公司的了解", stableApi: "/api/v1/products" },
    ]
    for (const route of routes) {
      const stableResponse = page.waitForResponse((response) =>
        new URL(response.url()).pathname.startsWith(route.stableApi)
          && response.request().method() === "GET",
      )
      await page.goto(route.path)
      expect((await stableResponse).ok(), `${route.path} stable query should succeed`).toBe(true)
      await expect(page.getByRole("heading", { name: route.heading, level: 1 })).toBeVisible()
      const bounds = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }))
      expect(bounds.scrollWidth, `${route.path} must not overflow horizontally`).toBeLessThanOrEqual(bounds.clientWidth + 1)
    }
  })
}
