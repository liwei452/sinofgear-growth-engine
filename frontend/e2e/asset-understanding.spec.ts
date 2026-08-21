import { expect, test } from "@playwright/test"

function labeledPdf(): Buffer {
  const content="BT /F1 12 Tf 72 720 Td (Product: Custom helical gear) Tj 0 -18 Td (Process: Gear grinding) Tj 0 -18 Td (Accuracy: DIN 6) Tj ET"
  const objects=[
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ]
  let body="%PDF-1.4\n",offset=Buffer.byteLength(body)
  const offsets=[0]
  objects.forEach((object,index)=>{offsets.push(offset);const chunk=`${index+1} 0 obj\n${object}\nendobj\n`;body+=chunk;offset+=Buffer.byteLength(chunk)})
  const xref=offset
  body+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`
  for(const value of offsets.slice(1))body+=`${String(value).padStart(10,"0")} 00000 n \n`
  body+=`trailer\n<< /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(body)
}

test("uploaded PDF becomes reviewed product facts without real AI or sending",async({page})=>{
  test.setTimeout(120_000)
  await page.goto("/login")
  await page.getByLabel("用户名").fill("phasea_e2e_operator")
  await page.getByLabel("密码").fill("PhaseA-E2E-Only!")
  await page.getByRole("button",{name:"登录",exact:true}).click()
  await expect(page).toHaveURL(/\/$/)
  await page.goto("/assets")
  await page.getByRole("button",{name:"上传素材"}).click()
  await page.getByLabel("文件").setInputFiles({name:"reviewed-gear-facts.pdf",mimeType:"application/pdf",buffer:labeledPdf()})
  await page.getByLabel("素材类型").selectOption("DOCUMENT")
  await page.getByRole("button",{name:"上传",exact:true}).click()
  const card=page.locator("article.panel").filter({hasText:"reviewed-gear-facts.pdf"})
  await expect(card).toBeVisible()
  await card.getByLabel("整理到产品").selectOption("10000000-0000-4000-8000-000000000101")
  await card.getByRole("button",{name:"准备产品事实"}).click()
  await expect(card.getByText("Fake Provider · 本地演示")).toBeVisible()
  await card.getByRole("button",{name:"查看已有事实"}).click()
  await expect(card.getByText("Accuracy: DIN 6")).toBeVisible()
  const accuracy=card.locator("article.fact").filter({hasText:"accuracy：DIN 6"})
  await expect(accuracy.getByText("高风险事实，必须人工确认")).toBeVisible()
  await accuracy.getByRole("button",{name:"确认写入事实库"}).click()
  await expect(accuracy.getByText("已验证")).toBeVisible()
  await page.reload()
  const refreshed=page.locator("article.panel").filter({hasText:"reviewed-gear-facts.pdf"})
  await refreshed.getByRole("button",{name:"查看已有事实"}).click()
  await expect(refreshed.locator("article.fact").filter({hasText:"accuracy：DIN 6"}).getByText("已验证")).toBeVisible()
})
