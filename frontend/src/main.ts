import { VueQueryPlugin } from "@tanstack/vue-query"
import { createApp } from "vue"

import App from "./App.vue"
import AppShell from "./app/AppShell.vue"
import { queryClient } from "./app/queryClient"
import { createAppRouter } from "./app/router"
import LoginPage from "./modules/auth/LoginPage.vue"
import DashboardPage from "./modules/dashboard/DashboardPage.vue"
import PlaceholderPage from "./shared/components/PlaceholderPage.vue"
import "./styles/tokens.css"
import "./styles/base.css"

const router = createAppRouter(queryClient, {
  components: {
    Login: LoginPage,
    Shell: AppShell,
    Dashboard: DashboardPage,
    Placeholder: PlaceholderPage,
  },
})

createApp(App)
  .use(VueQueryPlugin, { queryClient })
  .use(router)
  .mount("#app")
