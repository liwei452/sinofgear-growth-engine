<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router"

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
const pageTitle = computed(() => String(route.meta.title ?? "工作台"))
const logoutMutation = useMutation({
  mutationFn: logout,
  onSuccess: async () => {
    queryClient.removeQueries({ queryKey: ["auth", "me"] })
    await router.replace("/login")
  },
})

function closeNavigation() {
  navOpen.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") closeNavigation()
}

onMounted(() => window.addEventListener("keydown", onKeydown))
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown))
</script>

<template>
  <div class="app-shell">
    <aside
      id="primary-sidebar"
      data-testid="app-sidebar"
      class="app-sidebar"
      :class="{ 'app-sidebar-open': navOpen }"
    >
      <RouterLink class="brand-lockup" to="/" aria-label="SinofGear 首页" @click="closeNavigation">
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
            @click="closeNavigation"
          >
            <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>
      </nav>
    </aside>
    <button v-if="navOpen" class="nav-backdrop" type="button" aria-label="关闭导航遮罩" @click="closeNavigation" />

    <div class="app-main">
      <header class="topbar">
        <div class="topbar-start">
          <button
            class="menu-button"
            type="button"
            :aria-expanded="navOpen"
            aria-controls="primary-sidebar"
            :aria-label="navOpen ? '关闭导航' : '打开导航'"
            @click="navOpen = !navOpen"
          >
            <span aria-hidden="true">☰</span>
          </button>
          <div>
            <p class="topbar-label">当前位置</p>
            <strong>{{ pageTitle }}</strong>
          </div>
        </div>
        <div v-if="currentUser.data.value" class="user-area">
          <div class="user-copy">
            <strong>{{ currentUser.data.value.organization.name }}</strong>
            <span>{{ currentUser.data.value.user.username }}</span>
          </div>
          <button
            class="button button-quiet"
            type="button"
            :disabled="logoutMutation.isPending.value"
            @click="logoutMutation.mutate()"
          >
            {{ logoutMutation.isPending.value ? "正在退出…" : "退出登录" }}
          </button>
        </div>
      </header>

      <main class="content-area">
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
