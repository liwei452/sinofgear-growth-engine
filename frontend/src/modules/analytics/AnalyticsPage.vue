<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"

import { ApiError } from "../../api/client"
import AppIcon from "../../shared/components/AppIcon.vue"
import NextStepPanel from "../../shared/components/NextStepPanel.vue"
import OperationModal from "../../shared/components/OperationModal.vue"
import StatusBadge from "../../shared/components/StatusBadge.vue"
import { ordinaryPlatform } from "../../shared/presentation/ordinary"
import { currentUserQueryOptions } from "../auth/auth"
import {
  contentQueryKeys,
  getCursorPage,
  getBrief,
  getMasterContent,
  getPlatformContent,
  listCampaigns,
  listPlatforms,
  safeCursorUrl,
} from "../content/api"
import { getPublishTask, getPublishTaskPage, listPublishTasks } from "../publishing/api"
import { getProductPage, listProducts, safeProductPageUrl } from "../products/api"
import {
  analyticsKeys,
  createShortLink,
  createTrackingLink,
  getChannelSummary,
  getChannelSummaryPage,
  getShortPage,
  getTrackingPage,
  listShortLinks,
  listTrackingLinks,
} from "./api"

const iso = (date: Date) => {
  const two = (value: number) => String(value).padStart(2, "0")
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}`
}

const today = new Date()
const startDefault = new Date(today.getTime() - 29 * 86400000)
const start = ref(iso(startDefault))
const end = ref(iso(today))
const campaign = ref("")
const platform = ref("")
const product = ref("")
const country = ref("")
const summaryUrl = ref<string | null>(null)
const trackingUrl = ref<string | null>(null)
const shortUrl = ref<string | null>(null)
const publishedUrl = ref<string | null>(null)
const message = ref("")
const operationsOpen = ref(false)
const client = useQueryClient()
const user = useQuery(currentUserQueryOptions())
const createOpen = ref(false)
const taskId = ref("")
const productId = ref("")
const utmSource = ref("")
const utmMedium = ref("social")
const utmCampaign = ref("")
const org = computed(() => user.data.value?.organization.id ?? "")
const permissions = computed(() => user.data.value?.membership.permissions ?? [])
const has = (permission: string) => permissions.value.includes(permission)
const canRead = computed(() => has("tracking.read"))
const canManage = computed(() => has("tracking.manage"))
const enabled = computed(() => Boolean(org.value) && canRead.value)
const filters = computed(() => ({
  start: start.value,
  end: end.value,
  campaign: campaign.value,
  platform: platform.value,
  product: product.value,
  country: country.value.toUpperCase(),
  limit: "20",
  offset: "0",
}))

const summary = useQuery({
  queryKey: computed(() => [...analyticsKeys.summary(org.value, filters.value), summaryUrl.value]),
  queryFn: () => summaryUrl.value
    ? getChannelSummaryPage(summaryUrl.value)
    : getChannelSummary(filters.value),
  enabled,
})
const tracking = useQuery({
  queryKey: computed(() => [...analyticsKeys.tracking(org.value), trackingUrl.value]),
  queryFn: () => trackingUrl.value ? getTrackingPage(trackingUrl.value) : listTrackingLinks(),
  enabled,
})
const shorts = useQuery({
  queryKey: computed(() => [...analyticsKeys.short(org.value), shortUrl.value]),
  queryFn: () => shortUrl.value ? getShortPage(shortUrl.value) : listShortLinks(),
  enabled,
})
const published = useQuery({
  queryKey: computed(() => [...analyticsKeys.all(org.value), "published", publishedUrl.value]),
  queryFn: () => publishedUrl.value ? getPublishTaskPage(publishedUrl.value) : listPublishTasks(),
  enabled: computed(() => enabled.value && canManage.value),
})

const MAX_NAME_PAGES = 100

function normalizedCursorKey(value: string): string {
  const target = new URL(value, window.location.origin)
  target.searchParams.sort()
  const query = target.searchParams.toString()
  return `${target.pathname}${query ? `?${query}` : ""}`
}

async function loadAllCampaigns(signal: AbortSignal) {
  let page = await listCampaigns({ signal })
  const values = [...page.results]
  const visited = new Set<string>()
  let loadedPages = 1
  while (page.next && loadedPages < MAX_NAME_PAGES) {
    const next = safeCursorUrl(page.next, "/api/v1/campaigns")
    if (!next) break
    const cursorKey = normalizedCursorKey(next)
    if (visited.has(cursorKey)) break
    visited.add(cursorKey)
    page = await getCursorPage(next, "/api/v1/campaigns", { signal })
    values.push(...page.results)
    loadedPages += 1
  }
  return values
}

async function loadAllProducts(signal: AbortSignal) {
  let page = await listProducts({}, { signal })
  const values = [...page.results]
  const visited = new Set<string>()
  let loadedPages = 1
  while (page.next && loadedPages < MAX_NAME_PAGES) {
    const next = safeProductPageUrl(page.next)
    if (!next) break
    const cursorKey = normalizedCursorKey(next)
    if (visited.has(cursorKey)) break
    visited.add(cursorKey)
    page = await getProductPage(next, { signal })
    values.push(...page.results)
    loadedPages += 1
  }
  return values
}

const campaigns = useQuery({
  queryKey: computed(() => [...analyticsKeys.all(org.value), "names", "campaigns"]),
  queryFn: ({ signal }) => loadAllCampaigns(signal),
  enabled: computed(() => enabled.value && has("campaigns.read")),
})
const platforms = useQuery({
  queryKey: computed(() => contentQueryKeys.platforms(org.value)),
  queryFn: listPlatforms,
  enabled: computed(() => enabled.value && has("memberships.read")),
})
const products = useQuery({
  queryKey: computed(() => [...analyticsKeys.all(org.value), "names", "products"]),
  queryFn: ({ signal }) => loadAllProducts(signal),
  enabled: computed(() => enabled.value && has("products.read")),
})

const campaignNames = computed(() => new Map(
  (campaigns.data.value ?? []).map((item) => [item.id, item.name]),
))
const platformNames = computed(() => new Map(
  (platforms.data.value ?? []).map((item) => [item.id, item.name || ordinaryPlatform(item.code)]),
))
const productNames = computed(() => new Map(
  (products.data.value ?? []).map((item) => [
    item.id,
    item.name_zh?.trim() || item.name_en?.trim() || "名称暂不可用",
  ]),
))
const displayCampaign = (id: string) => campaignNames.value.get(id) || "名称暂不可用"
const displayPlatform = (id: string) => platformNames.value.get(id) || "名称暂不可用"
const displayProduct = (id: string) => productNames.value.get(id) || "名称暂不可用"
const publishedTasks = computed(() => published.data.value?.results.filter((task) => Boolean(task.published_post)) ?? [])

const rows = computed(() => summary.data.value?.results ?? [])
const hasCompleteSummary = computed(() => Boolean(summary.data.value)
  && !summary.data.value?.next
  && !summary.data.value?.previous
  && (summary.data.value?.count ?? 0) <= rows.value.length)
const platformCount = computed(() => new Set(rows.value.map((row) => row.platform_id)).size)
const countryCount = computed(() => new Set(rows.value.map((row) => row.country).filter(Boolean)).size)
const trendRows = computed(() => {
  const totals = new Map<string, number>()
  for (const row of rows.value) totals.set(row.date, (totals.get(row.date) ?? 0) + row.clicks)
  return [...totals].sort(([left], [right]) => left.localeCompare(right))
    .map(([date, clicks]) => ({ date, clicks }))
})
const maxClicks = computed(() => Math.max(1, ...trendRows.value.map((row) => row.clicks)))
const comparablePlatforms = computed(() => {
  if (!hasCompleteSummary.value) return []
  const dates = new Map<string, Set<string>>()
  const totals = new Map<string, number>()
  for (const row of rows.value) {
    const knownDates = dates.get(row.platform_id) ?? new Set<string>()
    knownDates.add(row.date)
    dates.set(row.platform_id, knownDates)
    totals.set(row.platform_id, (totals.get(row.platform_id) ?? 0) + row.clicks)
  }
  if (dates.size < 2 || [...dates.values()].some((value) => value.size < 2)) return []
  const dateSignatures = [...dates.values()].map((value) => [...value].sort().join("|"))
  if (new Set(dateSignatures).size !== 1) return []
  return [...totals].sort((left, right) => right[1] - left[1])
})
const conclusion = computed(() => {
  if (!rows.value.length) return "当前筛选没有点击数据，还不能形成效果结论。先检查日期和追踪链接是否覆盖了真实发布。"
  if (!comparablePlatforms.value.length) {
    return "数据还不足以判断哪个平台效果最好，也不能据此判断点击变化的原因。先积累至少两个平台、多个日期的可比较点击数据。"
  }
  if (comparablePlatforms.value.length > 1 && comparablePlatforms.value[0][1] === comparablePlatforms.value[1][1]) {
    return "最高点击数并列，暂无唯一领先平台；无法区分并列平台哪个表现更高，也不能据此判断点击变化的原因。"
  }
  const [leading] = comparablePlatforms.value
  return `在当前筛选的可比较点击数据中，${displayPlatform(leading[0])}记录的点击数较高。这只是已有点击汇总，不能据此判断点击变化的原因。`
})
const nextExplanation = computed(() => rows.value.length
  ? "打开运营详情检查筛选条件和追踪覆盖，再决定是否扩大投放或调整内容。"
  : "打开运营详情调整日期，或为已发布内容补充追踪链接。")

async function loadProvenance(id: string) {
  const task = await getPublishTask(id)
  if (!task.published_post) throw new ApiError(0, "请选择已发布的内容。")
  const platformContent = await getPlatformContent(task.platform_content_id)
  const master = await getMasterContent(platformContent.master_content_id)
  const brief = await getBrief(master.brief_id)
  if (!brief.product_ids.length || !brief.landing_page_url) {
    throw new ApiError(0, "内容来源缺少产品或落地页，无法创建追踪链接。")
  }
  return { task, brief, productIds: brief.product_ids }
}

const provenance = useQuery({
  queryKey: computed(() => [...analyticsKeys.all(org.value), "provenance", taskId.value]),
  queryFn: () => loadProvenance(taskId.value),
  enabled: computed(() => enabled.value && canManage.value && Boolean(taskId.value)),
})
watch(() => provenance.data.value?.productIds, (ids) => {
  productId.value = ids?.length === 1 ? ids[0] : ""
})
const short = useMutation({
  mutationFn: (id: string) => {
    if (!canManage.value) throw new ApiError(403, "没有管理追踪链接的权限。")
    return createShortLink(id, crypto.randomUUID())
  },
  onSuccess: async () => {
    message.value = "短链接已创建。"
    await client.invalidateQueries({ queryKey: analyticsKeys.short(org.value) })
  },
})
const create = useMutation({
  mutationFn: async () => {
    if (!canManage.value) throw new ApiError(403, "没有创建追踪链接的权限。")
    const fresh = await loadProvenance(taskId.value)
    if (!fresh.productIds.includes(productId.value)) {
      throw new ApiError(0, "所选产品不属于当前内容来源，请重新选择。")
    }
    return createTrackingLink({
      destination: fresh.brief.landing_page_url,
      utm_source: utmSource.value,
      utm_medium: utmMedium.value,
      utm_campaign: utmCampaign.value,
      campaign_id: fresh.brief.campaign_id,
      platform_id: fresh.task.platform_id,
      product_id: productId.value,
      published_post_id: fresh.task.published_post!.id,
    }, crypto.randomUUID())
  },
  onSuccess: async () => {
    closeCreate()
    message.value = "追踪链接已创建。"
    await client.invalidateQueries({ queryKey: analyticsKeys.tracking(org.value) })
  },
})

const err = (value: unknown) => value instanceof ApiError
  ? value.userMessage
  : "分析数据暂时无法加载，请稍后重试。"
async function copy(value: string) {
  try {
    await navigator.clipboard.writeText(value)
    message.value = "已复制链接。"
  } catch {
    message.value = "复制失败，请手动选择链接。"
  }
}
function reset() {
  start.value = iso(startDefault)
  end.value = iso(today)
  campaign.value = ""
  platform.value = ""
  product.value = ""
  country.value = ""
}
function closeCreate() {
  createOpen.value = false
  taskId.value = ""
  productId.value = ""
  utmSource.value = ""
  utmMedium.value = "social"
  utmCampaign.value = ""
}
function syncOperationsOpen(event: Event) {
  operationsOpen.value = (event.currentTarget as HTMLDetailsElement).open
}
watch([start, end, campaign, platform, product, country], () => { summaryUrl.value = null })
watch(org, () => {
  summaryUrl.value = null
  trackingUrl.value = null
  shortUrl.value = null
  publishedUrl.value = null
  operationsOpen.value = false
  closeCreate()
})
</script>

<template>
  <main class="page-stack analytics-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">AI 效果解读</p>
        <h1>效果</h1>
        <p>先看结论与趋势，需要时再展开筛选、追踪链接和发布记录。</p>
      </div>
      <button v-if="canManage" class="primary-action" type="button" @click="createOpen = true">创建追踪链接</button>
    </header>

    <section v-if="!canRead" class="panel" role="alert">
      <h2>没有分析权限</h2>
      <p>需要分析查看权限才能查看此页面。</p>
    </section>

    <template v-else>
      <p v-if="message" role="status">{{ message }}</p>

      <section class="panel conclusion-panel" role="region" aria-label="AI 结论">
        <div class="section-title"><AppIcon name="sparkles" /><h2>AI 结论</h2></div>
        <p v-if="summary.isPending.value" role="status">正在读取效果数据…</p>
        <div v-else-if="summary.isError.value" role="alert">
          <strong>分析数据没有加载成功</strong>
          <p>{{ err(summary.error.value) }}</p>
          <button type="button" @click="summary.refetch()">重新加载分析数据</button>
        </div>
        <template v-else>
          <StatusBadge :tone="rows.length ? 'brand' : 'neutral'" :label="rows.length ? '基于当前点击数据' : '等待数据'" />
          <p class="conclusion-copy">{{ conclusion }}</p>
        </template>
      </section>

      <section class="panel" role="region" aria-label="关键指标">
        <div class="section-heading"><h2>关键指标</h2><span>总量覆盖筛选范围；分类数来自当前页</span></div>
        <p v-if="summary.isPending.value" role="status">正在计算关键指标…</p>
        <p v-else-if="summary.isError.value" class="muted">关键指标暂不可用，请先重试结论数据。</p>
        <div v-else class="metric-grid">
          <article aria-label="总点击数"><span>总点击数</span><strong>{{ summary.data.value?.total_clicks ?? 0 }}</strong><small>符合当前条件</small></article>
          <article><span>统计记录</span><strong>{{ summary.data.value?.count ?? rows.length }}</strong><small>聚合数据行</small></article>
          <article><span>当前页涉及平台</span><strong>{{ platformCount }}</strong><small>按平台标识去重</small></article>
          <article><span>当前页涉及国家或地区</span><strong>{{ countryCount }}</strong><small>按国家代码去重</small></article>
        </div>
      </section>

      <section class="panel" role="region" aria-label="点击趋势">
        <div class="section-heading"><h2>点击趋势</h2><span>当前页日期汇总，不代表因果关系</span></div>
        <p v-if="summary.isPending.value" role="status">正在准备趋势…</p>
        <p v-else-if="summary.isError.value" class="muted">趋势暂不可用，请先重试结论数据。</p>
        <template v-else-if="rows.length">
          <div class="bars" aria-label="点击趋势图">
            <div v-for="row in trendRows" :key="row.date" class="bar-row">
              <span>{{ row.date }}</span>
              <span class="bar" :style="{ width: `${Math.max(4, row.clicks / maxClicks * 100)}%` }"></span>
              <strong>{{ row.clicks }}</strong>
            </div>
          </div>
          <div class="table-wrap">
            <table aria-label="渠道点击明细">
              <thead><tr><th>日期</th><th>活动</th><th>国家或地区</th><th>平台</th><th>产品</th><th>点击</th></tr></thead>
              <tbody>
                <tr v-for="row in rows" :key="`${row.date}-${row.campaign_id}-${row.platform_id}-${row.product_id}`">
                  <td>{{ row.date }}</td><td>{{ displayCampaign(row.campaign_id) }}</td><td>{{ row.country || "暂不可用" }}</td>
                  <td>{{ displayPlatform(row.platform_id) }}</td><td>{{ displayProduct(row.product_id) }}</td><td>{{ row.clicks }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="campaigns.isError.value || platforms.isError.value || products.isError.value" class="muted">部分名称暂时无法读取，已隐藏内部标识。</p>
        </template>
        <div v-else-if="!summary.isError.value" class="empty-state"><h3>当前条件暂无点击</h3><p>展开运营详情，尝试扩大日期范围或清除筛选。</p></div>
      </section>

      <NextStepPanel
        title="下一步建议"
        :explanation="nextExplanation"
        primary-label="打开运营详情"
        @primary="operationsOpen = true"
      />

      <details
        class="operations panel"
        role="group"
        aria-label="运营详情"
        :open="operationsOpen"
        @toggle="syncOperationsOpen"
      >
        <summary><span>运营详情</span><small>筛选、链接和发布记录</small></summary>
        <div class="operations-content">
          <section class="filters" aria-label="分析筛选">
            <label>开始日期<input v-model="start" type="date"></label>
            <label>结束日期<input v-model="end" type="date"></label>
            <label>活动<input v-model="campaign"></label>
            <label>平台<input v-model="platform"></label>
            <label>产品<input v-model="product"></label>
            <label>国家代码<input v-model="country" maxlength="2" placeholder="DE"></label>
            <button type="button" @click="reset">恢复近 30 天</button>
          </section>
          <nav class="actions" aria-label="分析结果分页">
            <button :disabled="!summary.data.value?.previous" @click="summaryUrl = summary.data.value?.previous ?? null">上一页</button>
            <button :disabled="!summary.data.value?.next" @click="summaryUrl = summary.data.value?.next ?? null">下一页</button>
          </nav>

          <section class="operation-section" aria-labelledby="tracking-links-title">
            <h2 id="tracking-links-title">追踪链接</h2>
            <p v-if="tracking.isPending.value" role="status">正在加载追踪链接…</p>
            <p v-else-if="tracking.isError.value" role="alert">{{ err(tracking.error.value) }} <button @click="tracking.refetch()">重新加载链接</button></p>
            <p v-else-if="!tracking.data.value?.results.length">暂无追踪链接。</p>
            <article v-for="link in tracking.data.value?.results" :key="link.id" class="link-row">
              <div><strong>{{ link.utm_campaign || "名称暂不可用" }}</strong><p>{{ link.full_url }}</p></div>
              <div class="actions"><button @click="copy(link.full_url)">复制</button><button v-if="canManage" @click="short.mutate(link.id)">创建短链接</button></div>
            </article>
            <nav class="actions" aria-label="追踪链接分页">
              <button :disabled="!tracking.data.value?.previous" @click="trackingUrl = tracking.data.value?.previous ?? null">上一页</button>
              <button :disabled="!tracking.data.value?.next" @click="trackingUrl = tracking.data.value?.next ?? null">下一页</button>
            </nav>
          </section>

          <section class="operation-section" aria-labelledby="short-links-title">
            <h2 id="short-links-title">短链接</h2>
            <p v-if="shorts.isPending.value" role="status">正在加载短链接…</p>
            <p v-else-if="shorts.isError.value" role="alert">{{ err(shorts.error.value) }}</p>
            <p v-else-if="!shorts.data.value?.results.length">暂无短链接。</p>
            <article v-for="item in shorts.data.value?.results" :key="item.id" class="link-row"><code>{{ item.redirect_path }}</code><button @click="copy(item.redirect_path)">复制</button></article>
            <nav class="actions" aria-label="短链接分页">
              <button :disabled="!shorts.data.value?.previous" @click="shortUrl = shorts.data.value?.previous ?? null">上一页</button>
              <button :disabled="!shorts.data.value?.next" @click="shortUrl = shorts.data.value?.next ?? null">下一页</button>
            </nav>
          </section>

          <section v-if="canManage" class="operation-section" aria-labelledby="published-title">
            <h2 id="published-title">已发布内容</h2>
            <p v-if="published.isPending.value" role="status">正在加载已发布内容…</p>
            <p v-else-if="published.isError.value" role="alert">{{ err(published.error.value) }}</p>
            <p v-else-if="!publishedTasks.length">暂无已发布内容。</p>
            <p v-for="task in publishedTasks" :key="task.id">{{ task.published_post?.external_id || "名称暂不可用" }}</p>
            <nav class="actions" aria-label="已发布内容分页">
              <button :disabled="!published.data.value?.previous" @click="publishedUrl = published.data.value?.previous ?? null">上一页</button>
              <button :disabled="!published.data.value?.next" @click="publishedUrl = published.data.value?.next ?? null">下一页</button>
            </nav>
          </section>
        </div>
      </details>

      <OperationModal v-if="createOpen" title="创建追踪链接" title-id="tracking-title" @close="closeCreate">
        <form class="modal" @submit.prevent="create.mutate()">
          <label>已发布内容<select v-model="taskId" required><option value="" disabled>请选择</option><option v-for="task in publishedTasks" :key="task.id" :value="task.id">{{ task.published_post?.external_id || "名称暂不可用" }}</option></select></label>
          <label v-if="(provenance.data.value?.productIds.length ?? 0) > 1">产品<select v-model="productId" required><option value="" disabled>请选择</option><option v-for="(id, index) in provenance.data.value?.productIds" :key="id" :value="id">{{ displayProduct(id) }}{{ displayProduct(id) === "名称暂不可用" ? `（选项 ${index + 1}）` : "" }}</option></select></label>
          <p v-else-if="provenance.data.value?.productIds.length === 1">产品：{{ displayProduct(provenance.data.value.productIds[0]) }}</p>
          <label>来源<input v-model="utmSource" required placeholder="linkedin"></label>
          <label>媒介<input v-model="utmMedium" required></label>
          <label>活动标识<input v-model="utmCampaign" required></label>
          <p>目标地址、活动、平台、产品与发布记录会从当前内容来源锁定，并在提交时复验。</p>
          <p v-if="provenance.isError.value || create.isError.value" role="alert">{{ err(provenance.error.value || create.error.value) }}</p>
          <div class="actions"><button type="button" @click="closeCreate">取消</button><button class="primary-action" :disabled="create.isPending.value || provenance.isPending.value || !productId">创建</button></div>
        </form>
      </OperationModal>
    </template>
  </main>
</template>

<style scoped>
.analytics-page{display:grid;gap:1rem}.page-header,.section-heading,.link-row,.actions,.section-title{display:flex;align-items:center;justify-content:space-between;gap:1rem}.page-header{align-items:flex-start}.page-header h1,.section-heading h2,.section-title h2{margin:.2rem 0}.panel{padding:1.1rem;border:1px solid var(--sg-line,var(--border-color,#d8dee8));border-radius:var(--sg-radius-md,1rem);background:var(--sg-surface,#fff)}.section-title{justify-content:flex-start}.section-title :deep(.app-icon){width:1.35rem;color:var(--sg-brand,#005ba8)}.conclusion-panel{border-left:4px solid var(--sg-brand,#005ba8)}.conclusion-copy{max-width:56rem;font-size:1.08rem;line-height:1.7}.section-heading span,.muted,summary small{color:var(--sg-muted,#667085)}.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.8rem}.metric-grid article{display:grid;gap:.25rem;padding:1rem;border-radius:.75rem;background:var(--sg-canvas,#f6f8fb)}.metric-grid strong{font-size:2rem;color:var(--sg-brand,#005ba8)}.bars{display:grid;gap:.5rem}.bar-row{display:grid;grid-template-columns:7rem minmax(2rem,1fr) 3rem;gap:.5rem;align-items:center}.bar{height:.8rem;background:var(--sg-brand,#005ba8);border-radius:999px}.table-wrap{overflow-x:auto;margin-top:1rem}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.65rem;border-bottom:1px solid var(--sg-line,#e5e9ef)}.operations{padding:0;overflow:hidden}.operations>summary{display:flex;justify-content:space-between;gap:1rem;padding:1.1rem;cursor:pointer;font-weight:800}.operations>summary:focus-visible{outline:3px solid var(--sg-brand-soft,#cfe5ff);outline-offset:-3px}.operations-content{display:grid;gap:1rem;padding:0 1.1rem 1.1rem}.filters{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem;align-items:end;padding:1rem;border-radius:.75rem;background:var(--sg-canvas,#f6f8fb)}.filters label,.modal label{display:grid;gap:.35rem}.operation-section{padding-top:1rem;border-top:1px solid var(--sg-line,#e5e9ef)}.link-row{display:flex;justify-content:space-between}.link-row p{overflow-wrap:anywhere}.actions{justify-content:flex-end}.modal{display:grid;gap:1rem}.empty-state{text-align:center;padding:1rem}@media(max-width:900px){.metric-grid,.filters{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.page-header,.section-heading,.link-row{align-items:stretch;flex-direction:column}.page-header .primary-action{width:100%}.metric-grid,.filters{grid-template-columns:1fr}.bar-row{grid-template-columns:6rem 1fr 2rem}.actions{flex-wrap:wrap}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style>
