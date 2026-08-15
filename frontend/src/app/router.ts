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
  Company: Component
  Settings: Component
  MapsDiscovery: Component
  Products: Component
  Knowledge: Component
  ContentFactory: Component
  Reviews: Component
  Assets: Component
  PublishingCalendar: Component
  PlatformAccounts: Component
  Analytics: Component
  LegacyAnalytics: Component
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
      component: options.components.Dashboard,
      meta: { title: "今天" },
    },
    { path: "promotion", name: "promotion", component: options.components.Promotion, meta: { title: "推广" } },
    { path: "opportunities", name: "opportunities", component: options.components.Opportunities, meta: { title: "客户机会" } },
    { path: "company", name: "company", component: options.components.Company, meta: { title: "我的公司" } },
    { path: "settings", name: "settings", component: options.components.Settings, meta: { title: "设置中心" } },
    { path: "maps-discovery", name: "maps-discovery", component: options.components.MapsDiscovery, meta: { title: "谷歌地图获客" } },
    {
      path: "products",
      name: "products",
      component: options.components.Products,
      meta: { title: "产品库", requiredPermission: "products.read" },
    },
    {
      path: "knowledge",
      name: "knowledge",
      component: options.components.Knowledge,
      meta: { title: "知识库", requiredPermission: "knowledge.read" },
    },
    {
      path: "content-factory",
      name: "content-factory",
      component: options.components.ContentFactory,
      meta: { title: "AI 内容工厂", requiredPermission: "campaigns.read" },
    },
    {
      path: "reviews",
      name: "reviews",
      component: options.components.Reviews,
      meta: { title: "审核中心", requiredPermission: "content.read" },
    },
    { path: "assets", name: "assets", component: options.components.Assets, meta: { title: "素材库", requiredPermission: "assets.read" } },
    { path: "publishing-calendar", name: "publishing-calendar", component: options.components.PublishingCalendar, meta: { title: "发布日历", requiredPermission: "publishing.read" } },
    { path: "platform-accounts", name: "platform-accounts", component: options.components.PlatformAccounts, meta: { title: "平台账户", requiredPermission: "publishing.read" } },
    { path: "analytics", name: "analytics", component: options.components.Analytics, meta: { title: "效果" } },
    { path: "admin/analytics", name: "admin-analytics", component: options.components.LegacyAnalytics, meta: { title: "高级数据看板", requiredRole: "ADMINISTRATOR" } },
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
        return { name: "settings", query: { blocked: "administrator" } }
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
