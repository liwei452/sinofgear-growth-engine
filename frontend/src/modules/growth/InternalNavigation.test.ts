import { mount } from "@vue/test-utils"
import { expect, it } from "vitest"
import { createMemoryHistory, createRouter, RouterLink } from "vue-router"

import PromotionPlanSummary from "./PromotionPlanSummary.vue"

it("uses SPA navigation after a promotion plan is approved", async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<div />" } },
      { path: "/content-factory", component: { template: "<div />" } },
    ],
  })
  await router.push("/")
  await router.isReady()

  const wrapper = mount(PromotionPlanSummary, {
    props: { approved: true },
    global: { plugins: [router] },
  })

  expect(wrapper.findComponent(RouterLink).exists()).toBe(true)
  expect(wrapper.get("a").attributes("href")).toBe("/content-factory")
})
