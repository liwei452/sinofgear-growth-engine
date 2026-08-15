import { VueQueryPlugin } from "@tanstack/vue-query"
import { createApp, defineAsyncComponent } from "vue"

import App from "./App.vue"
import AppShell from "./app/AppShell.vue"
import { queryClient } from "./app/queryClient"
import { createAppRouter } from "./app/router"
import LoginPage from "./modules/auth/LoginPage.vue"
import DashboardPage from "./modules/dashboard/DashboardPage.vue"
import CompanyPage from "./modules/growth/CompanyPage.vue"
import EffectivenessPage from "./modules/growth/EffectivenessPage.vue"
import OpportunitiesPage from "./modules/growth/OpportunitiesPage.vue"
import PromotionPage from "./modules/growth/PromotionPage.vue"
import PlaceholderPage from "./shared/components/PlaceholderPage.vue"
import "./styles/tokens.css"
import "./styles/base.css"

const router = createAppRouter(queryClient, {
  components: {
    Login: LoginPage,
    Shell: AppShell,
    Dashboard: DashboardPage,
    Promotion: PromotionPage,
    Opportunities: OpportunitiesPage,
    Company: CompanyPage,
    Settings: defineAsyncComponent(() => import("./modules/settings/SettingsCenterPage.vue")),
    Products: defineAsyncComponent(() => import("./modules/products/ProductLibraryPage.vue")),
    Knowledge: defineAsyncComponent(() => import("./modules/knowledge/KnowledgeLibraryPage.vue")),
    ContentFactory: defineAsyncComponent(() => import("./modules/content/ContentFactoryPage.vue")),
    Reviews: defineAsyncComponent(() => import("./modules/content/ReviewCenterPage.vue")),
    Assets: defineAsyncComponent(() => import("./modules/assets/AssetLibraryPage.vue")),
    PublishingCalendar: defineAsyncComponent(() => import("./modules/publishing/PublishingCalendarPage.vue")),
    PlatformAccounts: defineAsyncComponent(() => import("./modules/platformAccounts/PlatformAccountsPage.vue")),
    Analytics: EffectivenessPage,
    LegacyAnalytics: defineAsyncComponent(() => import("./modules/analytics/AnalyticsPage.vue")),
    Placeholder: PlaceholderPage,
  },
})

createApp(App)
  .use(VueQueryPlugin, { queryClient })
  .use(router)
  .mount("#app")
