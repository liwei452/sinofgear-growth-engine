import { render } from "@testing-library/vue"
import { expect, it } from "vitest"

import AppIcon from "./AppIcon.vue"

it("renders a named decorative SVG at the requested size", () => {
  const { container } = render(AppIcon, {
    props: { name: "calendar-days", size: 24, strokeWidth: 2 },
  })
  const icon = container.querySelector('svg[data-icon="calendar-days"]')

  expect(icon).toBeInTheDocument()
  expect(icon).toHaveAttribute("aria-hidden", "true")
  expect(icon).toHaveAttribute("width", "24")
  expect(icon).toHaveAttribute("stroke-width", "2")
})
