import { render, screen } from "@testing-library/vue"
import { expect, it } from "vitest"

import WorkspaceHeader from "./WorkspaceHeader.vue"

it("renders a business page heading, description, translated status, and actions", () => {
  render(WorkspaceHeader, {
    props: {
      title: "客户机会",
      description: "查看需要跟进的高意向客户。",
      status: "RUNNING",
    },
    slots: { actions: '<button type="button">新建跟进</button>' },
  })

  expect(screen.getByRole("heading", { level: 1, name: "客户机会" })).toBeInTheDocument()
  expect(screen.getByText("正在获客")).toBeInTheDocument()
  expect(screen.getByText("新建跟进")).toBeInTheDocument()
})
