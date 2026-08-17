# Agent 运行时与 Go/Rust 网关对接契约

日期：2026-08-17
状态：方向已确认，先落「我们这一部分」的 agent 运行时骨架

## 1. 边界确认

整体系统分两块，互不重写：

- **我们这一部分**：`sinofgear-growth-engine`，Django 5.2 + DRF + Celery + PostgreSQL + Redis + MinIO，前端 React/Vue 中文工作台。职责是增长获客：主动获客、内容工厂、推广、效果归因、询盘回流、销售阶段回填。
- **公司其他部分**：Rust 网关 + Go 服务（CRM / 智能客服等）。我们通过标准契约对接，不进对方的代码。

结论：**我们这部分继续用 Python/Django，不改成 Go/Rust。** 语言不一致通过「统一身份 + 事件契约 + 类型化 API」解决，而不是重写。

## 2. 目标：从「AI 辅助」到「真正的 agent」

现在的实现是「AI 辅助」：LLM 只做单次判断或生成，流程顺序由 Python 代码写死。

真正的 agent 需要四件事同时成立：

1. 能调用工具并循环：规划 → 调工具 → 看结果 → 再决定下一步 → 失败可重试。
2. 有持久记忆：公司、联系人、证据、会话、任务状态、已发送内容都沉淀，可断点续跑。
3. 由 agent 持有状态机，而不是把状态流转硬编码进 service。
4. 高风险动作卡人工审批，全程审计 + 预算/步数上限 + 幂等，防止失控、烧钱、重复触达。

## 3. Agent 运行时设计

新增 `backend/apps/growth/agent/` 作为有边界的运行时：

- `tools.py`：`Tool`（名称、描述、参数 schema、风险级别 `read`/`write`）+ `ToolRegistry`。
- `planner.py`：`Planner` 决定下一步；`LLMPlanner` 用真实模型，`DeterministicPlanner` 用于测试/无模型降级。
- `memory.py`：追加式 `Memory`，记录每一步决策与结果。
- `runtime.py`：`AgentRuntime` 循环，含审批闸门、步数预算、重复动作熔断、工具异常收口。

循环语义：

```text
memory.snapshot()
  -> planner.plan(goal, memory, tools, step_index)
  -> 若是 terminal：结束
  -> 解析工具；未知工具：失败
  -> 若是 write 工具且未审批：暂停，返回 waiting_approval
  -> 执行工具，记录结果
  -> 重复同一动作：熔断，防止无限循环
  -> 达到步数上限：budget_exceeded
```

`write` 工具（发送邮件、发布、花钱）永远先暂停等人审批；`read` 工具（发现、富化、评分、验证）可自动执行。

## 4. 与现有模块的映射

主动获客状态机落到现有模型，不另起炉灶：

| Agent 阶段 | 现有模块 / 模型 |
| --- | --- |
| 发现 | `maps_discovery.py`、`discovery.py`、`DiscoveryCandidate`、`DiscoveryRun` |
| 身份去重/排除 | `company_resolution.py`、`TargetAccount` 唯一约束 |
| 富化 | `enrichment.py`、`website_enrichment.py`、`CandidateEnrichmentSnapshot` |
| 评分分级 | `grading.py`、`lead_judgment.py`、`IntentSignal` |
| 联系人 | `contact_intelligence.py`、`Contact` |
| 邮箱验证 | `email_verification.py` |
| 开发信 | `OutreachDraft`（DRAFT/APPROVED） |
| 跟进状态 | `FollowUp`、`outreach_stages.py` |
| 回复/退信/退订 | `FollowUp` 状态 + `AccountFunnelEvent` |
| 询盘回流 | `InboundLead`、`LeadWebsiteVisit` |
| 人工交接 | `OpportunityReview`、`CRMHandoff` |

后续把这批 `read`/`write` 能力注册成 `Tool`，由 `AgentRuntime` 驱动，而不是继续在 service 里串行写死。

## 5. Go/Rust 网关对接契约

我们只暴露三条边界，后续接网关时按此实现：

1. **统一身份**：`company_id`、`contact_id`、`conversation_id`、`opportunity_id` 用稳定外部 ID；跨系统用映射表，不靠名字模糊匹配。
2. **事件**（幂等、带 `event_id` + `occurred_at` + `organization_id`）：`company.discovered`、`contact.verified`、`email.approved`、`email.sent`、`email.replied`、`email.bounced`、`email.unsubscribed`、`rfq.created`、`chat.escalated`。
3. **API**：以现有 `GET /api/v1/schema` 的 OpenAPI 为对外契约，新增事件回调/查询端点；网关侧用 Rust 网关统一鉴权，我们只认网关头传的组织/身份声明。

安全不变：连接器密钥只写不入读、写操作 CSRF、组织隔离、审计不存明文密钥。

## 6. 分阶段落地

- **Phase 0（本次）**：冻结边界 + agent 运行时骨架 + 测试。
- **Phase 1**：把主动获客的现有能力注册成工具，跑通 `发现 → 富化 → 评分 → 开发信 → 人工审批 → 发送` 一条真实闭环，并接持久记忆/任务断点续跑。
- **Phase 2**：官网询盘/访客意图回流，agent 自动分流，合格的进获客管道，需聊的交给 Rust 智能客服。
- **Phase 3**：客服前端变成 agent 前台，可调工具、查资料、判断转人工、推进 CRM。
- **Phase 4**：按需把 Django 中吃性能的模块下沉到 Go/Rust。

## 7. 本次已落地

- `apps/growth/agent/tools.py`：`Tool` / `ToolRegistry` / `ToolResult`。
- `apps/growth/agent/planner.py`：`Plan` / `Planner` / `LLMPlanner` / `DeterministicPlanner` / `build_planner`。
- `apps/growth/agent/memory.py`：`AgentStep` / `Memory`。
- `apps/growth/agent/runtime.py`：`AgentRuntime` / `AgentRunResult` / `PendingApproval`。
- `apps/growth/tests/test_agent_runtime.py`：证明循环、审批暂停/恢复、步数上限、未知工具失败、重复动作熔断。

下一步：把这批运行时接到现有 `discovery/enrichment/grading/contact/email` 能力上，做成第一条可跑的主动获客 agent 闭环。
