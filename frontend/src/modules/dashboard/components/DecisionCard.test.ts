import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"

import DecisionCard from "./DecisionCard.vue"

it("shows only the actions permitted by the cockpit contract and disables one active card", async () => {
  const onDecide = vi.fn()
  const user = userEvent.setup()
  render(DecisionCard, {
    props: {
      index: 1,
      title: "确认北方传动是否值得联系",
      explanation: "这条客户机会尚未完成人工判断；现在确认可让后续跟进继续。",
      actions: ["APPROVE", "REQUEST_ADJUSTMENT", "REJECT"],
      busy: false,
      onDecide,
    },
  })

  expect(screen.getByText("优先级 1")).toBeVisible()
  expect(screen.getByRole("heading", { name: "确认北方传动是否值得联系" })).toBeVisible()
  expect(screen.getByText("这条客户机会尚未完成人工判断；现在确认可让后续跟进继续。")).toBeVisible()
  await user.click(screen.getByRole("button", { name: "批准" }))
  await user.click(screen.getByRole("button", { name: "要求调整" }))
  await user.click(screen.getByRole("button", { name: "拒绝" }))
  expect(onDecide.mock.calls.map(([action]) => action)).toEqual(["APPROVE", "REQUEST_ADJUSTMENT", "REJECT"])
})

it("hides unavailable actions and disables all controls while this proposal is active", () => {
  render(DecisionCard, {
    props: {
      index: 2, title: "确认推广方案", explanation: "依据已确认资料生成。",
      actions: ["APPROVE"], busy: true,
    },
  })

  expect(screen.getByRole("button", { name: "正在提交" })).toBeDisabled()
  expect(screen.queryByRole("button", { name: "要求调整" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument()
})
