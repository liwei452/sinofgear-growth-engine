<script setup lang="ts">
import { RouterLink } from "vue-router"

export type NextStep = { title: string; description: string }

withDefaults(defineProps<{
  state?: "loading" | "ready" | "error"
  steps: NextStep[]
}>(), { state: "ready" })

defineEmits<{ retry: [] }>()
</script>

<template>
  <section id="next-steps" class="card next-step-card" aria-labelledby="next-step-title">
    <div class="section-heading">
      <div>
        <p class="eyebrow">从这里开始</p>
        <h2 id="next-step-title">下一步建议</h2>
      </div>
      <span class="step-badge">新手引导</span>
    </div>

    <p v-if="state === 'loading'" class="state-message" role="status" aria-live="polite">
      正在准备适合你的下一步…
    </p>
    <div v-else-if="state === 'error'" class="state-message state-error" role="alert">
      <p>建议加载失败，请稍后重试。</p>
      <button class="button button-secondary" type="button" @click="$emit('retry')">重新加载</button>
    </div>
    <p v-else-if="steps.length === 0" class="state-message" role="status">
      暂时没有待办事项，你可以安心探索工作台。
    </p>
    <template v-else>
      <ol class="step-list">
        <li v-for="(step, index) in steps" :key="step.title" class="step-item">
          <span class="step-number" aria-hidden="true">{{ index + 1 }}</span>
          <div>
            <h3>{{ step.title }}</h3>
            <p>{{ step.description }}</p>
          </div>
        </li>
      </ol>
      <RouterLink class="button button-primary" to="/products">先添加产品</RouterLink>
    </template>
  </section>
</template>
