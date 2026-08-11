import { render, screen } from "@testing-library/vue"
import { expect, it } from "vitest"

import StatusBadge from "./StatusBadge.vue"

it.each([
  ["brand", "进行中"],
  ["success", "已完成"],
  ["warning", "需要注意"],
  ["danger", "未能完成"],
  ["neutral", "暂未设置"],
] as const)("keeps the %s status understandable from its text label", (tone, label) => {
  render(StatusBadge, { props: { tone, label } })

  const badge = screen.getByText(label)
  expect(badge).toHaveClass("status-badge", `status-badge-${tone}`)
  expect(badge).toHaveTextContent(label)
})
