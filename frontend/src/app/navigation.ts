import type { IconName } from "../shared/components/AppIcon.vue"

export type NavigationItem = {
  label: string
  to: string
  icon: IconName
  requiredPermission?: string
  requiredRole?: string
  requiresPermission?: string
}

export type NavigationSection = {
  group?: string
  items: NavigationItem[]
}

export const navigationSections: NavigationSection[] = [{
  items: [
    { label: "今日", to: "/", icon: "calendar-days" },
    { label: "开始推广", to: "/promotion", icon: "send", requiredPermission: "missions.read" },
    { label: "客户机会", to: "/opportunities", icon: "users-round", requiredPermission: "leads.manage" },
    { label: "内容与发布", to: "/content-factory", icon: "clipboard-check", requiredPermission: "publishing.read" },
    { label: "效果", to: "/analytics", icon: "chart-column", requiredPermission: "missions.read" },
  ],
}]

export const utilityNavigation: NavigationItem[] = [
  { label: "我的公司", to: "/company", icon: "building-2" },
  { label: "帮助", to: "/help", icon: "book-open" },
  { label: "设置", to: "/settings", icon: "settings" },
]
