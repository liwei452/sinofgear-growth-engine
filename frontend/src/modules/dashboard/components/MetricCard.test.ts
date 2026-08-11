import { render, screen } from "@testing-library/vue"
import { expect, it } from "vitest"

import MetricCard from "./MetricCard.vue"

it("keeps the available metric and its conclusion together", () => {
  render(MetricCard, {
    props: {
      label: "近期完成任务",
      value: "3 项",
      conclusion: "已有 3 项工作完成，可以查看对应工作区的结果。",
    },
  })

  expect(screen.getByText("近期完成任务")).toBeVisible()
  expect(screen.getByText("3 项")).toBeVisible()
  expect(screen.getByText("已有 3 项工作完成，可以查看对应工作区的结果。")).toBeVisible()
})
