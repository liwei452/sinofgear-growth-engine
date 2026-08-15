import { expect, type Page, test } from "@playwright/test"

async function login(page: Page) {
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_operator")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

test("growth workspace persists follow-up, draft, approval, and manual metrics", async ({ page }) => {
  await login(page)

  const packTech = page.getByRole("article", { name: "PackTech GmbH 采购机会" })
  await expect(packTech).toBeVisible()
  await expect(packTech).toContainText("Public careers page")
  const followUpResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/follow-up") && response.request().method() === "POST",
  )
  await packTech.getByRole("button", { name: "加入跟进" }).click()
  expect((await followUpResponse).status()).toBe(201)
  await expect(packTech.getByRole("button", { name: "已加入跟进" })).toBeDisabled()

  const draftResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/draft") && response.request().method() === "POST",
  )
  await packTech.getByRole("button", { name: "生成联系草稿" }).click()
  expect((await draftResponse).status()).toBe(201)
  await expect(page.getByRole("dialog", { name: "联系草稿" })).toContainText("草稿不会自动发送")
  await expect(page.getByRole("dialog", { name: "联系草稿" })).toContainText("Hello PackTech GmbH team")
  await page.getByRole("button", { name: "关闭" }).click()

  await page.reload()
  await expect(page.getByRole("article", { name: "PackTech GmbH 采购机会" })
    .getByRole("button", { name: "已加入跟进" })).toBeDisabled()

  await page.goto("/promotion")
  await expect(page.getByText("30-second DIN 6 inspection proof")).toBeVisible()

  const linkedInPackage = page.getByRole("article", { name: "LinkedIn Company Page 内容包" })
  await expect(linkedInPackage).toContainText("How inspection evidence reduces assembly rework")
  const linkedInApprovalResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/approve") && response.request().method() === "POST",
  )
  await linkedInPackage.getByRole("button", { name: "批准 LinkedIn 内容包" }).click()
  expect((await linkedInApprovalResponse).status()).toBe(200)
  await expect(linkedInPackage.getByRole("button", { name: "下载 LinkedIn 发布包" })).toBeEnabled()
  await expect(page.getByRole("article", { name: "TikTok 内容包" })
    .getByRole("button", { name: "批准 TikTok 内容包" })).toBeEnabled()

  const linkedInExportResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/manual-export")
      && response.request().method() === "POST",
  )
  const linkedInDownload = page.waitForEvent("download")
  await linkedInPackage.getByRole("button", { name: "下载 LinkedIn 发布包" }).click()
  expect((await linkedInExportResponse).status()).toBe(200)
  expect((await linkedInDownload).suggestedFilename()).toBe("linkedin-manual-package.json")

  for (const channel of ["Facebook", "Instagram"]) {
    const channelApprovalResponse = page.waitForResponse(response =>
      new URL(response.url()).pathname.endsWith("/approve") && response.request().method() === "POST",
    )
    await page.getByRole("button", { name: `批准 ${channel} 内容包` }).click()
    expect((await channelApprovalResponse).status()).toBe(200)
  }

  const approvalResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/approve") && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "批准内容包" }).click()
  expect((await approvalResponse).status()).toBe(200)
  await expect(page.getByRole("status").filter({ hasText: "已批准，等待人工下载" })).toBeVisible()
  await page.reload()
  await expect(page.getByRole("button", { name: "已批准" })).toBeDisabled()
  const exportResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/manual-export")
      && response.request().method() === "POST",
  )
  const download = page.waitForEvent("download")
  await page.getByRole("button", { name: "下载发布包" }).click()
  expect((await exportResponse).status()).toBe(200)
  expect((await download).suggestedFilename()).toBe("tiktok-manual-package.json")
  await expect(page.getByText(/发布包已下载/)).toBeVisible()

  const publishBatchResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/publish-batches"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "一键发布到 4 个渠道" }).click()
  expect((await publishBatchResponse).status()).toBe(201)
  await expect(page.getByText("Demo / Fake 发布结果")).toBeVisible()
  await expect(page.getByText("3 个渠道发布成功，1 个渠道需要重试。")).toBeVisible()
  await expect(page.getByRole("link", { name: "查看 LinkedIn Demo 帖子" }))
    .toHaveAttribute("href", /example\.invalid\/demo-post\//)

  const retryPublishResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/retry-failed")
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "重试失败渠道" }).click()
  expect((await retryPublishResponse).status()).toBe(200)
  await expect(page.getByText("4 个渠道均已发布成功。")).toBeVisible()
  await page.reload()
  await expect(page.getByText("Demo / Fake 发布结果")).toBeVisible()
  await expect(page.getByText("4 个渠道均已发布成功。")).toBeVisible()

  await page.goto("/analytics")
  await page.getByLabel("播放或访问").fill("7000")
  await page.getByLabel("点击").fill("200")
  const metricResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/metric-receipts"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "保存回填" }).click()
  expect((await metricResponse).status()).toBe(201)
  await expect(page.getByRole("status")).toContainText("指标已保存")
  await page.reload()
  await expect(page.getByText("7,000 播放")).toBeVisible()
  await expect(page.getByText("200 点击")).toBeVisible()

  await page.goto("/opportunities")
  await expect(page.getByRole("heading", { name: "证据化客户机会" })).toBeVisible()
  await expect(page.getByText("3 家目标公司")).toBeVisible()
  await expect(page.getByRole("heading", { name: "PackTech GmbH" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "自动发现客户" })).toBeVisible()
  await expect(page.getByText("欧盟与英国官方采购数据", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("TED 欧盟采购公告")).toBeVisible()
  await expect(page.getByText("英国 Contracts Finder")).toBeVisible()
  await expect(page.getByText("Google Maps 官方企业发现")).toBeVisible()
  await expect(page.getByText("接入密钥后可用")).toBeVisible()
  const discoveryResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/discovery/run"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "立即查找" }).click()
  expect((await discoveryResponse).status()).toBe(200)
  await expect(page.getByRole("status")).toContainText("发现 1 条新采购信号")
  await expect(page.getByText("4 家目标公司")).toBeVisible()
  await page.getByRole("button", { name: /E2E Gear Procurement Authority/ }).click()
  await expect(page.getByRole("heading", { name: "E2E Gear Procurement Authority" })).toBeVisible()
  await expect(page.getByText("Demo / Fake").first()).toBeVisible()
  const duplicateDiscoveryResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/discovery/run"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "立即查找" }).click()
  expect((await duplicateDiscoveryResponse).status()).toBe(200)
  await expect(page.getByRole("status")).toContainText("发现 0 条新采购信号")
  await expect(page.getByText("4 家目标公司")).toBeVisible()
  await page.getByRole("button", { name: "导入公开线索" }).click()
  await page.getByLabel("公司名称").fill("Browser Import Drives Ltd")
  await page.getByLabel("国家或地区").fill("United Kingdom")
  await page.getByLabel("行业（选填）").fill("Packaging machinery")
  await page.getByLabel("来源名称").fill("User supplied public news")
  await page.getByLabel("公开 HTTPS 链接").fill("https://example.invalid/manual-import/evidence")
  await page.getByLabel("原始证据摘要").fill("The company announced a permitted public packaging line expansion.")
  const manualImportResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/opportunity-imports/manual-url"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "保存为待核实机会" }).click()
  expect((await manualImportResponse).status()).toBe(201)
  await expect(page.getByRole("heading", { name: "Browser Import Drives Ltd" })).toBeVisible()
  await expect(page.getByText("许可 / 用户提供来源")).toBeVisible()
  await expect(page.getByText("继续观察 · 50")).toHaveCount(2)
  await page.getByRole("button", { name: "查看证据" }).click()
  await expect(page.getByText("人工导入网页")).toBeVisible()
  await expect(page.getByText("manual-opportunity-v1")).toBeVisible()
  await expect(page.getByText("公司身份仍需人工核实")).toBeVisible()
  await expect(page.getByText("采购范围与时间仍需人工确认")).toBeVisible()
  await expect(page.getByRole("link", { name: "打开原始来源" }))
    .toHaveAttribute("href", "https://example.invalid/manual-import/evidence")

  const csrfToken = (await page.context().cookies()).find(cookie => cookie.name === "csrftoken")?.value
  expect(csrfToken).toBeTruthy()
  const duplicateResponse = await page.context().request.post(
    `${new URL(page.url()).origin}/api/v1/growth/opportunity-imports/manual-url`,
    {
      headers: { "X-CSRFToken": csrfToken ?? "" },
      data: {
        company_name: "Duplicate name must not replace the company",
        country: "United Kingdom",
        industry: "Packaging machinery",
        source_label: "User supplied public news",
        source_url: "https://example.invalid/manual-import/evidence",
        evidence_text: "The company announced a permitted public packaging line expansion.",
      },
    },
  )
  expect(duplicateResponse.status()).toBe(200)
  expect((await duplicateResponse.json()).created).toBe(false)

  await page.reload()
  await expect(page.getByText("5 家目标公司")).toBeVisible()
  await page.getByRole("button", { name: /Browser Import Drives Ltd/ }).click()
  await expect(page.getByRole("heading", { name: "Browser Import Drives Ltd" })).toBeVisible()
  await page.getByRole("button", { name: /PackTech GmbH/ }).click()
  await expect(page.getByRole("heading", { name: "PackTech GmbH" })).toBeVisible()
  await expect(page.getByRole("button", { name: "已加入跟进" })).toBeDisabled()
  await page.getByRole("button", { name: /NordMotion AB/ }).click()
  await expect(page.getByRole("heading", { name: "NordMotion AB" })).toBeVisible()
  await expect(page.getByRole("button", { name: "加入跟进" })).toBeEnabled()
  await page.getByRole("button", { name: /PackTech GmbH/ }).click()
  await expect(page.getByRole("heading", { name: "PackTech GmbH" })).toBeVisible()
  await page.getByRole("button", { name: "查看证据" }).click()
  await expect(page.getByRole("heading", { name: "评分依据" })).toBeVisible()
  await expect(page.getByText("证据覆盖 18")).toBeVisible()
  await expect(page.getByText("本地演示样本")).toBeVisible()
  await expect(page.getByText("采购范围与时间仍需人工确认")).toBeVisible()
  await expect(page.getByRole("link", { name: "打开原始来源" }))
    .toHaveAttribute("href", "https://example.invalid/demo-evidence/1001")
  await expect(page.getByRole("heading", { name: "跟进记录" })).toBeVisible()
  await expect(page.getByText("从未发送")).toBeVisible()
  const opportunityDraftResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/draft") && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "生成联系草稿" }).click()
  expect((await opportunityDraftResponse).status()).toBe(201)
  await expect(page.getByText(/Hello PackTech GmbH team/)).toBeVisible()
  await page.reload()
  await expect(page.getByRole("button", { name: "已加入跟进" })).toBeDisabled()
  await expect(page.getByRole("heading", { name: "跟进记录" })).toBeVisible()
  await expect(page.getByText("从未发送")).toBeVisible()

  await page.goto("/company")
  await expect(page.getByRole("heading", { name: "我的公司" })).toBeVisible()
  const verifyResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.includes("/growth/company-facts/")
      && new URL(response.url()).pathname.endsWith("/verify")
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "确认 DIN 6" }).click()
  expect((await verifyResponse).status()).toBe(200)
  await page.reload()
  const dinFactRow = page.getByRole("row").filter({ hasText: "DIN 6" })
  await expect(dinFactRow).toContainText("已确认")
  await expect(dinFactRow.getByRole("button", { name: "确认 DIN 6" })).toHaveCount(0)
})
