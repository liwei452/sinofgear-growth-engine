# Growth Mission Phase One（V2）修订版实施计划

Date: 2026-08-19
Status: 供评审（supersedes 2026-08-18-growth-mission-phase-one）

## 修订结论

V1 已经落地了任务底座，但把“换工作台外壳”误当成了“打通闭环”。V2 不继续横向铺页面，
先把五条真实边界与一条纵向链路做实。

核心链路压缩为：

```text
创建增长任务
→ Agent 找客户并评分
→ 审核开发信
→ 待发送 / 发送
→ Agent 制定社媒计划并生成内容
→ 一次审核（各平台版本）
→ 自动生成发布包
→ 一键发布
→ 查看回复、RFQ、成交归因
```

## 对评审意见的逐条修正

1. 内容审核合并为一次：`MasterContent` 降级为内部母稿，不再要求单独人工审核。
   审核对象变为“一组平台版本”，一次审核后自动生成 `ChannelPackage`，不再出现第三段审核。
2. Agent 全面任务化：把 `mission_id`、目标国家、目标产品、已选客户、允许渠道、归因码、
   已验证企业事实传入内容/获客 Agent；内容策略幂等键由“组织 + 日期”改为“任务 + 周期”。
3. 归因改成因果证据：仅“同客户”只能算 `ASSISTED`；只有具体 `OutreachMessage` 回复、
   带 `attribution_code` 的 RFQ/表单、带任务 UTM 的社媒链接、或有人工确认人与理由时才算 `CONFIRMED`。
4. 邮箱状态与内容审核解耦：`草稿 → 审核通过 → 待发送 → 已发送`。未接邮箱停在“待发送”，
   绝不写入 `SENT`。当前代码已修复该“假发送”问题（`email_delivery_readiness()` + `EmailDeliveryUnavailable`）。
5. 补齐 `MissionEntityLink` 类型：新增 `DISCOVERY_CANDIDATE`、`CONTENT_BRIEF`、`MASTER_CONTENT`、
   `PLATFORM_CONTENT`、`OUTREACH_MESSAGE`、`INBOUND_RFQ`。

## 分期

### 第一期 A：真实边界 + 任务底座 + 完整实体关联

目标：所有对外事实不造假；增长任务能完整回答“客户从哪里来、Agent 生成了什么、谁审核了、
发了什么、最后产生什么”。

- A1 补齐实体关联类型与 `link_mission_entity` 注册表
  - 文件：`backend/apps/growth/models.py`、`backend/apps/growth/migrations/00xx_mission_entity_types.py`、
    `backend/apps/growth/mission_services.py`、`backend/apps/growth/tests/test_mission_links.py`
  - 新增 EntityType：`DISCOVERY_CANDIDATE`、`CONTENT_BRIEF`、`MASTER_CONTENT`、`PLATFORM_CONTENT`、
    `OUTREACH_MESSAGE`、`INBOUND_RFQ`
  - `sync_mission_links_from_agent_run` 与内容/发布入口按对象类型写回对应 link
  - 验收：任一任务时间线可串联“候选 → Brief → 母稿 → 平台版 → 发布包/邮件 → 结果”
- A2 归因因果规则（替换当前“同客户即确认”）
  - 文件：`backend/apps/growth/mission_attribution.py`、`backend/apps/growth/tests/test_mission_attribution.py`
  - `CONFIRMED` 仅接受：`OutreachMessage.status == REPLIED`、`InboundRfq.attribution_code == mission.attribution_code`、
    社媒 MetricReceipt 带任务 UTM、或人工归因记录（含确认人 + 理由）
  - 仅同客户、匿名曝光、无下游证据 → `ASSISTED` / `UNATTRIBUTED`
  - 未接通渠道返回 `None` + availability，不补零
- A3 AI 计划业务语义校验
  - 文件：`backend/apps/growth/mission_planning.py`、`backend/apps/growth/tests/test_mission_planning.py`
  - 在 JSON Schema 之上，校验计划中的渠道、国家、行业、产品、归因码、事实 ID 都属于当前任务组织
  - 缺少可信产品事实时生成“补全企业知识”工作项，而非继续生成营销内容
- A4 工作项分页 / 上限 / 预加载
  - 文件：`backend/apps/growth/work_items.py`、`backend/apps/growth/work_item_views.py`
  - 增加 `?limit` 分页与稳定游标，投影边界先限量再排序
- A5 OpenAPI 与前端类型重新生成
  - 文件：`frontend/src/api/generated/schema.ts`（`pnpm api:generate` 后检查）

### 第一期 B：Agent 任务化 + 合并审核 + 统一今日待办

目标：Agent 围绕单个增长任务工作，操作者只需一次内容审核与一次今日待办。

- B1 内容/获客 Agent 全面任务化
  - `run_content_strategy_agent` / `run_proactive_acquisition` / `run_social_ops_agent` 接收任务上下文
    （mission_id、国家、产品、客户、渠道、归因码、已验证事实）
  - 内容策略幂等键改为 `content-strategy:{organization}:{mission}:{cycle}`
  - 获客仍保持候选级幂等，但候选必须来自当前任务已选客户集合
- B2 合并内容审核为一次
  - 前端 `ReviewCenterPage` / `ContentFactoryPage` 不再要求 MasterContent 单独审核
  - 审核对象为“平台版本组”，一次 `批准并排期` 后自动生成 `ChannelPackage` 并进入发布包
- B3 统一今日待办收件箱
  - 复用 `workItems` 模块，接入开发信、社媒内容、客户回复、发布失败、配置阻塞五类事项
  - 每项一个主操作，完成后自动返回任务详情

### 第一期 C：因果归因 + 老板看板 + 清理旧入口

目标：老板只看有效客户、有效回复、RFQ、报价、订单、收入与单位成果成本；旧模块入口收敛。

- C1 老板工作台模式（不依赖 `READ_ONLY` 推断）
  - 显式工作台模式或角色，而非“只读即老板”
- C2 效果看板只显示可验证结果
  - 曝光/互动/任务数归入“辅助诊断”，不冒充业务结果
- C3 清理旧页面与旧路由
  - 保留兼容跳转，移除主导航旧入口；任务、待办、归因成为唯一普通用户主流程

## 审计要求（贯穿三期）

- 任务创建、计划批准、状态变更、人工归因均写入 `GrowthEvent` / 审计事件，带操作者与时间
- 开发信与社媒发布对外动作始终需要人工批准
- Mock / Fake 只能产出预览，不能产生 `SENT` / `PUBLISHED` / 可归因收入

## 已完成的 V1 遗留物（不重复建设）

- `GrowthMission` / `MissionPlan` / `MissionEntityLink` 与权限
- 任务 API、任务详情页、今日待办骨架、任务级归因骨架
- 邮箱“假发送”修复、Demo 社媒“假发布”修复
