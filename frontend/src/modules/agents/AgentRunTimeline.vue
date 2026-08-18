<script setup lang="ts">
import { computed, ref } from "vue"

import AppIcon from "../../shared/components/AppIcon.vue"
import type { AgentRun, AgentRunStep } from "../growth/agentApi"

const props = defineProps<{ run: AgentRun; busy?: boolean }>()
defineEmits<{ approve: []; reject: [] }>()

const technicalOpen = ref(false)
const modeLabels = {
  AI_AGENT: "AI Agent",
  AI_GENERATION: "AI 生成任务",
  AUTOMATION: "自动化流程",
}
const outcomeLabels: Record<string, string> = {
  succeeded: "已完成",
  blocked_approval: "等待你批准",
  failed: "需要处理",
  drafted: "草稿已准备",
}
const toolLabels: Record<string, string> = {
  discover_maps_candidates: "发现潜在客户",
  enrich_candidate: "整理客户公开信息",
  website_enrich_candidate: "分析客户网站",
  verify_candidate_contacts: "核验联系人信息",
  add_to_follow_up: "加入人工跟进",
  draft_outreach: "准备开发信草稿",
  send_email: "发送已批准消息",
  analyze_content_opportunities: "分析市场与内容机会",
  create_content_brief: "准备内容需求",
  enrich_content_brief: "完善内容依据",
  mark_content_brief_ready: "提交内容生成准备",
  trigger_master_generation: "发起 AI 内容生成",
  create_platform_variants: "创建平台内容变体",
  analyze_post_performance: "汇总社媒表现",
  propose_publish_calendar: "制定社媒排期建议",
  schedule_social_post: "安排社媒发布",
}

const modeLabel = computed(() => modeLabels[props.run.execution_mode ?? "AUTOMATION"])
const modelIdentity = computed(() => (
  props.run.execution_mode === "AI_AGENT"
    ? [props.run.planner_provider, props.run.planner_model].filter(Boolean).join(" · ")
    : ""
))

function stepLabel(step: AgentRunStep): string {
  return toolLabels[step.tool_name ?? ""] ?? "处理业务步骤"
}

function onTechnicalToggle(event: Event): void {
  technicalOpen.value = (event.currentTarget as HTMLDetailsElement).open
}
</script>

<template>
  <article class="run-timeline" :aria-label="run.goal">
    <header>
      <div>
        <span class="mode-badge" :class="`mode-${run.execution_mode?.toLowerCase() ?? 'automation'}`">{{ modeLabel }}</span>
        <h3>{{ run.goal }}</h3>
        <p v-if="modelIdentity">{{ modelIdentity }}</p>
      </div>
      <time :datetime="run.updated_at">{{ new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(run.updated_at)) }}</time>
    </header>

    <ol v-if="run.steps.length" class="business-steps">
      <li v-for="step in run.steps" :key="step.index" :class="`outcome-${step.outcome}`">
        <span class="step-marker"><AppIcon :name="step.outcome === 'blocked_approval' ? 'calendar-clock' : step.outcome === 'failed' ? 'inbox' : 'circle-check'" :size="16" /></span>
        <div>
          <strong>{{ stepLabel(step) }}</strong>
          <small>{{ outcomeLabels[step.outcome] ?? step.outcome }}</small>
        </div>
      </li>
    </ol>
    <p v-else class="run-empty">该任务还没有生成执行步骤。</p>

    <section v-if="run.status === 'WAITING_APPROVAL'" class="approval-step">
      <div>
        <strong>下一步需要你的决定</strong>
        <p>{{ run.pending_approval?.reasoning || "对外或写入动作必须先经过人工批准。" }}</p>
      </div>
      <div>
        <button class="button button-primary" type="button" :disabled="busy" @click="$emit('approve')">批准执行</button>
        <button class="button button-quiet" type="button" :disabled="busy" @click="$emit('reject')">拒绝</button>
      </div>
    </section>

    <details class="technical-record" @toggle="onTechnicalToggle">
      <summary>技术记录</summary>
      <div v-if="technicalOpen" class="technical-content">
        <p>运行 ID：<code>{{ run.id }}</code></p>
        <ol>
          <li v-for="step in run.steps" :key="step.index">
            <strong>{{ step.tool_name || "未命名工具" }}</strong>
            <code>{{ JSON.stringify(step.args) }}</code>
            <p v-if="step.reasoning">{{ step.reasoning }}</p>
            <p v-if="step.error" class="error">{{ step.error }}</p>
          </li>
        </ol>
      </div>
    </details>
  </article>
</template>

<style scoped>
.run-timeline { display: grid; gap: 16px; border: 1px solid var(--sg-line); border-radius: 18px; background: #fff; padding: 20px; box-shadow: var(--sg-shadow-sm); }
.run-timeline > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.run-timeline h3 { margin: 8px 0 3px; color: var(--sg-ink); font-size: .97rem; }
.run-timeline header p, .run-timeline time { margin: 0; color: var(--sg-muted); font-size: .69rem; }
.mode-badge { display: inline-flex; border-radius: 999px; background: var(--sg-brand-soft); padding: 4px 8px; color: var(--sg-brand-strong); font-size: .65rem; font-weight: 850; }
.mode-ai_generation { background: #eeeaff; color: #6b51c9; }
.mode-automation { background: #eef3f7; color: #557086; }
.business-steps { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }
.business-steps li { position: relative; display: grid; grid-template-columns: 32px 1fr; gap: 10px; min-height: 42px; }
.business-steps li:not(:last-child)::after { content: ""; position: absolute; left: 15px; top: 27px; bottom: 0; width: 2px; background: var(--sg-line); }
.step-marker { z-index: 1; display: grid; width: 30px; height: 30px; place-items: center; border-radius: 50%; background: #e9fbf4; color: var(--sg-success); }
.outcome-blocked_approval .step-marker { background: #fff3df; color: #bd730e; }
.outcome-failed .step-marker { background: #fff0f0; color: var(--sg-danger); }
.business-steps div { display: grid; align-content: start; gap: 3px; padding: 5px 0 12px; }
.business-steps strong { color: var(--sg-ink); font-size: .78rem; }
.business-steps small { color: var(--sg-muted); font-size: .68rem; }
.approval-step { display: flex; align-items: center; justify-content: space-between; gap: 14px; border: 1px solid #ffe0af; border-radius: 13px; background: #fff9ef; padding: 13px; }
.approval-step p { margin: 4px 0 0; color: var(--sg-muted); font-size: .72rem; }
.approval-step > div:last-child { display: flex; gap: 8px; flex: 0 0 auto; }
.technical-record { border-top: 1px solid var(--sg-line); padding-top: 12px; color: var(--sg-muted); font-size: .7rem; }
.technical-record summary { cursor: pointer; color: var(--sg-muted); font-weight: 800; }
.technical-content ol { display: grid; gap: 10px; padding-left: 18px; }
.technical-content li { display: grid; gap: 4px; }
.technical-content code { overflow-wrap: anywhere; white-space: pre-wrap; }
.technical-content p, .run-empty { margin: 0; color: var(--sg-muted); }
.error { color: var(--sg-danger) !important; }
@media (max-width: 640px) { .approval-step { align-items: stretch; flex-direction: column; }.approval-step > div:last-child { flex-wrap: wrap; }.run-timeline > header { flex-direction: column; } }
</style>
