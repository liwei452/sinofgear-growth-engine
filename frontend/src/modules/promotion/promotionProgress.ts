export type PromotionStepId = "company" | "market" | "icp" | "discovery" | "content" | "channels" | "approval"
export type PromotionStep = {
  id: PromotionStepId
  label: string
  state: "complete" | "current" | "blocked" | "upcoming"
  summary: string
  route?: string
}

export type PromotionProgressInput = {
  companyConfigured: boolean
  marketConfigured: boolean
  icpConfigured: boolean
  discoveryStarted: boolean
  contentPrepared: boolean
  channelsConfigured: boolean
  approvalReady: boolean
}

type StepDefinition = Omit<PromotionStep, "state"> & {
  complete: (input: PromotionProgressInput) => boolean
  prerequisites: Array<(input: PromotionProgressInput) => boolean>
}

const definitions: StepDefinition[] = [
  {
    id: "company", label: "公司资料", summary: "确认可用于推广的公司事实。", route: "/company",
    complete: input => input.companyConfigured, prerequisites: [],
  },
  {
    id: "market", label: "目标市场", summary: "在增长任务中保存目标市场。", route: "/missions",
    complete: input => input.marketConfigured, prerequisites: [input => input.companyConfigured],
  },
  {
    id: "icp", label: "目标客户", summary: "明确产品、行业和客户画像。", route: "/products",
    complete: input => input.icpConfigured, prerequisites: [input => input.companyConfigured],
  },
  {
    id: "discovery", label: "客户发现", summary: "从已保存的任务中开始获取客户。", route: "/missions",
    complete: input => input.discoveryStarted,
    prerequisites: [input => input.marketConfigured, input => input.icpConfigured],
  },
  {
    id: "content", label: "内容准备", summary: "准备已关联产品的素材和内容。", route: "/assets",
    complete: input => input.contentPrepared, prerequisites: [input => input.discoveryStarted],
  },
  {
    id: "channels", label: "推广渠道", summary: "查看渠道账户、接口配置和适用限制。", route: "/platform-accounts",
    complete: input => input.channelsConfigured, prerequisites: [input => input.contentPrepared],
  },
  {
    id: "approval", label: "人工审核", summary: "在任务详情中审核计划后再启动。", route: "/missions",
    complete: input => input.approvalReady, prerequisites: [input => input.channelsConfigured],
  },
]

export function promotionSteps(input: PromotionProgressInput): PromotionStep[] {
  let currentAssigned = false
  return definitions.map((definition) => {
    if (definition.complete(input)) return { ...definition, state: "complete" }
    if (!definition.prerequisites.every(prerequisite => prerequisite(input))) {
      return { ...definition, state: "blocked" }
    }
    if (!currentAssigned) {
      currentAssigned = true
      return { ...definition, state: "current" }
    }
    return { ...definition, state: "upcoming" }
  })
}
