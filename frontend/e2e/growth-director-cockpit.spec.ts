import { expect, type Page, test } from "@playwright/test"

const password = "PhaseA-E2E-Only!"

async function login(page: Page, username: "phasea_e2e_reviewer" | "phasea_e2e_viewer"): Promise<void> {
  await page.goto("/login")
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill(password)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

test("ordinary mode keeps exactly five beginner entries in the approved order", async ({ page }) => {
  await login(page, "phasea_e2e_reviewer")
  const links = page.getByRole("navigation", { name: "主导航" }).getByRole("link")
  await expect(links).toHaveCount(5)
  await expect(links.allTextContents()).resolves.toEqual([
    "今天", "产品资料", "推广", "客户机会", "效果",
  ])
})

test("cockpit exposes loading, recoverable error, truthful empty and real success states", async ({ page }) => {
  await page.route("**/api/v1/director/cockpit", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300))
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ decisions: [], active_work: [], recent_outcomes: [], generated_at: new Date().toISOString() }),
    })
  })
  await login(page, "phasea_e2e_reviewer")
  await expect(page.getByRole("status")).toContainText("正在整理")
  await expect(page.getByRole("heading", { name: "今天没有需要你决定的事" })).toBeVisible()
  await expect(page.getByText("当前没有等待你决定的事项。", { exact: false })).toBeVisible()
  await expect(page.getByText("还没有可汇报的真实结果。", { exact: false })).toBeVisible()

  await page.unroute("**/api/v1/director/cockpit")
  await page.route("**/api/v1/director/cockpit", (route) => route.fulfill({
    status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporary" }),
  }))
  await page.reload()
  await expect(page.getByRole("alert").filter({ hasText: "今天的工作暂时没有加载成功" })).toBeVisible()
  await expect(page.getByRole("button", { name: "重新加载" })).toBeVisible()

  await page.unroute("**/api/v1/director/cockpit")
  await page.reload()
  await expect(page.getByRole("heading", { name: /今天有 3 件事需要你决定/ })).toBeVisible()
  await expect(page.getByText("批准德国市场推广方案", { exact: true })).toBeVisible()
  await expect(page.locator("body")).not.toContainText(/PROMOTION_PLAN|director\.read|PromptVersion|AIRun|provider_error/)
})

test("reviewer decisions are real, reasons are required, and dialog focus returns", async ({ page }) => {
  await login(page, "phasea_e2e_reviewer")

  const approveCard = page.locator("article").filter({ hasText: "批准德国市场推广方案" })
  page.once("dialog", (dialog) => dialog.accept())
  await approveCard.getByRole("button", { name: "批准" }).click()
  await expect(page.getByText("批准德国市场推广方案", { exact: true })).toHaveCount(0)

  const adjustmentCard = page.locator("article").filter({ hasText: "调整斜齿轮内容方案" })
  const adjustmentButton = adjustmentCard.getByRole("button", { name: "要求调整" })
  await adjustmentButton.click()
  const adjustmentDialog = page.getByRole("dialog", { name: "请说明需要怎样调整" })
  await expect(adjustmentDialog.getByRole("heading")).toBeFocused()
  await adjustmentDialog.getByRole("button", { name: "提交" }).click()
  await expect(adjustmentDialog.getByRole("alert")).toContainText("请用中文填写原因")
  await adjustmentDialog.getByRole("button", { name: "取消" }).click()
  await expect(adjustmentButton).toBeFocused()
  await adjustmentButton.click()
  const reopenedAdjustmentDialog = page.getByRole("dialog", { name: "请说明需要怎样调整" })
  await reopenedAdjustmentDialog.getByLabel("原因").fill("请补充可核实的精度与交期依据。")
  await reopenedAdjustmentDialog.getByRole("button", { name: "提交" }).click()
  await expect(page.getByText("调整斜齿轮内容方案", { exact: true })).toHaveCount(0)

  const rejectCard = page.locator("article").filter({ hasText: "确认未经核实的成本建议" })
  await rejectCard.getByRole("button", { name: "拒绝" }).click()
  const rejectDialog = page.getByRole("dialog", { name: "请说明拒绝原因" })
  await rejectDialog.getByLabel("原因").fill("成本数据尚未经过财务核实，暂不采用。")
  await rejectDialog.getByRole("button", { name: "提交" }).click()
  await expect(page.getByText("确认未经核实的成本建议", { exact: true })).toHaveCount(0)
})

test("read-only users see evidence but no decision controls", async ({ page }) => {
  await login(page, "phasea_e2e_viewer")
  await expect(page.getByText("复核包装机械客户机会", { exact: true })).toBeVisible()
  const card = page.locator("article").filter({ hasText: "复核包装机械客户机会" })
  await expect(card.getByRole("button")).toHaveCount(0)
})

test("Agent Center reports five honest states without fake automation", async ({ page }) => {
  await login(page, "phasea_e2e_reviewer")
  await page.getByRole("button", { name: "打开高级功能" }).click()
  await page.getByRole("link", { name: "AI Agent 中心" }).click()
  await expect(page).toHaveURL(/\/agent-center$/)
  const region = page.getByRole("region", { name: "AI Agent 准备状态" })
  for (const agent of ["Growth Director", "Content Agent", "Lead Agent", "AIEO Agent", "Analytics Agent"]) {
    await expect(region.getByRole("heading", { name: agent })).toBeVisible()
  }
  await expect(region.locator("article")).toHaveCount(5)
  await expect(region.getByText("设计已确认，后续批次接入", { exact: true })).toBeVisible()
  await expect(region).not.toContainText(/自动调度已开启|正在自动抓取|自动发布已开启/)
})

test("mobile cockpit stays bounded at 390x844 and dialog traps and restores focus", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page, "phasea_e2e_viewer")
  const bounds = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(bounds.scrollWidth).toBeLessThanOrEqual(bounds.clientWidth + 1)
  await page.getByRole("button", { name: "打开导航" }).click()
  await expect(page.getByRole("navigation", { name: "主导航" }).getByRole("link")).toHaveCount(5)
  await page.keyboard.press("Escape")
  await expect(page.getByRole("button", { name: "打开导航" })).toBeFocused()
})
