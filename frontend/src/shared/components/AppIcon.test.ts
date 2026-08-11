import { render, screen } from "@testing-library/vue"
import { expect, it } from "vitest"

import AppIcon from "./AppIcon.vue"

const iconNames = [
  "home", "megaphone", "users", "chart", "company", "settings", "bell",
  "globe", "chevron", "check", "search", "document", "sparkles", "star",
] as const

it.each(iconNames)("renders the %s icon as decorative inline SVG", (name) => {
  render(AppIcon, { props: { name } })

  const icon = screen.getByTestId(`app-icon-${name}`)
  expect(icon.tagName).toBe("svg")
  expect(icon).toHaveAttribute("aria-hidden", "true")
  expect(icon).toHaveAttribute("focusable", "false")
  expect(icon.querySelector("path, circle, rect, polyline, line")).not.toBeNull()
})
