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
  const offenders = await page.evaluate(() => {
    const viewport = document.documentElement.clientWidth
    const isInsideHorizontalScroller = (element: HTMLElement) => {
      let ancestor = element.parentElement
      while (ancestor && ancestor !== document.body) {
        const style = window.getComputedStyle(ancestor)
        if (ancestor.scrollWidth > ancestor.clientWidth && /auto|scroll/.test(style.overflowX)) return true
        ancestor = ancestor.parentElement
      }
      return false
    }
    return [...document.querySelectorAll<HTMLElement>("main *")]
      .filter((element) => {
        const style = window.getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return style.display !== "none"
          && style.visibility !== "hidden"
          && !element.closest("[aria-hidden='true'], [inert]")
          && !isInsideHorizontalScroller(element)
          && (rect.left < -1 || rect.right > viewport + 1)
      })
      .map((element) => ({ tag: element.tagName, className: element.className, rect: element.getBoundingClientRect().toJSON() }))
  })
  expect(offenders).toEqual([])
}

async function expectMinimumTarget(locator: ReturnType<Page["locator"]>) {
  const box = await locator.boundingBox()
  expect(box, "expected a visible interactive target").not.toBeNull()
  expect(box!.width).toBeGreaterThanOrEqual(44)
  expect(box!.height).toBeGreaterThanOrEqual(44)
}

test.describe("business outcome navigation", () => {
  test("desktop activates each primary destination and keeps every destination within its visible width", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await login(page)

    const navigation = page.getByRole("navigation", { name: "主导航" })
    await expect(navigation.getByRole("link")).toHaveCount(5)
    for (const destination of ["/promotion", "/opportunities", "/content-factory", "/analytics", "/"]) {
      const link = navigation.locator(`a[href="${destination}"]`)
      await expect(link).toBeVisible()
      await link.click()
      await expect(page).toHaveURL(destination === "/" ? /\/$/ : new RegExp(`${destination}$`))
      await expect(page.locator("main h1")).toBeVisible()
      await expect(page.getByTestId("app-sidebar")
        .locator(`nav[aria-label="主导航"] a[href="${destination}"]`)).toHaveAttribute("aria-current", "page")
      await expect(page.locator("main")).toHaveCount(1)
      await expectNoHorizontalOverflow(page)
    }
    await expectMinimumTarget(navigation.locator('a[href="/opportunities"]'))
  })

  test("mobile drawer traps focus, restores it on Escape, and activates each primary destination", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await login(page)

    const trigger = page.getByRole("button", { name: "打开导航" })
    await trigger.click()
    await expect(page.getByTestId("app-sidebar")).toHaveClass(/app-sidebar-open/)
    await page.keyboard.press("Shift+Tab")
    await expect(page.getByTestId("app-sidebar").getByRole("link").last()).toBeFocused()
    await page.keyboard.press("Tab")
    await expect(page.getByTestId("app-sidebar").getByRole("link").first()).toBeFocused()
    await page.keyboard.press("Escape")
    await expect(page.getByTestId("app-sidebar")).not.toHaveClass(/app-sidebar-open/)
    await expect(trigger).toBeFocused()
    await expectMinimumTarget(trigger)
    for (const destination of ["/promotion", "/opportunities", "/content-factory", "/analytics", "/"]) {
      await trigger.click()
      const link = page.getByTestId("app-sidebar")
        .getByRole("navigation", { name: "主导航" })
        .locator(`a[href="${destination}"]`)
      await link.click()
      await expect(page).toHaveURL(destination === "/" ? /\/$/ : new RegExp(`${destination}$`))
      await expect(page.locator("main h1")).toBeVisible()
      await expect(page.getByTestId("app-sidebar")
        .locator(`nav[aria-label="主导航"] a[href="${destination}"]`)).toHaveAttribute("aria-current", "page")
      await expect(page.locator("main")).toHaveCount(1)
      await expectNoHorizontalOverflow(page)
      if (destination === "/opportunities") {
        await expectMinimumTarget(page.getByRole("searchbox", { name: "搜索客户机会" }))
        await expectMinimumTarget(page.getByLabel("阶段"))
      }
    }
  })

  test("legacy mission deep links remain authenticated and reachable", async ({ page }) => {
    await login(page)
    await page.goto("/missions/00000000-0000-4000-8000-000000000999?view=customer")
    await expect(page).toHaveURL(/\/missions\/00000000-0000-4000-8000-000000000999\?view=customer/)
    await expect(page.getByRole("heading", { name: "增长任务" })).toBeVisible()
    await expect(page.locator("main")).toHaveCount(1)
  })

  test("submission-unknown content has stable tab semantics and never exposes an ordinary retry", async ({ page }) => {
    await login(page)
    const blockedSideEffects: string[] = []
    const externalRequests: string[] = []
    page.on("request", (request) => {
      const url = new URL(request.url())
      if (url.origin !== new URL(page.url()).origin) externalRequests.push(url.origin)
    })
    await page.route("**/api/v1/master-contents?*", route => route.fulfill({ json: { next: null, previous: null, results: [] } }))
    await page.route("**/api/v1/platform-contents?*", route => route.fulfill({ json: {
      next: null,
      previous: null,
      results: [{
        id: "unknown-content", master_content_id: "master-1", master_version: 1, platform_id: "linkedin",
        lineage_id: "lineage-1", previous_version_id: null, version: 1, status: "APPROVED", is_current_head: true,
        publish_package_id: null, created_by_id: 1, created_at: "2026-08-20T08:00:00Z", updated_at: "2026-08-20T08:00:00Z",
        provenance: {}, payload: { schema_version: 2, platform_code: "LINKEDIN", language: "en", title: "Unknown submission", body: "", cta: "", landing_page_url: "https://example.invalid", hashtags: [], evidence_fact_ids: [] },
      }],
    } }))
    await page.route("**/api/v1/publish-tasks?*", route => route.fulfill({ json: {
      next: null, previous: null,
      results: [{ id: "unknown-task", platform_content_id: "unknown-content", social_account_id: "account-unknown", connector_code: "BUFFER", status: "SUBMISSION_UNKNOWN", provider_submission_id: "provider-pending" }],
    } }))
    await page.route(/\/api\/v1\/(?:publish-tasks\/[^/]+\/run|growth\/publish-batches|growth\/missions\/[^/]+\/publish|.*outreach.*send|.*authorize)/, route => {
      blockedSideEffects.push(new URL(route.request().url()).pathname)
      return route.abort("blockedbyclient")
    })

    await page.getByRole("navigation", { name: "主导航" }).locator('a[href="/content-factory"]').click()
    const stages = ["PREPARE", "AI_DRAFT", "REVIEW", "SCHEDULED", "SUBMITTED", "PUBLISHED", "NEEDS_ATTENTION"]
    for (const stage of stages) {
      const tab = page.locator(`#publishing-tab-${stage}`)
      await expect(tab).toHaveAttribute("aria-controls", `publishing-panel-${stage}`)
      await expect(page.locator(`#publishing-panel-${stage}`)).toHaveCount(1)
    }
    const reviewTab = page.locator("#publishing-tab-REVIEW")
    await reviewTab.focus()
    await page.keyboard.press("ArrowRight")
    await expect(page.locator("#publishing-tab-SCHEDULED")).toBeFocused()
    await page.keyboard.press("End")
    await expect(page.locator("#publishing-tab-NEEDS_ATTENTION")).toBeFocused()
    await page.keyboard.press("Home")
    await expect(page.locator("#publishing-tab-PREPARE")).toBeFocused()
    await page.locator("#publishing-tab-SUBMITTED").click()
    await expect(page.locator("#publishing-panel-SUBMITTED")).toBeVisible()
    for (const stage of stages.filter(stage => stage !== "SUBMITTED")) {
      await expect(page.locator(`#publishing-panel-${stage}`)).not.toBeVisible()
    }
    await expect(page.getByText("平台提交状态待确认；请勿重复发布")).toBeVisible()
    await expect(page.getByText("已发布", { exact: true })).toHaveCount(0)
    await expect(page.getByRole("button", { name: /重试|运行发布|再次发布/ })).toHaveCount(0)
    await page.locator("#publishing-tab-NEEDS_ATTENTION").click()
    await expect(page.locator("#publishing-panel-NEEDS_ATTENTION")).toBeVisible()
    for (const stage of stages.filter(stage => stage !== "NEEDS_ATTENTION")) {
      await expect(page.locator(`#publishing-panel-${stage}`)).not.toBeVisible()
    }
    expect(blockedSideEffects).toEqual([])
    expect(externalRequests).toEqual([])
  })

  test("promotion read failure stays explicitly unknown instead of becoming completed", async ({ page }) => {
    await login(page)
    await page.route("**/api/v1/growth/company-facts", route => route.fulfill({ status: 503, json: { detail: "temporarily unavailable" } }))
    await page.getByRole("navigation", { name: "主导航" }).locator('a[href="/promotion"]').click()
    await expect(page.getByRole("heading", { name: "推广状态暂时无法读取" })).toBeVisible()
    await expect(page.getByText(/未读取到的数据不会被标记为已完成/)).toBeVisible()
    await expect(page.getByText("推广准备记录已齐备", { exact: true })).toHaveCount(0)
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

  test("a market recommendation leads to candidate import, human review, enrichment, follow-up, and an unsent contact draft", async ({ page }) => {
    await login(page)
    await page.getByRole("navigation", { name: "主导航" }).locator('a[href="/promotion"]').click()
    await expect(page.getByRole("heading", { name: "市场推荐" })).toBeVisible()
    await page.getByRole("link", { name: "查看候选并导入名单" }).first().click()
    await expect(page).toHaveURL(/\/opportunities\?market=/)
    await expect(page.getByText(/市场推荐 .* 已带入；请导入有权使用的候选名单并进行人工审核/)).toBeVisible()
    const company = "Orbit Drive Components"
    const requests: string[] = []
    const blockedSideEffects: string[] = []
    page.on("request", request => requests.push(new URL(request.url()).pathname))
    await page.route(/\/api\/v1\/(?:publish-tasks\/[^/]+\/run|growth\/publish-batches|growth\/missions\/[^/]+\/publish|.*outreach.*send|.*authorize)/, route => {
      blockedSideEffects.push(new URL(route.request().url()).pathname)
      return route.abort("blockedbyclient")
    })

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
    expect(blockedSideEffects).toEqual([])
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
