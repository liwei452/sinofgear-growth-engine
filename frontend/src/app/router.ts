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
  Products: Component
  Knowledge: Component
  ContentFactory: Component
  Reviews: Component
  Placeholder: Component
}

type RouterOptions = {
  history?: RouterHistory
  components: AppRouteComponents
}

const placeholderRoutes: Array<{ path: string; name: string; title: string }> = [
  { path: "assets", name: "assets", title: "素材库" },
  { path: "publishing-calendar", name: "publishing-calendar", title: "发布日历" },
  { path: "platform-accounts", name: "platform-accounts", title: "平台账号" },
  { path: "analytics", name: "analytics", title: "数据看板" },
]

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
      meta: { title: "首页" },
    },
    {
      path: "products",
      name: "products",
      component: options.components.Products,
      meta: { title: "产品库" },
    },
    {
      path: "knowledge",
      name: "knowledge",
      component: options.components.Knowledge,
      meta: { title: "知识库" },
    },
    {
      path: "content-factory",
      name: "content-factory",
      component: options.components.ContentFactory,
      meta: { title: "AI 内容工厂" },
    },
    {
      path: "reviews",
      name: "reviews",
      component: options.components.Reviews,
      meta: { title: "审核中心" },
    },
    ...placeholderRoutes.map((route) => ({
      ...route,
      component: options.components.Placeholder,
      meta: { title: route.title },
    })),
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
      await queryClient.ensureQueryData(currentUserQueryOptions())
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
