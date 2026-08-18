import { render, screen } from "@testing-library/vue"
import { expect, it } from "vitest"

import EmptyState from "./EmptyState.vue"
import WorkspaceHeader from "./WorkspaceHeader.vue"

it("renders one clear page heading with supporting actions", () => {
  render(WorkspaceHeader, {
    props: {
      eyebrow: "今天",
      title: "今天先做这三件事",
      description: "按优先级处理需要人工决定的工作。",
    },
    slots: { actions: '<button type="button">处理全部</button>' },
  })

  expect(screen.getByRole("heading", { level: 1, name: "今天先做这三件事" })).toBeInTheDocument()
  expect(screen.getByText("按优先级处理需要人工决定的工作。")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "处理全部" })).toBeInTheDocument()
})

it("renders a truthful icon-led empty state and its next action", () => {
  render(EmptyState, {
    props: {
      icon: "inbox",
      title: "这里还没有内容",
      description: "创建第一条内容后，它会出现在这里。",
    },
    slots: { default: '<a href="/content-factory">创建内容</a>' },
  })

  expect(screen.getByTestId("icon-inbox")).toHaveAttribute("aria-hidden", "true")
  expect(screen.getByRole("heading", { level: 3, name: "这里还没有内容" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "创建内容" })).toHaveAttribute("href", "/content-factory")
})
