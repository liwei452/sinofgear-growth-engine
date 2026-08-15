import { expect, type Page, test } from "@playwright/test"

async function login(page: Page) {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_operator")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function expectNoSeededDemo(page: Page) {
  await expect(page.getByText("PackTech GmbH")).toHaveCount(0)
  await expect(page.getByText("NordMotion AB")).toHaveCount(0)
  await expect(page.getByText(/Demo \/ Fake|Demo\/Fake/)).toHaveCount(0)
}

test("formal workspace stays clean and persists only explicitly recorded data", async ({ page }) => {
  await login(page)

  await page.getByRole("button", { name: "打开用户菜单" }).click()
  await page.getByRole("menuitem", { name: "设置" }).click()
  await expect(page).toHaveURL(/\/settings\?from=/)
  await expect(page.getByRole("heading", { name: "设置中心" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "高级管理" })).toHaveCount(0)
  await expect(page.getByText("真实 AI Provider 尚未配置")).toBeVisible()
  await page.getByRole("link", { name: "返回工作台" }).click()
  await expect(page).toHaveURL(/\/$/)

  await expect(page.getByRole("heading", { name: "今天发现的采购机会" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "今天还没有已验证的采购机会" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "还没有真实 AI 可见度监测记录" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "还没有人工回填的渠道结果" })).toBeVisible()
  await expectNoSeededDemo(page)

  await page.goto("/promotion")
  await expect(page.getByRole("heading", { name: "还没有可审核的渠道内容包" })).toBeVisible()
  await expect(page.getByRole("link", { name: "创建内容" })).toHaveAttribute("href", "/content-factory")
  await expect(page.getByRole("article", { name: "TikTok 内容包" })).toHaveCount(0)
  await expectNoSeededDemo(page)

  await page.goto("/opportunities")
  await expect(page.getByRole("heading", { name: "还没有可审核的客户机会" })).toBeVisible()
  await expect(page.getByText("当前没有已验证的活跃市场")).toBeVisible()
  await expect(page.getByRole("button", { name: "导入合法名单" })).toBeVisible()
  await expectNoSeededDemo(page)

  await page.getByLabel("国家或地区").fill("德国")
  await page.getByLabel("ISO 国家代码").fill("DEU")
  await page.getByRole("combobox", { name: "获客路径", exact: true }).selectOption("MIXED_ACQUISITION")
  const watchMarketResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/markets/watch"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "加入观察市场" }).click()
  expect([200, 201]).toContain((await watchMarketResponse).status())
  await expect(page.getByText("已加入观察市场，下一步导入真实候选公司。")).toBeVisible()
  await expect(page.getByText(/正在准备 德国 市场候选公司/)).toBeVisible()
  await page.reload()
  const germany = page.getByRole("article", { name: "德国 混合公开信号" })
  await expect(germany).toBeVisible()
  await expect(germany.getByText("待验证")).toBeVisible()
  await expect(germany.getByText("用户建立的观察市场，尚无样本证据。")).toBeVisible()
  await expect(page.getByText(/需求强度 25%/)).toHaveCount(0)
  await expectNoSeededDemo(page)

  await page.getByRole("button", { name: "导入公开线索" }).click()
  await page.getByLabel("公司名称").fill("Browser Import Drives Ltd")
  await page.getByLabel("国家或地区").fill("United Kingdom")
  await page.getByLabel("行业（选填）").fill("Packaging machinery")
  await page.getByLabel("来源名称").fill("User supplied public news")
  await page.getByLabel("公开 HTTPS 链接").fill("https://example.invalid/manual-import/evidence")
  await page.getByLabel("原始证据摘要").fill("The company announced a permitted public packaging line expansion.")
  const importResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/opportunity-imports/manual-url"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "保存为待核实机会" }).click()
  expect((await importResponse).status()).toBe(201)
  await expect(page.getByRole("heading", { name: "Browser Import Drives Ltd" })).toBeVisible()
  await page.reload()
  await expect(page.getByRole("heading", { name: "Browser Import Drives Ltd" })).toBeVisible()
  await expectNoSeededDemo(page)

  await page.goto("/analytics")
  await expect(page.getByText("尚未回填渠道结果")).toBeVisible()
  await expect(page.getByLabel("播放或访问")).toHaveValue("0")
  await expect(page.getByLabel("点击")).toHaveValue("0")
  await page.getByLabel("播放或访问").fill("7")
  await page.getByLabel("点击").fill("2")
  await page.getByLabel("数据来源说明").fill("Platform analytics checked by owner")
  await page.getByLabel("观察时间").fill("2026-08-15T09:30")
  const metricResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/metric-receipts"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "保存回填" }).click()
  expect((await metricResponse).status()).toBe(201)
  await page.reload()
  await expect(page.getByText("7 播放或访问")).toBeVisible()
  await expect(page.getByText("2 点击")).toBeVisible()
  await expectNoSeededDemo(page)

  await page.goto("/company")
  await expect(page.getByText("还没有已保存的公司事实")).toBeVisible()
  await expect(page.getByText("ISO 9001")).toHaveCount(0)
  await expect(page.getByText("DIN 6")).toHaveCount(0)
  await expect(page.getByRole("link", { name: "上传资料并提取事实" })).toHaveAttribute("href", "/assets")

  await page.goto("/reviews")
  await expect(page.getByRole("heading", { name: "审核中心" })).toBeVisible()
  await expect(page.getByText(/Demo \/ Fake|Demo\/Fake/)).toHaveCount(0)

  await page.goto("/publishing-calendar")
  await expect(page.getByRole("heading", { name: "发布日历" })).toBeVisible()
  await expect(page.getByText(/Demo \/ Fake|Demo\/Fake/)).toHaveCount(0)
})
