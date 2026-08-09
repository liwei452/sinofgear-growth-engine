<script setup lang="ts">
import { useMutation, useQueryClient } from "@tanstack/vue-query"
import { ref } from "vue"
import { useRoute, useRouter } from "vue-router"

import { safeRedirect } from "../../app/router"
import { currentUserQueryOptions, login } from "./auth"

const username = ref("")
const password = ref("")
const failure = ref("")
const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()

const loginMutation = useMutation({
  mutationFn: login,
  onMutate: () => {
    failure.value = ""
    queryClient.removeQueries()
  },
  onError: () => {
    failure.value = "用户名或密码不正确，请重试。"
  },
  onSuccess: async () => {
    await queryClient.fetchQuery(currentUserQueryOptions())
    await router.replace(safeRedirect(route.query.redirect))
  },
})

function submit() {
  loginMutation.mutate({ username: username.value, password: password.value })
}
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <div class="login-brand" aria-hidden="true">SG</div>
      <p class="eyebrow">欢迎回来</p>
      <h1 id="login-title">SinofGear 增长引擎</h1>
      <p class="login-promise">把内容、发布和增长数据放在一个清楚的工作台里。</p>

      <form class="login-form" :aria-busy="loginMutation.isPending.value" @submit.prevent="submit">
        <div class="field">
          <label for="username">用户名</label>
          <input
            id="username"
            v-model="username"
            name="username"
            autocomplete="username"
            required
            :disabled="loginMutation.isPending.value"
          />
        </div>
        <div class="field">
          <label for="password">密码</label>
          <input
            id="password"
            v-model="password"
            name="password"
            type="password"
            autocomplete="current-password"
            required
            :disabled="loginMutation.isPending.value"
          />
        </div>
        <p v-if="failure" class="form-error" role="alert">{{ failure }}</p>
        <button class="button button-primary button-block" type="submit" :disabled="loginMutation.isPending.value">
          {{ loginMutation.isPending.value ? "正在登录…" : "登录" }}
        </button>
      </form>
      <p class="login-help">登录后，我们会从最清楚的下一步开始。</p>
    </section>
  </main>
</template>
