import { VueQueryPlugin } from "@tanstack/vue-query"
import { createApp, defineAsyncComponent } from "vue"

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
    Products: defineAsyncComponent(() => import("./modules/products/ProductLibraryPage.vue")),
    Knowledge: defineAsyncComponent(() => import("./modules/knowledge/KnowledgeLibraryPage.vue")),
    ContentFactory: defineAsyncComponent(() => import("./modules/content/ContentFactoryPage.vue")),
    Reviews: defineAsyncComponent(() => import("./modules/content/ReviewCenterPage.vue")),
    Assets: defineAsyncComponent(() => import("./modules/assets/AssetLibraryPage.vue")),
    PublishingCalendar: defineAsyncComponent(() => import("./modules/publishing/PublishingCalendarPage.vue")),
    PlatformAccounts: defineAsyncComponent(() => import("./modules/platformAccounts/PlatformAccountsPage.vue")),
    Analytics: defineAsyncComponent(() => import("./modules/analytics/AnalyticsPage.vue")),
    LeadRadar: defineAsyncComponent(() => import("./modules/leads/LeadRadarPage.vue")),
    CompanyProfile: defineAsyncComponent(() => import("./modules/company/CompanyProfilePage.vue")),
    Placeholder: PlaceholderPage,
  },
})

createApp(App)
  .use(VueQueryPlugin, { queryClient })
  .use(router)
  .mount("#app")
