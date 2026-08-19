# Growth Mission 收口重构方案

Date: 2026-08-19
Status: 评审稿（暂停加功能，先冻结现状并定骨架）

## 0. 现状与 Git 结论

在本工作区：`feature/phase-a` 本地与 `origin/feature/phase-a` 完全一致，HEAD 均为
`6b05831`，`rev-list --left-right --count` 为 `0 0`，**没有分叉**。若你看到“本地/远程
ahead N”，那是另一台克隆或审查快照的状态，不是这个工作区。收口前我会再取一次远程确认。

真实邮箱不接入，不阻塞本轮。

## 1. 唯一主流程

产品只保留三个视角，Agent 不再是一级菜单，而是后台执行引擎：

```text
操作者：
  创建增长任务
  → 获客发现/评估（Agent 自动）
  → 审核开发信（人工）
  → 社媒计划与内容生成（Agent 自动）
  → 审核平台内容（人工）
  → 一键发布（人工）

管理者：
  配置大模型 / 平台 API / 公司信息 / 产品资料 / 权限

老板：
  查看投入、线索、回复、商机、成交归因
```

Agent 只在需要人工决策时产生一个“审核任务”，进入统一“今日待办”。

## 2. 导航收敛

普通用户主导航只保留：

```text
今日待办   /
增长任务   /missions
数据归因   /attribution
```

管理员额外：

```text
系统配置   /settings
```

其余入口全部下沉：

- 客户与商机、内容与素材 → 变成“增长任务”详情内的执行线，不再一级导航。
- Agent 工作台、审核中心、内容工厂、发布日历、推广页 → 取消独立入口，能力并入任务/待办。

## 3. 前端页面：保留 / 合并 / 删除

### 保留（主视图）

- `DashboardPage`（含 `TodayWorkInbox`）→ 今日待办
- `GrowthMissionsPage` / `GrowthMissionDetailPage` / `MissionLaneBoard` → 增长任务
- `ExecutiveAttributionPage` → 数据归因
- `SettingsCenterPage` / `AIModelSettingsPage` → 系统配置
- `RoleHomePage` → 按角色分流首页

### 合并进增长任务执行线

- `ContentFactoryPage` + `ContentBriefWizard` + `ContentRecommendationPanel` → 合并到任务“社媒增长”线（从任务触发选题/生成，不再独立页面）
- `ReviewCenterPage` + `ContentReviewDialog` → 合并到“今日待办”审核卡
- `PromotionPage`（OAuth/发布/重试）→ 合并到任务“社媒增长”线的“发布”步骤
- `PublishingCalendarPage` → 任务“社媒增长”线的排期视图
- `OpportunitiesPage` → 任务“客户开发”线的候选/机会视图

### 删除 / 归档

- `AgentWorkspacePage`、`AgentCapabilityCard`、`AgentRunTimeline` 等 Agent 一级工作台 → 删除导航，保留后端 Agent 能力
- `AnalyticsPage`（LegacyAnalytics，`/admin/analytics`）→ 删除，归因统一走 `/attribution`
- `ContentAssetsHubPage` → 拆回资产/知识，作为管理员资源，不放普通导航
- `EffectivenessPage`（旧 `/analytics` 组件）→ 删除，归因统一

## 4. 后端接口：保留 / 合并 / 删除

### 保留（核心契约）

- 任务：`/growth/missions`、`/growth/missions/<id>`、`generate-plan`、`approve-plan`、`status`、`timeline`、`start-outreach`、`start-content-strategy`
- 统一待办：`/growth/work-items`
- 归因：`/growth/attribution`
- 任务计划：`mission_planning.py`

### 合并 / 精简

- `GrowthWorkspaceView`（一次性返回多集合）→ 拆成各执行线所需的最小端点；前端不再用一个大接口
- 内容生成、平台版本、渠道包、发布批次 → 保留但只被任务/待办内部调用，不暴露为独立业务入口
- 获客发现/补全/评分 → 保留为任务内部工具

### 删除 / 降级

- 旧“推广计划”独立审批（`promotion-plan/approve|regenerate`）→ 由任务计划取代，降级或删除
- 旧“经营效果”多量纲相加 → 由 `/attribution` 取代

## 5. 数据模型：保留 / 合并 / 删除

### 保留（领域主对象）

- `GrowthMission` / `MissionPlan` / `MissionEntityLink`
- `TargetAccount` / `DiscoveryCandidate` / `Contact` / `IntentSignal`
- `OutreachDraft` / `OutreachMessage`
- `ChannelPackage` / `GrowthPublishBatch` / `GrowthPublishItem`
- `MetricReceipt` / `InboundLead` / `InboundRfq` / `SalesDeal`
- `ProductEvidenceFact`（资产事实）
- `Campaign` / `ContentBrief` / `MasterContent` / `PlatformContent`（内容内部对象）

### 合并 / 内部化

- `MasterContent`：降为内部母稿，已自动 APPROVED，不再进人工审核
- `ChannelPackage`：发布包，由平台版本审批自动生成
- `AgentRun` / `AgentRunStep`：作为执行审计，不在 UI 一级呈现

### 删除 / 归档（仅当不再被引用）

- 旧 `ReactivationRecord`、`MarketCountryProfile`、`TradeDatasetSnapshot` 等非主链模型：保留数据表，移除普通导航/入口，作为“高级/迁移”保留

## 6. 实施顺序

1. 从 `origin/feature/phase-a`（`6b05831`）建干净分支 `consolidation/main-flow`。
2. 先删重复：移除 Agent 工作台、旧分析、旧推广页、审核中心、内容工厂一级导航；后端删除/降级 `GrowthWorkspaceView`、旧经营效果。
3. 再修链路：把获客/内容/发布全部挂到任务执行线，Agent 后台化；补齐 `MissionContext`、审批后回写、归因因果证据、审计事件。
4. 最后统一 UI：三视角 + 单一明亮医疗蓝视觉系统（另行用 UI 设计稿定 token）。

## 7. 验收口径

- 普通员工：创建任务 → 待办审核开发信 → 待办审核平台内容 → 一键发布 → 看任务归因。
- Agent：全程后台运行，不占导航；只在需要人工决策时出现在“今日待办”。
- 管理者：只在系统配置处理模型/API/公司/产品/权限。
- 老板：只在数据归因看投入与结果。
