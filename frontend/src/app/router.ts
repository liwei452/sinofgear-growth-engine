import type { QueryClient } from "@tanstack/vue-query"
import type { Component } from "vue"
import {
  createRouter, createWebHistory, type RouterHistory, type RouteRecordRaw,
} from "vue-router"

import { ApiError } from "../api/client"
import { currentUserQueryOptions } from "../modules/auth/auth"

export type AppRouteComponents = {
  Login: Component
  Shell: Component
  Dashboard: Component
  Promotion: Component
  Opportunities: Component
  Missions: Component
  MissionDetail: Component
  Company: Component
  Settings: Component
  AIModelSettings: Component
  MapsDiscovery: Component
  Products: Component
  Knowledge: Component
  ContentFactory: Component
  Reviews: Component
  Assets: Component
  PublishingCalendar: Component
  PlatformAccounts: Component
  RoleHome: Component
  ContentAssetsHub: Component
  Attribution: Component
  Placeholder: Component
}

type RouterOptions = {
  history?: RouterHistory
  components: AppRouteComponents
}

export function safeRedirect(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) {
    return "/"
  }
  let decoded: string
  try {
    decoded = decodeURIComponent(value)
  } catch {
    return "/"
  }
  const hasUnsafeCharacter = [...decoded].some((character) => {
    const codePoint = character.codePointAt(0) ?? 0
    return character === "\\" || codePoint < 32 || codePoint === 127
  })
  if (hasUnsafeCharacter) return "/"
  const target = new URL(value, window.location.origin)
  if (target.origin !== window.location.origin) return "/"
  return `${target.pathname}${target.search}${target.hash}`
}

export function createAppRouter(queryClient: QueryClient, options: RouterOptions) {
  const childRoutes: RouteRecordRaw[] = [
    {
      path: "",
      name: "home",
      component: options.components.RoleHome,
      meta: { title: "今天" },
    },
    { path: "promotion", redirect: { name: "missions" } },
    { path: "opportunities", redirect: { name: "missions" } },
    { path: "agent-approvals", name: "agent-approvals", redirect: { name: "home", query: { view: "approvals" } } },
    { path: "missions", name: "missions", component: options.components.Missions, meta: { title: "增长任务", requiredPermission: "missions.read" } },
    { path: "missions/:missionId", name: "mission-detail", component: options.components.MissionDetail, meta: { title: "增长任务详情", requiredPermission: "missions.read" } },
    { path: "company", name: "company", component: options.components.Company, meta: { title: "我的公司", requiredRole: "ADMINISTRATOR" } },
    { path: "settings", name: "settings", component: options.components.Settings, meta: { title: "设置中心", requiredRole: "ADMINISTRATOR" } },
    { path: "settings/ai-model", name: "ai-model-settings", component: options.components.AIModelSettings, meta: { title: "AI 模型", requiredRole: "ADMINISTRATOR", requiredPermission: "credentials.manage" } },
    { path: "maps-discovery", name: "maps-discovery", component: options.components.MapsDiscovery, meta: { title: "谷歌地图获客", requiredRole: "ADMINISTRATOR", requiredPermission: "leads.manage" } },
    {
      path: "products",
      name: "products",
      component: options.components.Products,
      meta: { title: "产品库", requiredRole: "ADMINISTRATOR", requiredPermission: "products.read" },
    },
    {
      path: "knowledge",
      name: "knowledge",
      component: options.components.Knowledge,
      meta: { title: "知识库", requiredPermission: "knowledge.read" },
    },
    { path: "content-factory", redirect: { name: "missions" } },
    { path: "reviews", redirect: { name: "missions" } },
    { path: "assets", name: "assets", component: options.components.Assets, meta: { title: "素材库", requiredPermission: "assets.read" } },
    { path: "publishing-calendar", redirect: { name: "missions" } },
    { path: "platform-accounts", name: "platform-accounts", component: options.components.PlatformAccounts, meta: { title: "平台账户", requiredRole: "ADMINISTRATOR", requiredPermission: "publishing.read" } },
    { path: "analytics", name: "analytics", redirect: { name: "attribution" } },
    { path: "attribution", name: "attribution", component: options.components.Attribution, meta: { title: "数据归因", requiredPermission: "missions.read" } },
    { path: "content", redirect: { name: "assets" } },
  ]
  const router = createRouter({
    history: options.history ?? createWebHistory(),
    routes: [
      {
        path: "/login",
        name: "login",
        component: options.components.Login,
        meta: { public: true, title: "登录" },
      },
      {
        path: "/",
        component: options.components.Shell,
        meta: { requiresAuth: true },
        children: childRoutes,
      },
    ],
  })
  router.beforeEach(async (to) => {
    if (!to.matched.some((record) => record.meta.requiresAuth)) return true
    try {
      const currentUser = await queryClient.ensureQueryData(currentUserQueryOptions())
      const requiredRole = typeof to.meta.requiredRole === "string" ? to.meta.requiredRole : undefined
      if (requiredRole && currentUser.membership.role !== requiredRole) {
        return { name: "home", query: { blocked: "administrator" } }
      }
      const requiredPermission = typeof to.meta.requiredPermission === "string"
        ? to.meta.requiredPermission
        : undefined
      if (requiredPermission && !currentUser.membership.permissions.includes(requiredPermission)) {
        return { name: "settings", query: { blocked: requiredPermission } }
      }
      return true
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        queryClient.removeQueries({ queryKey: ["auth", "me"] })
        return { name: "login", query: { redirect: safeRedirect(to.fullPath) } }
      }
      return true
    }
  })
  return router
}
