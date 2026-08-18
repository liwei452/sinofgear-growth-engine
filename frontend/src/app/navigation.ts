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

export const navigationSections: NavigationSection[] = [
  {
    items: [{ label: "今日待办", to: "/", icon: "calendar-days" }],
  },
  {
    group: "增长",
    items: [
      { label: "增长任务", to: "/missions", icon: "clipboard-check", requiredPermission: "missions.read" },
      { label: "客户与商机", to: "/opportunities", icon: "users-round", requiredPermission: "leads.read" },
      { label: "内容与素材", to: "/content", icon: "sparkles", requiredPermission: "content.read" },
      { label: "数据归因", to: "/attribution", icon: "chart-column", requiredPermission: "missions.read" },
    ],
  },
]

export const utilityNavigation: NavigationItem[] = [
  {
    label: "系统配置",
    to: "/settings",
    icon: "settings",
    requiredRole: "ADMINISTRATOR",
    requiresPermission: "credentials.manage",
  },
]
