import { expect, it } from "vitest"

import { businessStatus } from "./businessStatus"

it("translates active work and human approval into business language", () => {
  expect(businessStatus("RUNNING")).toMatchObject({ label: "正在获客", tone: "info" })
  expect(businessStatus("WAITING_APPROVAL")).toMatchObject({ label: "等待人工审核", tone: "warning" })
})

it("explains uncertain publication and configuration blockers", () => {
  expect(businessStatus("SUBMISSION_UNKNOWN")).toMatchObject({
    label: "已提交，等待平台确认",
    tone: "warning",
  })
  expect(businessStatus("CONFIGURATION_REQUIRED").consequence).toContain("暂不能")
})

it("translates dashboard health and platform connection states", () => {
  expect(businessStatus("ACTION_REQUIRED")).toMatchObject({ label: "需要处理", tone: "warning" })
  expect(businessStatus("NOT_CONNECTED")).toMatchObject({ label: "尚未连接", tone: "warning" })
})

it("keeps unrecognized values neutral and explainable", () => {
  expect(businessStatus("UNRECOGNIZED")).toEqual({
    label: "状态待确认",
    consequence: "系统尚未提供可解释的业务状态。",
    tone: "neutral",
  })
})
