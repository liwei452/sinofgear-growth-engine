import type { IconName } from "../shared/components/AppIcon.vue"

export type NavigationItem = {
  label: string
  to: string
  icon: IconName
  requiredPermission?: string
}

export type NavigationSection = {
  group?: string
  items: NavigationItem[]
}

export const navigationSections: NavigationSection[] = [{
  items: [{ label: "今天", to: "/", icon: "calendar-days" }],
}, {
  group: "客户增长",
  items: [
    { label: "客户机会", to: "/opportunities", icon: "users-round", requiredPermission: "leads.read" },
    { label: "谷歌地图获客", to: "/maps-discovery", icon: "map-pinned", requiredPermission: "leads.manage" },
  ],
}, {
  group: "AI Agent",
  items: [
    { label: "Agent 工作台", to: "/agent-workspace", icon: "bot", requiredPermission: "agents.run" },
  ],
}, {
  group: "内容与社媒",
  items: [
    { label: "内容工厂", to: "/content-factory", icon: "sparkles", requiredPermission: "content.manage" },
    { label: "审核中心", to: "/reviews", icon: "clipboard-check", requiredPermission: "content.read" },
    { label: "社媒运营", to: "/promotion", icon: "send", requiredPermission: "publishing.read" },
    { label: "发布日历", to: "/publishing-calendar", icon: "calendar-clock", requiredPermission: "publishing.read" },
    { label: "平台账户", to: "/platform-accounts", icon: "share-2", requiredPermission: "publishing.read" },
  ],
}, {
  group: "效果",
  items: [{ label: "经营效果", to: "/analytics", icon: "chart-column", requiredPermission: "metrics.read" }],
}, {
  group: "公司资产",
  items: [
    { label: "产品库", to: "/products", icon: "package-search", requiredPermission: "products.read" },
    { label: "知识库", to: "/knowledge", icon: "book-open", requiredPermission: "knowledge.read" },
    { label: "素材库", to: "/assets", icon: "images", requiredPermission: "assets.read" },
    { label: "公司资料", to: "/company", icon: "building-2" },
  ],
}]

export const utilityNavigation: NavigationItem[] = [
  { label: "设置中心", to: "/settings", icon: "settings" },
]
