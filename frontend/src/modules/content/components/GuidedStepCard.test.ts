import { render, screen } from "@testing-library/vue"
import { expect, it } from "vitest"

import "../../../styles/tokens.css"
import GuidedStepCard from "./GuidedStepCard.vue"

it("expands only the current step and announces its position", async () => {
  const view = render(GuidedStepCard, {
    props: { number: 2, title: "告诉 AI 目标", description: "选择这次推广要达成的结果。", state: "current" },
    slots: { default: "<button>保存目标并继续</button>" },
  })

  expect(screen.getByRole("heading", { name: "告诉 AI 目标" })).toBeVisible()
  expect(screen.getByRole("region", { name: "告诉 AI 目标" })).toHaveAttribute("aria-current", "step")
  expect(screen.getByText("选择这次推广要达成的结果。")).toBeVisible()
  expect(screen.getByRole("button", { name: "保存目标并继续" })).toBeVisible()
  expect(getComputedStyle(view.container.querySelector("article")!).borderColor).toBe("var(--sg-brand)")
  expect(getComputedStyle(screen.getByText("2")).backgroundColor).toBe("var(--sg-brand)")
  expect(getComputedStyle(document.documentElement).getPropertyValue("--sg-brand").trim()).toBe("#005ba8")

  await view.rerender({ number: 2, title: "告诉 AI 目标", description: "选择这次推广要达成的结果。", state: "locked" })
  expect(screen.queryByText("选择这次推广要达成的结果。")).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "保存目标并继续" })).not.toBeInTheDocument()
  expect(screen.getByText("尚未开始")).toBeVisible()
})
