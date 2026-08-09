<script setup lang="ts">
import NextStepPanel, { type NextStep } from "../../shared/components/NextStepPanel.vue"

const steps: NextStep[] = [
  { title: "添加第一个产品", description: "先让系统知道你要推广什么。" },
  { title: "整理品牌知识", description: "补充受众、卖点和表达边界。" },
  { title: "准备可用素材", description: "上传图片或视频，后续生成会更顺手。" },
]
</script>

<template>
  <div class="page-stack dashboard-page">
    <section class="welcome-panel" aria-labelledby="dashboard-title">
      <p class="eyebrow">今天的工作台</p>
      <h1 id="dashboard-title">先完成一件最重要的事</h1>
      <p>不用一次学会所有功能。跟着建议走，逐步搭好你的增长基础。</p>
    </section>
    <NextStepPanel :steps="steps" />
  </div>
</template>
