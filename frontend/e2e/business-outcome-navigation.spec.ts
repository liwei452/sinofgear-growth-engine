import { expect, type Page, test } from "@playwright/test"
import { join } from "node:path"

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

  test("mobile Help and Settings links meet the 44px minimum target", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await login(page)

    await page.goto("/help")
    for (const destination of ["/", "/promotion", "/opportunities", "/content-factory", "/analytics"]) {
      await expectMinimumTarget(page.locator(`main a[href="${destination}"]`))
    }

    await page.goto("/settings")
    await expectMinimumTarget(page.locator("main .settings-card nav a").first())
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
    const groups = ["PENDING", "PLANNED", "COMPLETED"]
    for (const group of groups) {
      const tab = page.locator(`#publishing-tab-${group}`)
      await expect(tab).toHaveAttribute("aria-controls", `publishing-panel-${group}`)
      await expect(page.locator(`#publishing-panel-${group}`)).toHaveCount(1)
    }
    const pendingTab = page.locator("#publishing-tab-PENDING")
    await pendingTab.focus()
    await page.keyboard.press("ArrowRight")
    await expect(page.locator("#publishing-tab-PLANNED")).toBeFocused()
    await page.keyboard.press("End")
    await expect(page.locator("#publishing-tab-COMPLETED")).toBeFocused()
    await page.keyboard.press("Home")
    await expect(page.locator("#publishing-tab-PENDING")).toBeFocused()
    await page.locator("#publishing-tab-PLANNED").click()
    await page.getByRole("button", { name: "已提交 1" }).click()
    await expect(page.locator("#publishing-panel-PLANNED")).toBeVisible()
    for (const group of groups.filter(group => group !== "PLANNED")) {
      await expect(page.locator(`#publishing-panel-${group}`)).not.toBeVisible()
    }
    await expect(page.getByText("平台提交状态待确认；请勿重复发布")).toBeVisible()
    await expect(page.getByText("已发布", { exact: true })).toHaveCount(0)
    await expect(page.getByRole("button", { name: /重试|运行发布|再次发布/ })).toHaveCount(0)
    expect(blockedSideEffects).toEqual([])
    expect(externalRequests).toEqual([])
  })

  test("360px content workflow shows all three primary stages without horizontal guessing", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 800 })
    await login(page)
    await page.goto("/content-factory")

    const tabs = page.getByRole("tab")
    await expect(tabs).toHaveCount(3)
    for (const label of [/^待处理/, /^计划中/, /^已完成/]) {
      const tab = page.getByRole("tab", { name: label })
      await expect(tab).toBeVisible()
      const box = await tab.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(360)
    }
    const dimensions = await page.getByRole("tablist", { name: "内容发布主阶段" }).evaluate(element => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }))
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
    await expectNoHorizontalOverflow(page)
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

  test("a manually imported candidate list is held at the licence-confirmation gate", async ({ page }) => {
    await login(page)
    await page.goto("/opportunities")
    await page.getByRole("button", { name: "导入候选名单" }).click()
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
    await expect(page.getByText("候选名单的使用许可尚待人工确认，暂不能加入跟进或生成联系草稿。", { exact: true })).toBeVisible()
    await expect(page.getByRole("button", { name: "准备资料补全" })).toBeVisible()
    await expect(page.getByRole("button", { name: "加入跟进" })).toHaveCount(0)
    await expect(page.getByRole("button", { name: "生成联系草稿" })).toHaveCount(0)
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

const visualAuditDirectory = process.env.SINO_VISUAL_AUDIT_DIR

if (visualAuditDirectory) {
  test("visual audit saves the four core pages at desktop and mobile sizes", async ({ page }) => {
    await page.route("**/api/v1/auth/me", async (route) => {
      const upstream = await route.fetch()
      const body = await upstream.json()
      await route.fulfill({
        response: upstream,
        json: {
          ...body,
          user: { ...body.user, username: "演示管理员" },
          organization: { ...body.organization, name: "星沣传动（演示）" },
        },
      })
    })
    await login(page)
    const pages = [
      { name: "today", path: "/", heading: "今日" },
      { name: "opportunities", path: "/opportunities", heading: "客户机会" },
      { name: "content-publishing", path: "/content-factory", heading: "内容与发布" },
      { name: "results", path: "/analytics", heading: "效果" },
    ]
    const viewports = [
      { name: "desktop", width: 1440, height: 900 },
      { name: "mobile", width: 390, height: 844 },
    ]

    for (const viewport of viewports) {
      await page.setViewportSize(viewport)
      for (const auditPage of pages) {
        await page.goto(auditPage.path)
        await expect(page.getByRole("heading", { name: auditPage.heading, level: 1 })).toBeVisible()
        await expect(page.locator("main")).toHaveCount(1)
        await expect(page.locator("main").getByText(/正在读取/)).toHaveCount(0)
        await page.evaluate(() => window.scrollTo(0, 0))
        await expect(page.locator("header.topbar")).toBeVisible()
        await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)
        await expectNoHorizontalOverflow(page)
        await page.screenshot({
          path: join(visualAuditDirectory, `${viewport.name}-${auditPage.name}.png`),
          fullPage: false,
        })
      }
    }
  })
}
