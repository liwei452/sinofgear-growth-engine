import { VueQueryPlugin } from "@tanstack/vue-query"
import { createApp, defineAsyncComponent } from "vue"

import App from "./App.vue"
import AppShell from "./app/AppShell.vue"
import { queryClient } from "./app/queryClient"
import { createAppRouter } from "./app/router"
import LoginPage from "./modules/auth/LoginPage.vue"
import DashboardPage from "./modules/dashboard/DashboardPage.vue"
import RoleHomePage from "./modules/dashboard/RoleHomePage.vue"
import CompanyPage from "./modules/growth/CompanyPage.vue"
import OpportunityWorkspacePage from "./modules/opportunities/OpportunityWorkspacePage.vue"
import HelpPage from "./modules/help/HelpPage.vue"
import GrowthMissionsPage from "./modules/missions/GrowthMissionsPage.vue"
import GrowthMissionDetailPage from "./modules/missions/GrowthMissionDetailPage.vue"
import PromotionWorkspacePage from "./modules/promotion/PromotionWorkspacePage.vue"
import ContentPublishingPage from "./modules/publishing/ContentPublishingPage.vue"
import ExecutiveAttributionPage from "./modules/attribution/ExecutiveAttributionPage.vue"
import PlaceholderPage from "./shared/components/PlaceholderPage.vue"
import "./styles/tokens.css"
import "./styles/base.css"

const router = createAppRouter(queryClient, {
  components: {
    Login: LoginPage,
    Shell: AppShell,
    Dashboard: DashboardPage,
    RoleHome: RoleHomePage,
    Promotion: PromotionWorkspacePage,
    Opportunities: OpportunityWorkspacePage,
    ContentPublishing: ContentPublishingPage,
    Results: PlaceholderPage,
    Missions: GrowthMissionsPage,
    MissionDetail: GrowthMissionDetailPage,
    Company: CompanyPage,
    Help: HelpPage,
    Settings: defineAsyncComponent(() => import("./modules/settings/SettingsCenterPage.vue")),
    AIModelSettings: defineAsyncComponent(() => import("./modules/settings/AIModelSettingsPage.vue")),
    MapsDiscovery: defineAsyncComponent(() => import("./modules/growth/GoogleMapsDiscoverySettings.vue")),
    Products: defineAsyncComponent(() => import("./modules/products/ProductLibraryPage.vue")),
    Knowledge: defineAsyncComponent(() => import("./modules/knowledge/KnowledgeLibraryPage.vue")),
    Assets: defineAsyncComponent(() => import("./modules/assets/AssetLibraryPage.vue")),
    PlatformAccounts: defineAsyncComponent(() => import("./modules/platformAccounts/PlatformAccountsPage.vue")),
    Attribution: ExecutiveAttributionPage,
    Placeholder: PlaceholderPage,
  },
})

createApp(App)
  .use(VueQueryPlugin, { queryClient })
  .use(router)
  .mount("#app")
