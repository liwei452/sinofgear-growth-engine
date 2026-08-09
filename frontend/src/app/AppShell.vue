<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router"

import { ApiError } from "../api/client"
import { currentUserQueryOptions, logout } from "../modules/auth/auth"

const navigation = [
  { group: "工作台", items: [{ label: "首页", to: "/", icon: "首" }] },
  {
    group: "内容准备",
    items: [
      { label: "产品库", to: "/products", icon: "产" },
      { label: "知识库", to: "/knowledge", icon: "知" },
      { label: "素材库", to: "/assets", icon: "素" },
    ],
  },
  {
    group: "内容与审核",
    items: [
      { label: "AI 内容工厂", to: "/content-factory", icon: "AI" },
      { label: "审核中心", to: "/reviews", icon: "审" },
    ],
  },
  {
    group: "发布与增长",
    items: [
      { label: "发布日历", to: "/publishing-calendar", icon: "发" },
      { label: "平台账号", to: "/platform-accounts", icon: "账" },
      { label: "数据看板", to: "/analytics", icon: "数" },
    ],
  },
]

const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const currentUser = useQuery(currentUserQueryOptions())
const navOpen = ref(false)
const isNarrowViewport = ref(false)
const sidebarElement = ref<HTMLElement | null>(null)
const menuButtonElement = ref<HTMLButtonElement | null>(null)
const contentElement = ref<HTMLElement | null>(null)
const drawerClosed = computed(() => isNarrowViewport.value && !navOpen.value)
const pageTitle = computed(() => String(route.meta.title ?? "工作台"))
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
  logoutMutation.reset()
  logoutMutation.mutate()
}

function onKeydown(event: KeyboardEvent) {
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
        <span><strong>SinofGear</strong><small>增长引擎</small></span>
      </RouterLink>
      <nav aria-label="主导航">
        <section v-for="section in navigation" :key="section.group" class="nav-group">
          <h2>{{ section.group }}</h2>
          <RouterLink
            v-for="item in section.items"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            exact-active-class="nav-link-active"
          >
            <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>
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
            <span aria-hidden="true">☰</span>
          </button>
          <div>
            <p class="topbar-label">当前位置</p>
            <strong>{{ pageTitle }}</strong>
          </div>
        </div>
        <div v-if="currentUser.data.value" class="user-session">
          <div class="user-area">
            <div class="user-copy">
              <strong>{{ currentUser.data.value.organization.name }}</strong>
              <span>{{ currentUser.data.value.user.username }}</span>
            </div>
            <button
              class="button button-quiet"
              type="button"
              :disabled="logoutMutation.isPending.value"
              @click="startLogout"
            >
              {{ logoutMutation.isPending.value ? "正在退出…" : logoutError ? "重新退出" : "退出登录" }}
            </button>
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
