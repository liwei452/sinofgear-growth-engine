import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { expect, it } from "vitest"

import BusinessState from "./BusinessState.vue"

it("announces loading work with text and icon semantics", () => {
  render(BusinessState, {
    props: {
      kind: "loading",
      title: "正在读取",
      message: "正在读取客户机会，请稍候。",
    },
  })

  expect(screen.getByRole("status")).toHaveTextContent("正在读取")
  expect(screen.getByLabelText("正在读取")).toBeInTheDocument()
})

it("emits an action when the named recovery action is selected", async () => {
  const user = userEvent.setup()
  const { emitted } = render(BusinessState, {
    props: {
      kind: "error",
      title: "暂时无法读取客户机会",
      message: "请检查网络后重试。",
      actionLabel: "重新加载",
    },
  })

  await user.click(screen.getByRole("button", { name: "重新加载" }))
  expect(emitted("action")).toHaveLength(1)
})
