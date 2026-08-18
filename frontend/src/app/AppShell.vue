<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router"

import { ApiError } from "../api/client"
import { currentUserQueryOptions, logout } from "../modules/auth/auth"
import { agentRunsQueryOptions } from "../modules/growth/agentApi"
import AppIcon from "../shared/components/AppIcon.vue"
import { navigationSections, utilityNavigation } from "./navigation"

const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const currentUser = useQuery(currentUserQueryOptions())
const canApprove = computed(
  () => currentUser.data.value?.membership.permissions.includes("agents.approve") ?? false,
)
const pendingApprovals = useQuery({
  ...agentRunsQueryOptions("WAITING_APPROVAL"),
  enabled: canApprove,
})
const pendingApprovalCount = computed(
  () => (pendingApprovals.data.value ?? []).length,
)
const visibleNavigation = computed(() =>
  navigationSections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => {
        const permission = item.requiredPermission
        if (!permission) return true
        return currentUser.data.value?.membership.permissions.includes(permission) ?? false
      }),
    }))
    .filter((section) => section.items.length > 0),
)
const navOpen = ref(false)
const userMenuOpen = ref(false)
const isNarrowViewport = ref(false)
const sidebarElement = ref<HTMLElement | null>(null)
const menuButtonElement = ref<HTMLButtonElement | null>(null)
const userMenuButtonElement = ref<HTMLButtonElement | null>(null)
const contentElement = ref<HTMLElement | null>(null)
const drawerClosed = computed(() => isNarrowViewport.value && !navOpen.value)
const logoutMutation = useMutation({
  mutationFn: logout,
  onSuccess: async () => {
    queryClient.removeQueries()
    await router.replace("/login")
  },
})
const logoutError = computed(() => {
  const error = logoutMutation.error.value
  if (!error) return undefined
  if (error instanceof ApiError) {
    return {
      message: error.userMessage,
      recovery: error.recoveryAction ?? "请检查网络后重试。",
    }
  }
  return {
    message: "暂时无法退出登录。",
    recovery: "请检查网络后重试。",
  }
})

let viewportQuery: MediaQueryList | undefined

function updateViewport(event: MediaQueryList | MediaQueryListEvent) {
  isNarrowViewport.value = event.matches
  if (!event.matches) navOpen.value = false
}

function drawerFocusableElements(): HTMLElement[] {
  if (!sidebarElement.value) return []
  return [...sidebarElement.value.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )]
}

function closeNavigation() {
  const wasOpen = navOpen.value
  navOpen.value = false
  if (wasOpen && isNarrowViewport.value) {
    void nextTick(() => menuButtonElement.value?.focus())
  }
}

async function openNavigation() {
  navOpen.value = true
  await nextTick()
  drawerFocusableElements()[0]?.focus()
}

function toggleNavigation() {
  if (navOpen.value) closeNavigation()
  else void openNavigation()
}

function startLogout() {
  userMenuOpen.value = false
  logoutMutation.reset()
  logoutMutation.mutate()
}

function toggleUserMenu() {
  userMenuOpen.value = !userMenuOpen.value
}

function closeUserMenu({ restoreFocus = false } = {}) {
  if (!userMenuOpen.value) return
  userMenuOpen.value = false
  if (restoreFocus) void nextTick(() => userMenuButtonElement.value?.focus())
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" && userMenuOpen.value) {
    event.preventDefault()
    closeUserMenu({ restoreFocus: true })
    return
  }
  if (!isNarrowViewport.value || !navOpen.value) return
  if (event.key === "Escape") {
    event.preventDefault()
    closeNavigation()
    return
  }
  if (event.key !== "Tab") return
  const focusable = drawerFocusableElements()
  const first = focusable[0]
  const last = focusable.at(-1)
  if (!first || !last) return
  if (event.shiftKey && (document.activeElement === first || !sidebarElement.value?.contains(document.activeElement))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (document.activeElement === last || !sidebarElement.value?.contains(document.activeElement))) {
    event.preventDefault()
    first.focus()
  }
}

watch(() => route.fullPath, async () => {
  const userMenuWasOpen = userMenuOpen.value
  closeUserMenu()
  if (userMenuWasOpen) {
    await nextTick()
    contentElement.value?.focus()
  }
  if (!isNarrowViewport.value || !navOpen.value) return
  navOpen.value = false
  await nextTick()
  contentElement.value?.focus()
})

onMounted(() => {
  viewportQuery = window.matchMedia("(max-width: 860px)")
  updateViewport(viewportQuery)
  viewportQuery.addEventListener("change", updateViewport)
  window.addEventListener("keydown", onKeydown)
})
onBeforeUnmount(() => {
  viewportQuery?.removeEventListener("change", updateViewport)
  window.removeEventListener("keydown", onKeydown)
})
</script>

<template>
  <div class="app-shell">
    <aside
      id="primary-sidebar"
      ref="sidebarElement"
      data-testid="app-sidebar"
      class="app-sidebar"
      :class="{ 'app-sidebar-open': navOpen }"
      :aria-hidden="drawerClosed ? 'true' : undefined"
      :inert="drawerClosed ? '' : null"
    >
      <RouterLink class="brand-lockup" to="/" aria-label="SinofGear 首页">
        <span class="brand-mark" aria-hidden="true">SG</span>
        <span><strong>SinofGear</strong><small>AI 推广获客</small></span>
      </RouterLink>
      <nav aria-label="主导航">
        <section v-for="section in visibleNavigation" :key="section.group" class="nav-group">
          <h2 v-if="section.group">{{ section.group }}</h2>
          <RouterLink
            v-for="item in section.items"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            exact-active-class="nav-link-active"
          >
            <span class="nav-icon" aria-hidden="true"><AppIcon :name="item.icon" :size="18" /></span>
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>
      </nav>
      <nav class="sidebar-utilities" data-testid="sidebar-utilities" aria-label="账户与设置">
        <RouterLink
          v-for="item in utilityNavigation"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          exact-active-class="nav-link-active"
        >
          <span class="nav-icon" aria-hidden="true"><AppIcon :name="item.icon" :size="18" /></span>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
    </aside>
    <button
      v-if="navOpen && isNarrowViewport"
      class="nav-backdrop"
      type="button"
      tabindex="-1"
      aria-label="关闭导航遮罩"
      @click="closeNavigation()"
    />

    <div class="app-main">
      <header class="topbar">
        <div class="topbar-start">
          <button
            ref="menuButtonElement"
            class="menu-button"
            type="button"
            :aria-expanded="navOpen"
            aria-controls="primary-sidebar"
            :aria-label="navOpen ? '关闭导航' : '打开导航'"
            @click="toggleNavigation"
          >
            <AppIcon name="panel-left" :size="20" />
          </button>
          <span class="topbar-context">增长工作台</span>
        </div>
        <RouterLink
          v-if="canApprove"
          class="approval-badge"
          to="/agent-approvals"
          :aria-label="`待我审核 ${pendingApprovalCount}`"
        >
          <AppIcon name="circle-check" :size="18" />
          <span>待我审核</span> <strong>{{ pendingApprovalCount }}</strong>
        </RouterLink>
        <div v-if="currentUser.data.value" class="user-session">
          <div class="user-area">
            <div class="user-copy">
              <strong>{{ currentUser.data.value.organization.name }}</strong>
              <span>{{ currentUser.data.value.user.username }}</span>
            </div>
            <button
              ref="userMenuButtonElement"
              class="button button-quiet"
              type="button"
              aria-haspopup="menu"
              :aria-expanded="userMenuOpen"
              :aria-label="userMenuOpen ? '关闭用户菜单' : '打开用户菜单'"
              :disabled="logoutMutation.isPending.value"
              @click="toggleUserMenu"
            >
              设置与账户 <AppIcon name="chevron-down" :size="16" />
            </button>
            <div v-if="userMenuOpen" class="user-menu" role="menu" aria-label="用户菜单">
              <RouterLink role="menuitem" :to="{ path: '/settings', query: { from: route.fullPath } }">设置</RouterLink>
              <button
                role="menuitem"
                type="button"
                :disabled="logoutMutation.isPending.value"
                @click="startLogout"
              >
                <AppIcon name="log-out" :size="16" />
                {{ logoutMutation.isPending.value ? "正在退出…" : logoutError ? "重新退出" : "退出登录" }}
              </button>
            </div>
          </div>
          <div
            v-if="logoutError"
            class="logout-error"
            role="alert"
            aria-live="assertive"
          >
            <p>{{ logoutError.message }}</p>
            <p>{{ logoutError.recovery }}</p>
          </div>
        </div>
      </header>

      <main ref="contentElement" class="content-area" tabindex="-1">
        <p v-if="currentUser.isPending.value" class="state-message" role="status" aria-live="polite">
          正在确认登录状态…
        </p>
        <div v-else-if="currentUser.isError.value" class="card state-message state-error" role="alert">
          <h1>暂时无法打开工作台</h1>
          <p>请检查网络后刷新页面，或重新登录。</p>
          <RouterLink class="button button-primary" to="/login">返回登录</RouterLink>
        </div>
        <RouterView v-else />
      </main>
    </div>
  </div>
</template>
