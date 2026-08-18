import { createMemoryHistory, createRouter } from "vue-router"

export function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }],
  })
}
