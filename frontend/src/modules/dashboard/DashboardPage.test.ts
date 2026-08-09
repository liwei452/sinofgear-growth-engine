import { render, screen } from "@testing-library/vue"
import userEvent from "@testing-library/user-event"
import { createMemoryHistory, createRouter } from "vue-router"
import { expect, it, vi } from "vitest"

import NextStepPanel from "../../shared/components/NextStepPanel.vue"
import DashboardPage from "./DashboardPage.vue"

const steps = [
  { title: "添加第一个产品", description: "先让系统知道你要推广什么。" },
  { title: "整理品牌知识", description: "补充受众、卖点和表达边界。" },
  { title: "准备可用素材", description: "上传图片或视频，后续生成会更顺手。" },
]

async function renderWithRouter(component: typeof DashboardPage, props = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component },
      { path: "/products", component: { template: "<p>产品页</p>" } },
    ],
  })
  router.push("/")
  await router.isReady()
  return render(component, { props, global: { plugins: [router] } })
}

it("shows three clear novice steps and one primary action", async () => {
  await renderWithRouter(DashboardPage)

  expect(screen.getByRole("heading", { name: "下一步建议" })).toBeInTheDocument()
  for (const step of steps) expect(screen.getByText(step.title)).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "先添加产品" })).toHaveAttribute("href", "/products")
})

it("announces a loading state without showing actions", async () => {
  render(NextStepPanel, { props: { state: "loading", steps: [] } })

  expect(screen.getByRole("status")).toHaveTextContent("正在准备适合你的下一步…")
  expect(screen.queryByRole("link")).not.toBeInTheDocument()
})

it("shows an accessible empty state", async () => {
  render(NextStepPanel, { props: { state: "ready", steps: [] } })

  expect(screen.getByRole("status")).toHaveTextContent("暂时没有待办事项")
})

it("shows a recoverable error and emits retry", async () => {
  const retry = vi.fn()
  const user = userEvent.setup()
  render(NextStepPanel, { props: { state: "error", steps: [], onRetry: retry } })

  expect(screen.getByRole("alert")).toHaveTextContent("建议加载失败，请稍后重试。")
  await user.click(screen.getByRole("button", { name: "重新加载" }))
  expect(retry).toHaveBeenCalledOnce()
})
