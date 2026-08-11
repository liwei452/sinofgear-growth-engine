import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import DecisionCard from "./DecisionCard.vue"

it("shows the priority, reason, and next action before optional follow-up", async () => {
  const onPrimary = vi.fn()
  const onSecondary = vi.fn()
  const user = userEvent.setup()
  render(DecisionCard, {
    props: {
      index: 1,
      title: "确认北方传动是否值得联系",
      explanation: "这条客户机会尚未完成人工判断；现在确认可让后续跟进继续。",
      statusLabel: "等待你的判断",
      statusTone: "warning",
      primaryAction: "查看并决定",
      secondaryAction: "稍后处理",
      onPrimary,
      onSecondary,
    },
  })

  expect(screen.getByText("优先级 1")).toBeVisible()
  expect(screen.getByRole("heading", { name: "确认北方传动是否值得联系" })).toBeVisible()
  expect(screen.getByText("这条客户机会尚未完成人工判断；现在确认可让后续跟进继续。")).toBeVisible()
  expect(screen.getByText("等待你的判断")).toBeVisible()

  await user.click(screen.getByRole("button", { name: "查看并决定" }))
  await user.click(screen.getByRole("button", { name: "稍后处理" }))
  expect(onPrimary).toHaveBeenCalledTimes(1)
  expect(onSecondary).toHaveBeenCalledTimes(1)
})
