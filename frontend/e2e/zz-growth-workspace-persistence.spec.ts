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
  await expect(page.getByRole("heading", { name: "推广计划与内容包" })).toBeVisible()

  const linkedInPackage = page.getByRole("article", { name: "LinkedIn Company Page 内容包" })
  await expect(linkedInPackage).toContainText("手工发布包")
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
  await expect(page.locator(".opportunity-detail").getByRole("heading", { name: "PackTech GmbH" })).toBeVisible()
  const reactivation = page.getByRole("region", { name: "沉睡线索重新激活" })
  await reactivation.getByLabel("已有关系账户").selectOption({ label: "PackTech GmbH" })
  await reactivation.getByLabel("关系来源").selectOption("PAST_INQUIRY")
  await reactivation.getByLabel("最后互动时间").fill("2026-04-15T16:00")
  await reactivation.getByLabel("历史互动摘要").fill("2025 trade fair gear sample discussion; no order or current intent was claimed.")
  await reactivation.getByRole("button", { name: "加入重新激活" }).click()
  await expect(reactivation.getByRole("alert")).toContainText("确认名单使用权")
  await reactivation.getByRole("checkbox", { name: "确认这是已有关系或合法自有名单" }).check()
  const reactivationSelectResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/reactivations"
      && response.request().method() === "POST",
  )
  await reactivation.getByRole("button", { name: "加入重新激活" }).click()
  expect((await reactivationSelectResponse).status()).toBe(201)
  const packTechReactivation = reactivation.getByRole("article", { name: "PackTech GmbH 重新激活" })
  await expect(packTechReactivation).toContainText("战略账户")
  await expect(packTechReactivation).toContainText("Demo / Fake")
  const reactivationDraftResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/draft")
      && new URL(response.url()).pathname.includes("/api/v1/growth/reactivations/")
      && response.request().method() === "POST",
  )
  await packTechReactivation.getByRole("button", { name: "生成待审草稿" }).click()
  expect((await reactivationDraftResponse).status()).toBe(201)
  await expect(packTechReactivation).toContainText("待审草稿")
  const reactivationApproveResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/approve")
      && new URL(response.url()).pathname.includes("/api/v1/growth/reactivations/")
      && response.request().method() === "POST",
  )
  await packTechReactivation.getByRole("button", { name: "人工批准草稿" }).click()
  expect((await reactivationApproveResponse).status()).toBe(200)
  await expect(packTechReactivation).toContainText("已批准，未发送")
  await page.reload()
  await expect(page.getByRole("article", { name: "PackTech GmbH 重新激活" })).toContainText("已批准，未发送")
  const refreshedReactivation = page.getByRole("region", { name: "沉睡线索重新激活" })
  await refreshedReactivation.getByLabel("已有关系账户").selectOption({ label: "NordMotion AB" })
  await refreshedReactivation.getByLabel("关系来源").selectOption("OWNED_CRM")
  await refreshedReactivation.getByLabel("最后互动时间").fill("2026-01-15T16:00")
  await refreshedReactivation.getByLabel("历史互动摘要").fill("Historical conversation recorded in the factory-owned CRM.")
  await refreshedReactivation.getByRole("checkbox", { name: "确认这是已有关系或合法自有名单" }).check()
  const observationSelectResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/reactivations"
      && response.request().method() === "POST",
  )
  await refreshedReactivation.getByRole("button", { name: "加入重新激活" }).click()
  expect((await observationSelectResponse).status()).toBe(201)
  const observationReactivation = refreshedReactivation.getByRole("article", { name: "NordMotion AB 重新激活" })
  await expect(observationReactivation).toContainText("观察账户证据不足，只建议补全")
  await expect(observationReactivation.getByRole("button", { name: "生成待审草稿" })).toHaveCount(0)

  await page.goto("/analytics")
  await page.reload()
  const attribution = page.getByRole("region", { name: "账户获客漏斗" })
  await expect(attribution).toBeVisible()
  const packTechAttribution = attribution.getByRole("article", { name: "PackTech GmbH 归因记录" })
  await expect(packTechAttribution).toContainText("人工批准")
  await expect(packTechAttribution).toContainText("已批准，尚未发送")
  const nordAttribution = attribution.getByRole("article", { name: "NordMotion AB 归因记录" })
  await expect(nordAttribution).toContainText("补全证据")
  await expect(nordAttribution).toContainText("证据不足，不生成触达草稿")
  await expect(attribution.getByRole("button", { name: /人工发送/ })).toContainText("尚未发生")
  await expect(attribution.getByRole("button", { name: /^回复/ })).toContainText("尚未发生")
  await expect(attribution.getByRole("button", { name: /有效需求/ })).toContainText("尚未发生")
  await expect(attribution.getByText("积极回复率 无数据")).toBeVisible()
  await expect(attribution.getByText("需求率 无数据")).toBeVisible()
  await attribution.getByRole("button", { name: /人工批准/ }).click()
  await expect(packTechAttribution).toBeVisible()
  await expect(attribution.getByRole("article", { name: "NordMotion AB 归因记录" })).toHaveCount(0)

  await page.goto("/opportunities")
  await expect(page.getByRole("heading", { name: "自动发现客户" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "双市场获客验证" })).toBeVisible()
  await expect(page.getByRole("article", { name: "印度尼西亚 强海关数据路线" })).toContainText("待采样")
  await expect(page.getByRole("article", { name: "南非 混合信号路线" })).toContainText("待采样")
  await expect(page.getByText("市场雷达")).toBeVisible()
  await expect(page.getByText("智利 · 下一优先")).toBeVisible()
  await expect(page.getByText("印度 · 条件观察")).toBeVisible()
  await page.getByRole("searchbox", { name: "搜索国家" }).fill("美国")
  const usaMarket = page.getByRole("article", { name: "美国 海关强数据路线" })
  await expect(usaMarket).toContainText("Demo / 研究配置")
  await expect(usaMarket).toContainText("工业设备、包装机械、矿业与能源")
  await expect(usaMarket).toContainText("研究配置")
  const watchMarketResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/markets/USA/watch"
      && response.request().method() === "POST",
  )
  await usaMarket.getByRole("button", { name: "加入观察市场" }).click()
  expect((await watchMarketResponse).status()).toBe(200)
  await expect(usaMarket).toContainText("已观察")
  await page.reload()
  await page.getByRole("searchbox", { name: "搜索国家" }).fill("美国")
  const persistedUsaMarket = page.getByRole("article", { name: "美国 海关强数据路线" })
  await expect(persistedUsaMarket).toContainText("已观察")
  await persistedUsaMarket.getByRole("button", { name: "查看该市场候选公司" }).click()
  await expect(page.getByText(/美国 · 先导入许可名单或公开线索/)).toBeVisible()
  await expect(page.getByText("欧盟与英国官方采购数据", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("TED 欧盟采购公告")).toBeVisible()
  await expect(page.getByText("英国 Contracts Finder")).toBeVisible()
  await expect(page.getByText("Google Maps 官方企业发现")).toBeVisible()
  await expect(page.getByText("接入密钥后可用")).toBeVisible()
  await page.getByLabel("CSV 或 JSON 文件").setInputFiles("e2e/fixtures/licensed-candidate-sample.csv")
  await page.getByLabel("数据来源方").fill("E2E licensed supplier")
  await page.getByLabel("许可或合同名称").fill("E2E internal prospecting licence")
  const candidateImportResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/discovery/candidate-imports"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "导入为待核实候选" }).click()
  expect((await candidateImportResponse).status()).toBe(201)
  await expect(page.getByRole("status")).toContainText("已加入 2 家待核实候选")
  await expect(page.getByText(/待核实候选：2 家/)).toBeVisible()
  await expect(page.getByText("3 家目标公司")).toBeVisible()
  const jakartaCandidate = page.getByRole("article").filter({ hasText: "Jakarta Drives" })
  await expect(jakartaCandidate).toContainText("E2E licensed supplier")
  await expect(jakartaCandidate).toContainText("尚未发现采购意向，不会自动联系")
  const candidateReviewResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.includes("/api/v1/growth/discovery/candidates/")
      && new URL(response.url()).pathname.endsWith("/review")
      && response.request().method() === "POST",
  )
  await jakartaCandidate.getByRole("button", { name: "加入资料补全" }).click()
  expect((await candidateReviewResponse).status()).toBe(200)
  await expect(page.getByRole("status").filter({ hasText: "不会自动联系客户" })).toBeVisible()
  await expect(page.getByText(/待核实候选：1 家/)).toBeVisible()
  await expect(page.getByText("3 家目标公司")).toBeVisible()
  const enrichmentCard = page.getByRole("article").filter({ hasText: "Jakarta Drives" })
  await expect(page.getByRole("heading", { name: "待补全公司资料" })).toBeVisible()
  const enrichmentResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.includes("/api/v1/growth/enrichment/candidates/")
      && new URL(response.url()).pathname.endsWith("/prepare")
      && response.request().method() === "POST",
  )
  await enrichmentCard.getByRole("button", { name: "准备公司资料" }).click()
  expect((await enrichmentResponse).status()).toBe(201)
  await expect(enrichmentCard).toContainText("Demo / Fake 资料补全预演")
  await expect(enrichmentCard).toContainText("已有事实与来源")
  await expect(enrichmentCard).toContainText("尚未发现可验证的公开联系路径")
  await expect(enrichmentCard).toContainText("没有采购意向证据")
  await expect(page.getByText("3 家目标公司")).toBeVisible()
  const candidateFollowUpResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.includes("/api/v1/growth/enrichment/candidates/")
      && new URL(response.url()).pathname.endsWith("/follow-up")
      && response.request().method() === "POST",
  )
  await enrichmentCard.getByRole("button", { name: "加入跟进" }).click()
  expect((await candidateFollowUpResponse).status()).toBe(201)
  await expect(enrichmentCard).toContainText("已加入人工跟进")
  await expect(page.getByText("4 家目标公司")).toBeVisible()
  const candidateDraftResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.includes("/api/v1/growth/opportunities/")
      && new URL(response.url()).pathname.endsWith("/draft")
      && response.request().method() === "POST",
  )
  await enrichmentCard.getByRole("button", { name: "生成联系草稿" }).click()
  expect((await candidateDraftResponse).status()).toBe(201)
  await expect(enrichmentCard).toContainText("待人工审核 · 绝不自动发送")
  await expect(enrichmentCard).toContainText("Hello E2E Jakarta Drives team")
  const discoveryResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/discovery/run"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "立即查找" }).click()
  expect((await discoveryResponse).status()).toBe(200)
  await expect(page.getByRole("status").filter({ hasText: "发现 1 条新采购信号" })).toBeVisible()
  await expect(page.getByText("5 家目标公司")).toBeVisible()
  await page.getByRole("button", { name: /E2E Gear Procurement Authority/ }).click()
  await expect(page.getByRole("heading", { name: "E2E Gear Procurement Authority" })).toBeVisible()
  await expect(page.getByText("Demo / Fake").first()).toBeVisible()
  await page.getByRole("button", { name: "查看证据" }).click()
  await expect(page.getByText("TENDER · 官方招投标")).toBeVisible()
  const duplicateDiscoveryResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/v1/growth/discovery/run"
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "立即查找" }).click()
  expect((await duplicateDiscoveryResponse).status()).toBe(200)
  await expect(page.getByRole("status").filter({ hasText: "发现 0 条新采购信号" })).toBeVisible()
  await expect(page.getByText("5 家目标公司")).toBeVisible()
  await page.getByLabel("公司名称").fill("Browser Import Drives Ltd")
  await page.getByLabel("国家或地区").fill("United Kingdom")
  await page.getByLabel("行业（选填）").fill("Packaging machinery")
  await page.getByLabel("来源名称").fill("User supplied public news")
  await page.getByLabel("公开 HTTPS 链接").fill("https://example.invalid/manual-import/evidence")
  await page.getByLabel("原始证据摘要").fill("The company announced a permitted public packaging line expansion.")
  await page.getByLabel("截图文件名（可选）").fill("browser-import-evidence.png")
  await page.getByLabel("截图时间（可选）").fill("2026-08-14T09:30")
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
  await expect(page.getByText("人工导入网页与截图信息")).toBeVisible()
  await expect(page.getByText("manual-opportunity-v1")).toBeVisible()
  await expect(page.getByText("COMPANY_WEB · 企业官网或公开目录")).toBeVisible()
  await expect(page.getByText("公司身份仍需人工核实")).toBeVisible()
  await expect(page.getByText("采购范围与时间仍需人工确认")).toBeVisible()
  await expect(page.getByText(/browser-import-evidence\.png/)).toContainText("仅元数据")
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
  await expect(page.getByText("6 家目标公司")).toBeVisible()
  await page.getByRole("button", { name: /Browser Import Drives Ltd/ }).click()
  await expect(page.getByRole("heading", { name: "Browser Import Drives Ltd" })).toBeVisible()
  await page.getByRole("button", { name: /PackTech GmbH/ }).click()
  await expect(page.locator(".opportunity-detail").getByRole("heading", { name: "PackTech GmbH" })).toBeVisible()
  await expect(page.getByRole("button", { name: "已加入跟进" })).toBeDisabled()
  await page.getByRole("button", { name: /NordMotion AB/ }).click()
  await expect(page.locator(".opportunity-detail").getByRole("heading", { name: "NordMotion AB" })).toBeVisible()
  await expect(page.getByRole("button", { name: "加入跟进" })).toBeEnabled()
  await page.getByRole("button", { name: /PackTech GmbH/ }).click()
  await expect(page.locator(".opportunity-detail").getByRole("heading", { name: "PackTech GmbH" })).toBeVisible()
  await page.getByRole("button", { name: "查看证据" }).click()
  await expect(page.getByRole("heading", { name: "评分依据" })).toBeVisible()
  await expect(page.getByText("证据覆盖 18")).toBeVisible()
  await expect(page.getByText("本地演示样本")).toBeVisible()
  await expect(page.getByText("采购范围与时间仍需人工确认")).toBeVisible()
  await expect(page.getByRole("link", { name: "打开原始来源" }))
    .toHaveAttribute("href", "https://example.invalid/demo-evidence/1001")
  await expect(page.getByRole("heading", { name: "跟进记录" })).toBeVisible()
  await expect(page.getByText("从未发送")).toBeVisible()
  await expect(page.getByText("AI 建议：优先跟进")).toBeVisible()
  const reviewResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/review")
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "确认优先跟进" }).click()
  expect((await reviewResponse).status()).toBe(201)
  await expect(page.getByText("人工判断：优先跟进")).toBeVisible()
  const opportunityDraftResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/draft") && response.request().method() === "POST",
  )
  await page.locator(".opportunity-detail").getByRole("button", { name: "生成联系草稿" }).click()
  expect((await opportunityDraftResponse).status()).toBe(201)
  await expect(page.locator(".opportunity-detail").getByText(/Hello PackTech GmbH team/)).toBeVisible()
  const handoffResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith("/crm-handoff")
      && response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "确认草稿并交给 Mock CRM" }).click()
  expect((await handoffResponse).status()).toBe(201)
  await expect(page.getByRole("status")).toContainText("已保存到 Mock CRM，未发送任何消息")
  await page.reload()
  await expect(page.getByRole("button", { name: "已加入跟进" })).toBeDisabled()
  await expect(page.getByRole("heading", { name: "跟进记录" })).toBeVisible()
  await expect(page.getByText("从未发送")).toBeVisible()
  await expect(page.getByText("人工判断：优先跟进")).toBeVisible()
  await expect(page.getByRole("status")).toContainText("已保存到 Mock CRM，未发送任何消息")

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
