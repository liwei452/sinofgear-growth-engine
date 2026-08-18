<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query"
import { computed, reactive, ref } from "vue"

import WorkspaceHeader from "../../shared/components/WorkspaceHeader.vue"

import {
  agentRunsQueryOptions,
  approveAgentRun,
  startAgentRun,
  type AgentRun,
} from "./agentApi"
import {
  getCursorPage,
  listBriefs,
  listMasterContents,
  listPlatforms,
  type ContentBrief,
  type MasterContent,
  type PlatformContent,
} from "../content/api"
import { getProductPage, listProducts, type Product } from "../products/api"
import { listApprovedCurrentHeads } from "../publishing/api"
import { listSocialAccounts, type SocialAccount } from "../platformAccounts/api"
import AgentApprovalCard from "./AgentApprovalCard.vue"

type StartableAgent = "platform_variants" | "content_creation" | "social_ops"

const queryClient = useQueryClient()
const runsQuery = useQuery(agentRunsQueryOptions())
const actionError = ref("")

const activeAgent = ref<StartableAgent | null>(null)
const form = reactive({
  master_id: "",
  brief_id: "",
  product_id: "",
  platform_id: "",
  content_id: "",
  account_id: "",
  scheduled_at: "",
})

const statusLabels: Record<AgentRun["status"], string> = {
  RUNNING: "运行中",
  WAITING_APPROVAL: "等待审批",
  COMPLETED: "已完成",
  BUDGET_EXCEEDED: "超出步数",
  FAILED: "已失败",
  REJECTED: "已拒绝",
}

const pendingRuns = computed(() =>
  (runsQuery.data.value ?? []).filter((run) => run.status === "WAITING_APPROVAL"),
)

const platformsQuery = useQuery({
  queryKey: ["growth", "agent-options", "platforms"],
  queryFn: () => listPlatforms(),
  enabled: computed(() =>
    activeAgent.value === "content_creation" || activeAgent.value === "social_ops"),
  staleTime: 60_000,
})

const masterContentsQuery = useQuery({
  queryKey: ["growth", "agent-options", "master-contents"],
  queryFn: async () => {
    const items: MasterContent[] = []
    let page = await listMasterContents({ page_size: 50 })
    items.push(...page.results)
    while (page.next) {
      page = await getCursorPage<MasterContent>(page.next, "/api/v1/master-contents")
      items.push(...page.results)
    }
    return items.filter((item) => item.status === "APPROVED")
  },
  enabled: computed(() => activeAgent.value === "platform_variants"),
  staleTime: 60_000,
})

const briefsQuery = useQuery({
  queryKey: ["growth", "agent-options", "briefs"],
  queryFn: async () => {
    const items: ContentBrief[] = []
    let page = await listBriefs()
    items.push(...page.results)
    while (page.next) {
      page = await getCursorPage<ContentBrief>(page.next, "/api/v1/content-briefs")
      items.push(...page.results)
    }
    return items.filter((item) => item.status !== "ARCHIVED")
  },
  enabled: computed(() => activeAgent.value === "content_creation"),
  staleTime: 60_000,
})

const productsQuery = useQuery({
  queryKey: ["growth", "agent-options", "products"],
  queryFn: async () => {
    const items: Product[] = []
    let page = await listProducts({ status: "ACTIVE" })
    items.push(...page.results)
    while (page.next) {
      page = await getProductPage(page.next)
      items.push(...page.results)
    }
    return items
  },
  enabled: computed(() => activeAgent.value === "content_creation"),
  staleTime: 60_000,
})

const socialContentsQuery = useQuery({
  queryKey: ["growth", "agent-options", "social-contents"],
  queryFn: () => listApprovedCurrentHeads(),
  enabled: computed(() => activeAgent.value === "social_ops"),
  staleTime: 60_000,
})

const socialAccountsQuery = useQuery({
  queryKey: ["growth", "agent-options", "social-accounts"],
  queryFn: async () => {
    const accounts = await listSocialAccounts()
    return accounts.filter(
      (account) =>
        account.status === "ACTIVE" &&
        account.publish_mode === "API_AUTO" &&
        account.effective_capabilities.includes("PUBLISH"),
    )
  },
  enabled: computed(() => activeAgent.value === "social_ops"),
  staleTime: 60_000,
})

const approveMutation = useMutation({
  mutationFn: ({ runId, decision }: { runId: string; decision: "approve" | "reject" }) =>
    approveAgentRun(runId, decision),
  onSuccess: () => {
    actionError.value = ""
    void queryClient.invalidateQueries({ queryKey: ["growth", "agent-runs"] })
  },
  onError: (error) => {
    actionError.value = error instanceof Error ? error.message : "审批失败"
  },
})

const startMutation = useMutation({
  mutationFn: ({ agentType, params }: { agentType: string; params: Record<string, unknown> }) =>
    startAgentRun(agentType, params),
  onSuccess: () => {
    actionError.value = ""
    closeStart()
    void queryClient.invalidateQueries({ queryKey: ["growth", "agent-runs"] })
  },
  onError: (error) => {
    actionError.value = error instanceof Error ? error.message : "启动失败"
  },
})

const startFormTitle = computed(() => {
  if (activeAgent.value === "platform_variants") return "创建平台变体"
  if (activeAgent.value === "content_creation") return "内容创作"
  if (activeAgent.value === "social_ops") return "社媒排期"
  return ""
})

const masterContents = computed(() => masterContentsQuery.data.value ?? [])
const briefs = computed(() => briefsQuery.data.value ?? [])
const products = computed(() => productsQuery.data.value ?? [])
const socialContents = computed(() => socialContentsQuery.data.value ?? [])
const socialAccounts = computed(() => socialAccountsQuery.data.value ?? [])

const startOptionsLoading = computed(() => {
  if (activeAgent.value === "platform_variants") return masterContentsQuery.isLoading.value
  if (activeAgent.value === "content_creation") {
    return briefsQuery.isLoading.value || productsQuery.isLoading.value || platformsQuery.isLoading.value
  }
  if (activeAgent.value === "social_ops") {
    return (
      socialContentsQuery.isLoading.value ||
      socialAccountsQuery.isLoading.value ||
      platformsQuery.isLoading.value
    )
  }
  return false
})

const startOptionsError = computed(() => {
  const message = (
    query: { isError: { value: boolean }; error: { value: unknown } },
  ): string =>
    query.isError.value
      ? query.error.value instanceof Error
        ? query.error.value.message
        : "选项加载失败"
      : ""

  if (activeAgent.value === "platform_variants") return message(masterContentsQuery)
  if (activeAgent.value === "content_creation") {
    return message(briefsQuery) || message(productsQuery) || message(platformsQuery)
  }
  if (activeAgent.value === "social_ops") {
    return message(socialContentsQuery) || message(socialAccountsQuery) || message(platformsQuery)
  }
  return ""
})

const canSubmit = computed(() => {
  if (activeAgent.value === "platform_variants") return Boolean(form.master_id)
  if (activeAgent.value === "content_creation") {
    return Boolean(form.brief_id && form.product_id && form.platform_id)
  }
  if (activeAgent.value === "social_ops") return Boolean(form.content_id && form.account_id)
  return false
})

function platformName(platformId: string): string {
  const platform = (platformsQuery.data.value ?? []).find((item) => item.id === platformId)
  return platform?.name ?? platformId
}

function masterLabel(item: MasterContent): string {
  const title = typeof item.payload.title === "string" ? item.payload.title : ""
  return title || item.id
}

function briefLabel(item: ContentBrief): string {
  const parts = [item.target_country, item.content_objective, item.language].filter(Boolean)
  return parts.length ? `${parts.join(" · ")}（${item.id.slice(0, 8)}）` : item.id
}

function productLabel(item: Product): string {
  return item.name_en || item.name_zh || item.id
}

function platformContentLabel(item: PlatformContent): string {
  const title = typeof item.payload.title === "string" ? item.payload.title : ""
  const platform = platformName(item.platform_id)
  return title ? `${platform} · ${title}` : `${platform} · ${item.id}`
}

function accountLabel(account: SocialAccount): string {
  return `${platformName(account.platform_id)} · ${account.display_name}`
}

function openStart(agentType: StartableAgent): void {
  activeAgent.value = agentType
  actionError.value = ""
  form.master_id = ""
  form.brief_id = ""
  form.product_id = ""
  form.platform_id = ""
  form.content_id = ""
  form.account_id = ""
  form.scheduled_at = ""
}

function closeStart(): void {
  activeAgent.value = null
}

function startContentStrategy(): void {
  actionError.value = ""
  startMutation.mutate({ agentType: "content_strategy", params: {} })
}

function submitStart(): void {
  if (!activeAgent.value || !canSubmit.value) return
  const agentType = activeAgent.value
  let params: Record<string, unknown> = {}

  if (agentType === "platform_variants") {
    params = { master_id: form.master_id }
  } else if (agentType === "content_creation") {
    params = {
      brief_id: form.brief_id,
      product_id: form.product_id,
      platform_id: form.platform_id,
      values: {
        target_country: "US",
        customer_type: "Buyer",
        content_objective: "Leads",
        cta: "Quote",
        landing_page_url: "https://sinfogear.com",
        language: "en",
        selling_points: ["Quality"],
        advantages: ["Speed"],
        keywords: ["gear"],
      },
    }
  } else if (agentType === "social_ops") {
    params = {
      content_id: form.content_id,
      account_id: form.account_id,
      scheduled_at: form.scheduled_at || undefined,
      timezone_name: "UTC",
    }
  }

  startMutation.mutate({ agentType, params })
}
</script>

<template>
  <main class="agent-approvals">
    <WorkspaceHeader
      eyebrow="人工控制台"
      title="等待你决定"
      description="Agent 可以研究、创作和安排社媒工作，但任何对外动作都必须由你明确批准。"
    >
      <template #meta>
        <span v-if="pendingRuns.length" class="pending-note">{{ pendingRuns.length }} 个任务等待审批</span>
      </template>
    </WorkspaceHeader>

    <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>
    <p v-if="runsQuery.isError.value" class="error" role="alert">
      加载失败：{{ runsQuery.error.value?.message }}
    </p>
    <p v-if="runsQuery.isLoading.value" class="empty">加载中…</p>

    <div v-else class="agent-approvals__list">
      <AgentApprovalCard
        v-for="run in runsQuery.data.value ?? []"
        :key="run.id"
        :run="run"
        :status-label="statusLabels[run.status]"
        :busy="approveMutation.isPending.value"
        @approve="approveMutation.mutate({ runId: run.id, decision: 'approve' })"
        @reject="approveMutation.mutate({ runId: run.id, decision: 'reject' })"
      />
      <p v-if="!(runsQuery.data.value ?? []).length" class="card empty">当前没有等待处理的 Agent 任务。</p>
    </div>

    <details class="card start-panel">
      <summary>启动新的 Agent 任务</summary>
      <p class="hint">每个 Agent 只做一小段受控流程，需要写数据或对外发布时都会回到这里审批。</p>
      <div class="start-actions">
        <button type="button" class="primary" @click="startContentStrategy">内容策略</button>
        <button type="button" class="secondary" @click="openStart('platform_variants')">平台变体</button>
        <button type="button" class="secondary" @click="openStart('content_creation')">内容创作</button>
        <button type="button" class="secondary" @click="openStart('social_ops')">社媒排期</button>
      </div>
    </details>

    <section v-if="activeAgent" class="card start-form">
      <div class="start-form__head">
        <h2>{{ startFormTitle }}</h2>
        <button type="button" class="ghost" @click="closeStart">关闭</button>
      </div>

      <p v-if="startOptionsLoading" class="empty">正在读取选项…</p>
      <p v-else-if="startOptionsError" class="error" role="alert">{{ startOptionsError }}</p>
      <template v-else>
        <label v-if="activeAgent === 'platform_variants'" class="field">
          <span>主内容</span>
          <select v-model="form.master_id">
            <option value="">请选择已批准的主内容</option>
            <option v-for="item in masterContents" :key="item.id" :value="item.id">
              {{ masterLabel(item) }}
            </option>
          </select>
        </label>

        <template v-if="activeAgent === 'content_creation'">
          <label class="field">
            <span>内容 Brief</span>
            <select v-model="form.brief_id">
              <option value="">请选择 Brief</option>
              <option v-for="item in briefs" :key="item.id" :value="item.id">
                {{ briefLabel(item) }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>产品</span>
            <select v-model="form.product_id">
              <option value="">请选择产品</option>
              <option v-for="item in products" :key="item.id" :value="item.id">
                {{ productLabel(item) }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>平台</span>
            <select v-model="form.platform_id">
              <option value="">请选择平台</option>
              <option v-for="item in platformsQuery.data.value ?? []" :key="item.id" :value="item.id">
                {{ item.name }}
              </option>
            </select>
          </label>
        </template>

        <template v-if="activeAgent === 'social_ops'">
          <label class="field">
            <span>平台内容</span>
            <select v-model="form.content_id">
              <option value="">请选择已批准内容</option>
              <option v-for="item in socialContents" :key="item.id" :value="item.id">
                {{ platformContentLabel(item) }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>社媒账号</span>
            <select v-model="form.account_id">
              <option value="">请选择可发布账号</option>
              <option v-for="item in socialAccounts" :key="item.id" :value="item.id">
                {{ accountLabel(item) }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>计划发布时间（可选）</span>
            <input v-model="form.scheduled_at" type="datetime-local" />
          </label>
        </template>

        <div class="form-actions">
          <button type="button" class="primary" :disabled="!canSubmit" @click="submitStart">
            启动
          </button>
        </div>
      </template>
    </section>
  </main>
</template>

<style scoped>
.agent-approvals {
  display: grid;
  gap: 18px;
  max-width: 1120px;
}
.pending-note {
  display: inline-flex;
  border-radius: 999px;
  background: #fff3df;
  padding: 5px 9px;
  color: #8a5900;
  font-weight: 800;
  font-size: 0.78rem;
}
.eyebrow {
  margin: 0;
  color: var(--sg-brand);
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.card {
  display: grid;
  gap: 14px;
  border: 1px solid var(--sg-line);
  border-radius: 14px;
  background: #fff;
  padding: 20px;
}
.card h2 {
  margin: 0;
  font-size: 1.02rem;
}
.hint {
  margin: 0;
  color: var(--sg-muted);
  font-size: 0.82rem;
  line-height: 1.55;
}
.start-actions,
.form-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.primary,
.secondary,
.ghost {
  border: 0;
  cursor: pointer;
  border-radius: 9px;
  padding: 10px 16px;
  font: inherit;
  font-weight: 700;
}
.primary {
  background: var(--sg-brand);
  color: #fff;
}
.secondary {
  background: var(--sg-brand-soft);
  color: var(--sg-brand);
}
.ghost {
  background: transparent;
  color: var(--sg-muted);
  padding: 6px 10px;
}
.primary:disabled,
.secondary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.start-form__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.field {
  display: grid;
  gap: 6px;
  font-size: 0.82rem;
  color: var(--sg-ink);
}
.field select,
.field input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--sg-line);
  border-radius: 9px;
  padding: 9px 11px;
  font: inherit;
  background: #fbfcfe;
}
.error {
  margin: 0;
  color: var(--sg-danger);
  font-size: 0.82rem;
}
.empty {
  margin: 0;
  color: var(--sg-muted);
  font-size: 0.82rem;
}
.agent-approvals__list {
  display: grid;
  gap: 12px;
}
.start-panel summary { cursor: pointer; color: var(--sg-ink); font-weight: 850; }
.start-panel[open] summary { margin-bottom: 2px; }
</style>
