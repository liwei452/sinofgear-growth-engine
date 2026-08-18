<script setup lang="ts">
import { useMutation, useQuery } from "@tanstack/vue-query"
import { computed, ref } from "vue"
import { RouterLink } from "vue-router"

import AppIcon from "../../shared/components/AppIcon.vue"
import ContentWorkspaceNav from "../content/ContentWorkspaceNav.vue"
import {
  exportChannelPackage,
  growthWorkspaceQueryOptions,
  type ChannelPackage,
  type ManualPackageExport,
  type PlatformConnection,
} from "../growth/api"
import SocialChannelCard from "./SocialChannelCard.vue"

const channelDefinitions = [
  { code: "FACEBOOK", name: "Facebook", capability: "公开主页图文与链接内容" },
  { code: "INSTAGRAM", name: "Instagram", capability: "图片、短视频与 Reels 内容" },
  { code: "LINKEDIN", name: "LinkedIn", capability: "公司主页专业内容与链接" },
  { code: "TIKTOK", name: "TikTok", capability: "竖版短视频与字幕素材" },
  { code: "YOUTUBE", name: "YouTube", capability: "公开视频或人工上传包" },
] as const

const workspaceQuery = useQuery(growthWorkspaceQueryOptions())
const downloadNotice = ref("")
const downloadMutation = useMutation({
  mutationFn: exportChannelPackage,
  onSuccess: saveExport,
  onError: () => { downloadNotice.value = "发布包暂时无法下载，请确认内容已批准。" },
})

const realPackages = computed(() => (
  (workspaceQuery.data.value?.channel_packages ?? []).filter(item => !item.is_demo)
))
const readyPackages = computed(() => realPackages.value.filter(item => item.status === "APPROVED"))
const reviewPackages = computed(() => realPackages.value.filter(item => item.status !== "APPROVED"))
const recentBatches = computed(() => (
  (workspaceQuery.data.value?.publish_batches ?? []).filter(item => !item.is_demo).slice(0, 4)
))
const outcomes = computed(() => (
  (workspaceQuery.data.value?.metric_receipts ?? []).filter(item => !item.is_demo).slice(0, 5)
))

function connectionFor(code: string): PlatformConnection | undefined {
  return workspaceQuery.data.value?.connectors.find(item => item.channel === code)
}

function packageFor(code: string): ChannelPackage | undefined {
  return [...realPackages.value]
    .filter(item => item.channel === code)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0]
}

function cardState(code: string) {
  const connection = connectionFor(code)
  const channelPackage = packageFor(code)
  if (connection?.status === "CONNECTED") {
    return {
      status: "官方账号已连接",
      recovery: "发布仍需人工批准，并受平台能力限制。",
      tone: "ready" as const,
      actionLabel: "管理账号",
      actionTo: "/platform-accounts",
    }
  }
  if (connection?.status === "REAUTHORIZATION_REQUIRED") {
    return { status: "需要重新授权", recovery: connection.recovery_action || "请重新完成官方授权。", tone: "warning" as const, actionLabel: "重新授权", actionTo: "/platform-accounts" }
  }
  if (connection?.status === "WAITING_PLATFORM_REVIEW") {
    return { status: "等待平台审核", recovery: connection.recovery_action || "平台审核完成前可使用手工发布包。", tone: "warning" as const, actionLabel: "查看配置", actionTo: "/platform-accounts" }
  }
  if (connection?.status === "PRIVATE_ONLY") {
    return { status: "当前仅支持私密发布", recovery: connection.recovery_action || "公开发布能力尚未开放。", tone: "warning" as const, actionLabel: "查看限制", actionTo: "/platform-accounts" }
  }
  if (channelPackage?.status === "APPROVED") {
    return { status: "可下载手工发布包", recovery: "人工登录平台发布，不会调用发布接口。", tone: "neutral" as const, actionLabel: "下载发布包", actionTo: undefined }
  }
  return {
    status: "需要管理员完成平台配置",
    recovery: "无需在此输入平台密码；也可先准备手工发布包。",
    tone: "neutral" as const,
    actionLabel: "查看配置指引",
    actionTo: "/settings",
  }
}

function packageTitle(channelPackage: ChannelPackage): string {
  const title = channelPackage.payload.title
  return typeof title === "string" && title ? title : `${channelPackage.channel} 内容包`
}

function saveExport(exported: ManualPackageExport): void {
  downloadNotice.value = `发布包已下载：${exported.filename}。未触发任何平台发布请求。`
  const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json;charset=utf-8" })
  if (typeof URL.createObjectURL !== "function") return
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = objectUrl
  anchor.download = exported.filename
  anchor.click()
  URL.revokeObjectURL(objectUrl)
}

function downloadFor(code: string): void {
  const channelPackage = packageFor(code)
  if (!channelPackage || channelPackage.status !== "APPROVED") return
  downloadMutation.mutate(channelPackage.id)
}
</script>

<template>
  <main class="social-operations-page">
    <header class="social-hero">
      <div>
        <p class="eyebrow">SOCIAL OPERATIONS</p>
        <h1>社媒运营</h1>
        <p>先看渠道是否可用，再处理待发布内容、审核和排期；没有官方接口时继续使用手工发布包。</p>
      </div>
      <span class="hero-icon"><AppIcon name="send" :size="26" /></span>
    </header>

    <ContentWorkspaceNav active="social" />
    <p v-if="downloadNotice" class="notice" role="status">{{ downloadNotice }}</p>
    <p v-if="workspaceQuery.isLoading.value" class="operation-card">正在读取社媒工作区…</p>
    <p v-else-if="workspaceQuery.isError.value" class="operation-card error" role="alert">社媒工作区暂时无法读取。</p>

    <template v-else>
      <section class="channel-section" aria-labelledby="channel-readiness-title">
        <div class="section-heading">
          <div><p class="eyebrow">渠道就绪度</p><h2 id="channel-readiness-title">五个渠道始终可见</h2></div>
          <span>5 个渠道</span>
        </div>
        <div class="channel-grid">
          <SocialChannelCard
            v-for="channel in channelDefinitions"
            :key="channel.code"
            :name="channel.name"
            :status="cardState(channel.code).status"
            :capability="channel.capability"
            :recovery="cardState(channel.code).recovery"
            :tone="cardState(channel.code).tone"
            :action-label="cardState(channel.code).actionLabel"
            :action-to="cardState(channel.code).actionTo"
            @action="downloadFor(channel.code)"
          />
        </div>
      </section>

      <div class="operations-grid">
        <div class="operations-main">
          <section class="operation-card" aria-labelledby="ready-title">
            <div class="section-heading"><h2 id="ready-title">今天可处理的内容</h2><span>{{ readyPackages.length }}</span></div>
            <ul v-if="readyPackages.length" class="content-list">
              <li v-for="item in readyPackages.slice(0, 5)" :key="item.id">
                <div><strong>{{ packageTitle(item) }}</strong><small>{{ item.channel }} · 已批准</small></div>
                <button type="button" :disabled="downloadMutation.isPending.value" @click="downloadMutation.mutate(item.id)">下载发布包</button>
              </li>
            </ul>
            <div v-else class="empty-state"><p>当前没有已批准、可发布的内容。</p><RouterLink to="/content-factory">创建内容</RouterLink></div>
          </section>

          <section class="operation-card" aria-labelledby="review-title">
            <div class="section-heading"><h2 id="review-title">等待内容审核</h2><span>{{ reviewPackages.length }}</span></div>
            <ul v-if="reviewPackages.length" class="content-list">
              <li v-for="item in reviewPackages.slice(0, 5)" :key="item.id"><div><strong>{{ packageTitle(item) }}</strong><small>{{ item.channel }} · 等待人工确认</small></div></li>
            </ul>
            <div v-else class="empty-state"><p>没有等待审核的社媒内容。</p><RouterLink to="/reviews">进入审核中心</RouterLink></div>
          </section>
        </div>

        <aside class="operations-side" aria-label="社媒任务与结果">
          <section class="operation-card">
            <div class="section-heading"><h2>排期与最近任务</h2><span>{{ recentBatches.length }}</span></div>
            <ul v-if="recentBatches.length" class="compact-list"><li v-for="batch in recentBatches" :key="batch.id"><strong>{{ batch.status }}</strong><small>{{ new Date(batch.updated_at).toLocaleString() }}</small></li></ul>
            <div v-else class="empty-state"><p>还没有真实发布任务。</p><RouterLink to="/publishing-calendar">打开发布日历</RouterLink></div>
          </section>
          <section class="operation-card">
            <div class="section-heading"><h2>已记录结果</h2><span>{{ outcomes.length }}</span></div>
            <ul v-if="outcomes.length" class="compact-list"><li v-for="item in outcomes" :key="item.id"><strong>{{ item.channel }}</strong><small>{{ new Date(item.updated_at).toLocaleDateString() }} · 已回填</small></li></ul>
            <p v-else class="empty-copy">尚未记录渠道效果，不展示虚构数据。</p>
          </section>
        </aside>
      </div>
    </template>
  </main>
</template>

<style scoped>
.social-operations-page { display: grid; gap: 18px; }
.social-hero { display: flex; align-items: center; justify-content: space-between; gap: 18px; border: 1px solid #cfe7ff; border-radius: 20px; background: linear-gradient(115deg, #fff 0%, #eaf5ff 100%); padding: 23px 25px; }
.social-hero h1 { margin: 4px 0 7px; color: var(--sg-ink); }
.social-hero p:last-child { max-width: 760px; margin: 0; color: var(--sg-muted); font-size: .8rem; line-height: 1.55; }
.hero-icon { display: grid; width: 54px; height: 54px; flex: 0 0 auto; place-items: center; border-radius: 16px; background: var(--sg-brand); color: #fff; box-shadow: 0 10px 24px rgb(22 135 255 / 22%); }
.eyebrow { margin: 0; color: var(--sg-brand); font-size: .64rem; font-weight: 900; letter-spacing: .1em; }
.channel-section { display: grid; gap: 12px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.section-heading h2 { margin: 3px 0 0; color: var(--sg-ink); font-size: .98rem; }
.section-heading > span { display: grid; min-width: 25px; height: 25px; place-items: center; border-radius: 999px; background: var(--sg-brand-soft); color: var(--sg-brand-strong); font-size: .67rem; font-weight: 850; }
.channel-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 11px; }
.operations-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); gap: 14px; align-items: start; }
.operations-main, .operations-side { display: grid; gap: 14px; }
.operation-card { display: grid; gap: 13px; margin: 0; border: 1px solid var(--sg-line); border-radius: 17px; background: #fff; padding: 18px; box-shadow: var(--sg-shadow-sm); }
.content-list, .compact-list { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }
.content-list li { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-top: 1px solid var(--sg-line); padding: 12px 0; }
.content-list li > div, .compact-list li { display: grid; gap: 4px; }
.content-list strong, .compact-list strong { color: var(--sg-ink); font-size: .76rem; }
.content-list small, .compact-list small, .empty-copy { color: var(--sg-muted); font-size: .68rem; }
.content-list button { border: 0; background: var(--sg-brand-soft); padding: 7px 9px; color: var(--sg-brand-strong); font: inherit; font-size: .68rem; font-weight: 850; cursor: pointer; }
.compact-list li { border-top: 1px solid var(--sg-line); padding: 10px 0; }
.empty-state { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-radius: 11px; background: #f8fbff; padding: 12px; }
.empty-state p, .empty-copy { margin: 0; }
.empty-state a { color: var(--sg-brand-strong); font-size: .71rem; font-weight: 850; text-decoration: none; }
.notice { margin: 0; border-radius: 10px; background: #e9fbf4; padding: 10px 13px; color: #19795b; font-size: .75rem; }
.error { color: var(--sg-danger); }
@media (max-width: 1180px) { .channel-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 900px) { .operations-grid { grid-template-columns: 1fr; } }
@media (max-width: 680px) { .channel-grid { grid-template-columns: 1fr; }.social-hero { align-items: flex-start; padding: 19px; } }
</style>
