import { expect, type Page, test } from "@playwright/test"

async function login(page: Page) {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_operator")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function expectResponsive(page: Page, width: number) {
  await page.setViewportSize({ width, height: 900 })
  await expect(page.getByRole("heading", { name: "Agent 工作台" })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}

test("operator starts a truthful automation task and discloses technical details on demand", async ({ page }) => {
  const run = {
    id: "fixture-automation-run",
    goal: "准备内容策略任务",
    agent_type: "content_strategy",
    execution_mode: "AUTOMATION",
    planner_provider: "",
    planner_model: "",
    status: "COMPLETED",
    terminal_reason: "complete",
    created_at: "2026-08-18T08:00:00Z",
    updated_at: "2026-08-18T08:01:00Z",
    steps: [{
      index: 1,
      tool_name: "analyze_content_opportunities",
      args: { source: "fixture-owned" },
      outcome: "succeeded",
      output: { count: 1 },
      error: null,
      reasoning: "Only stored fixture evidence was analyzed.",
    }],
    pending_approval: null,
  }
  let started = false
  await login(page)
  await page.route("**/api/v1/ai/provider-status", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ mode: "FAKE_OFFLINE", provider_label: "Fake / 离线演示", model: "fake-v1", configured: false, real_requests_enabled: false }),
  }))
  await page.route("**/api/v1/growth/agent/runs/start", async route => {
    started = true
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "COMPLETED", terminal_reason: "complete", pending_approval_token: null }) })
  })
  await page.route("**/api/v1/growth/agent/runs", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(started ? [run] : []),
  }))

  await page.goto("/agent-workspace")
  await expect(page.getByRole("heading", { name: "Agent 工作台" })).toBeVisible()
  await page.getByRole("button", { name: "启动内容策略" }).first().click()
  await page.getByRole("button", { name: "确认启动" }).click()
  const timeline = page.getByRole("article", { name: "准备内容策略任务" })
  await expect(timeline).toContainText("自动化流程")
  await expect(timeline.getByText("fixture-owned")).toHaveCount(0)
  await timeline.getByText("技术记录").click()
  await expect(timeline.getByText(/fixture-owned/)).toBeVisible()

  for (const width of [1440, 1024, 390]) await expectResponsive(page, width)
})
