import { render, screen } from "@testing-library/vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { expect, it } from "vitest"

import ContentAssetsHubPage from "./ContentAssetsHubPage.vue"

it("links the four ordinary content destinations", async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/content", component: ContentAssetsHubPage }],
  })
  await router.push("/content")
  render(ContentAssetsHubPage, { global: { plugins: [router] } })
  await router.isReady()

  expect(screen.getByRole("link", { name: /任务内容/ })).toHaveAttribute("href", "/missions?view=content")
  expect(screen.getByRole("link", { name: /已批准内容/ })).toHaveAttribute("href", "/reviews?status=approved")
  expect(screen.getByRole("link", { name: /素材库/ })).toHaveAttribute("href", "/assets")
  expect(screen.getByRole("link", { name: /知识参考/ })).toHaveAttribute("href", "/knowledge")
})
