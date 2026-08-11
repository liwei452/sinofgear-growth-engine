import { render, screen } from "@testing-library/vue"
import { expect, it } from "vitest"

import ActivityRow from "./ActivityRow.vue"

it("uses an indeterminate progress indicator when the job has no trustworthy percentage", () => {
  render(ActivityRow, {
    props: {
      title: "正在分析公开线索",
      detail: "已开始处理，完成时间暂时无法确认。",
      statusLabel: "正在处理",
      statusTone: "brand",
      progress: null,
    },
  })

  expect(screen.getByText("正在分析公开线索")).toBeVisible()
  expect(screen.getByText("已开始处理，完成时间暂时无法确认。")).toBeVisible()
  expect(screen.getByText("进度待确认")).toBeVisible()
  expect(screen.getByRole("progressbar", { name: "正在分析公开线索的进度" })).not.toHaveAttribute("aria-valuenow")
})

it("exposes the API-provided percentage when a job reports one", () => {
  render(ActivityRow, {
    props: {
      title: "正在整理公开线索",
      detail: "任务仍在执行。",
      statusLabel: "正在处理",
      statusTone: "brand",
      progress: 40,
    },
  })

  expect(screen.getByRole("progressbar", { name: "正在整理公开线索的进度" })).toHaveAttribute("aria-valuenow", "40")
  expect(screen.getByText("已完成 40%")) .toBeVisible()
})
