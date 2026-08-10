# Lead Intelligence Domain Design

日期：2026-08-10

状态：待用户最终审阅

所属阶段：Phase B1–B2

## 1. 目标

Lead Intelligence 将用户指定范围内的公开同行账号、帖子、评论和企业主页转化为可审计的工业 B2B 潜客候选。系统先完整接收一次导入或允许采集范围内的公开数据，再进行去重、翻译、企业归并、需求识别和人工审核。

核心价值不是“抓取大量联系人”，而是回答三个问题：

1. 哪家企业可能需要 SinofGear 能生产的产品？
2. 为什么系统做出这个判断？
3. 销售应当基于哪些公开证据决定是否联系？

## 2. 范围边界

### 2.1 本阶段包含

- 用户维护同行账号、帖子、关键词和行业页面监测目标；
- 官方接口允许的数据同步；
- URL、截图、CSV、JSON 和批量粘贴导入；
- 指定输入范围内的公开评论完整接收；
- 评论级需求分析和账号级 Company Intelligence；
- 公开账号到潜在企业的置信匹配；
- 企业级 LeadCandidate、多信号归并和证据链；
- 人工审核、联系建议和 JSON/CSV/Mock CRM 交接；
- 组织权限、审计、幂等、失败恢复和数据保留。

### 2.2 明确不包含

- 无人值守自主登录、密码或验证码保存；
- 绕过访问限制、代理池、指纹浏览器或反封禁；
- 抓取私信、好友关系、隐藏联系方式或非公开页面；
- 自动陌生私信、自动群发或自动联系；
- CRM 客户生命周期、报价、跟单、成交和销售绩效；
- 把平台公开账号直接认定为真实自然人或企业员工；
- 把 AI 分数作为自动拒绝或自动联系决定。

LinkedIn、Facebook/Instagram 和 TikTok 都在连接器范围内，但每个平台只有在官方接口、许可和账号权限允许时才启用自动同步。否则使用 URL、截图或文件导入，不承诺自动读取同行评论。

## 3. 架构位置

Phase B 延续 Phase A 的模块化单体：Django REST Framework 负责资源和状态，Celery/Redis 负责异步任务，Vue 负责新手化审核界面，PostgreSQL 是正式数据源，MinIO 保存私有截图与导入文件。

新增领域模块：

- `sources`：MonitoringTarget、导入、公开来源、SourceSignal、SourceEvidence 和 PublicActor；
- `leads`：CompanyMatch、CompanyIntelligenceProfile、LeadCandidate、LeadInsight 和 HumanReview；
- `outreach`：OutreachDraft 和 LeadHandoff。

继续复用：

- `identity`：组织、成员、角色和权限；
- `knowledge`：工业 Ontology 和 KnowledgeEvidence；
- `jobs`：进度、失败、重试和结果引用；
- `ai`：PromptVersion、AIRun、模型、输入输出、置信度和人工修正；
- `audit`：状态变更和审核记录；
- `integrations`：官方平台、AI、对象存储和 Mock 连接器。

SourceEvidence、KnowledgeEvidence 和 AIEO 的 VisibilityEvidence 是三个语义不同的对象，不使用一个万能多态证据表。

## 4. 主数据流

```text
MonitoringTarget
        ↓
IngestionBatch
        ↓
SourceAccount / SourceContent
        ↓
SourceSignal
        ↓
SourceEvidence
        ↓
PublicActor ──→ CompanyMatch
                     ↓
         CompanyIntelligenceProfile
                     ↓
               LeadCandidate
                     ↓
                 LeadInsight
                     ↓
                 HumanReview
                     ↓
               OutreachDraft
                     ↓
                LeadHandoff
```

采集和分析是两个独立过程。导入成功不代表分析成功，发现公开账号不代表它是潜客，AI 分析成功也不代表已获准交接。

## 5. 领域对象

### 5.1 MonitoringTarget

表示用户主动指定的监测范围。

关键字段：

- `organization_id`；
- `target_type`：`ACCOUNT`、`POST`、`KEYWORD`、`INDUSTRY_PAGE`；
- `platform`；
- `external_reference` 或规范化 URL；
- `label`；
- `collection_mode`：`OFFICIAL_API`、`MANUAL_URL`、`SCREENSHOT`、`FILE_IMPORT`、`PASTE`；
- `schedule`、`enabled`；
- `capability_snapshot`；
- `created_by`、`created_at`。

目标只描述允许范围，不保存平台密码、Cookie 或验证码。

### 5.2 IngestionBatch

表示一次导入或同步事务。

关键字段：

- `source_type`：`API`、`URL`、`SCREENSHOT`、`CSV`、`JSON`、`PASTE`；
- `status`：`QUEUED`、`RUNNING`、`PARTIAL_SUCCESS`、`SUCCEEDED`、`FAILED`、`CANCELLED`；
- `job_id`；
- `input_reference`；
- `received_count`、`accepted_count`、`duplicate_count`、`failed_count`；
- `row_errors`；
- `idempotency_key`；
- `started_at`、`finished_at`。

文件部分错误时保留成功行，并向用户返回失败行号、原因和恢复动作。

### 5.3 SourcePlatform

沿用 Phase A 的平台能力思想，为采集增加能力码：

- `CAN_READ_PUBLIC_ACCOUNT`；
- `CAN_READ_PUBLIC_CONTENT`；
- `CAN_READ_PUBLIC_COMMENT`；
- `REQUIRES_USER_URL`；
- `REQUIRES_APP_REVIEW`；
- `ALLOWS_RAW_RETENTION`；
- `ALLOWS_SCREENSHOT_RETENTION`。

能力由连接器和当前授权共同决定。前端不得仅根据平台名称推断可采集能力。

### 5.4 SourceAccount

保存平台公开账号事实，不直接等同于联系人或企业。

关键字段：平台、平台原始 ID、公开名称、主页 URL、公开简介、账号类型、公开网站、国家提示、首次和最后发现时间、原始快照指纹。

### 5.5 SourceContent

保存同行帖子、视频、文章或页面的公开元数据，包括平台原始 ID、作者账号、URL、标题、公开正文、发布时间、语言、采集时间和内容指纹。

### 5.6 SourceSignal

支持类型：

- `COMMENT`；
- `POST_AUTHOR`；
- `CHANNEL_OWNER`；
- `PROFILE_MATCH`；
- `MENTION`；
- `HASHTAG_MATCH`。

SourceSignal 是“值得进入分析流程的公开事实”，不是潜客结论。

### 5.7 SourceEvidence

SourceEvidence 是一级对象。创建后正文和来源字段不可覆盖；来源变化时创建新版本。

关键字段：

- `source_signal_id`；
- `evidence_type`；
- `original_text`；
- `source_url`；
- `platform`；
- `public_published_at`；
- `captured_at`；
- `collection_method`；
- `language`；
- `screenshot_asset_id` 或导入文件引用；
- `content_hash`；
- `availability_status`；
- `retention_class`。

机器翻译作为派生字段保存，不能覆盖 `original_text`。

不可变表示在保留期内不得修改事实内容，不阻止按照数据保留政策删除或匿名化。

### 5.8 PublicActor

表示留言人或公开账号。可关联多个 SourceAccount，但不保存隐藏联系方式。公开职位、公开雇主和公开网站必须带来源证据。

### 5.9 CompanyMatch

表示 PublicActor 或 SourceAccount 与潜在企业之间的匹配建议。

关键字段：候选公司名、规范化域名、官网、国家、行业概念、匹配依据、匹配置信度、匹配方法、人工决定和证据列表。

自动合并硬门槛：

- 相同且已验证的官网域名；或
- 公开主页明确声明雇主，并有第二条一致证据；或
- 人工确认。

名称相似、Logo 相似、邮箱后缀推测或模型猜测只能生成候选，不得自动合并。

### 5.10 CompanyIntelligenceProfile

CompanyIntelligenceProfile 是对匹配企业公开业务特征的版本化分析，不是 CRM 公司档案。

包含：

- 规范化公司名称、官网和公开来源；
- 国家或地区；
- 行业和应用 Ontology 链接；
- 公开产品、设备或服务；
- 企业角色：设备厂家、终端工厂、维修商、分销商、同行或未知；
- 可能需要的齿轮产品和 Requirement 链接；
- 与 SinofGear 已批准 Capability 的匹配结果；
- 采购可能性、判断理由、置信度和 evidence IDs；
- PromptVersion、AIRun 和 Ontology 快照；
- 人工确认与修正。

CompanyIntelligence 只分析公开业务事实。无证据时字段保持未知，不根据公司名称或国家自行补全。

### 5.11 LeadCandidate

LeadCandidate 以潜在企业为主，可关联多个 PublicActor、SourceSignal 和 SourceEvidence。

状态：

```text
DISCOVERED
→ ANALYZING
→ ANALYZED
→ REVIEWED
→ READY_FOR_HANDOFF
→ HANDED_OFF
```

`ANALYZED` 或 `REVIEWED` 可进入 `DISMISSED`。`DISMISSED` 可由人工重新打开，不表示永久黑名单。

### 5.12 LeadInsight

每次分析创建新版本，不覆盖历史结果。

包含：

- 产品需求和 Requirement Ontology 链接；
- 行业、应用、国家和客户类型；
- 数量、材料、精度、标准、交期等已识别参数；
- 100 分排序分；
- Evidence Confidence、Company Match Confidence 和 AI Confidence；
- 逐项评分理由和 evidence IDs；
- PromptVersion、AIRun 和 Ontology 快照；
- HumanCorrection 和 reviewer。

### 5.13 HumanReview

审核动作：`CONFIRM`、`CORRECT`、`DISMISS`、`REOPEN`、`MERGE_COMPANY`、`SPLIT_COMPANY`、`REQUEST_MORE_EVIDENCE`。

人工修正创建新审核记录和新洞察版本，不删除原始 AI 输出。

### 5.14 OutreachDraft

生成公开回复、电子邮件、LinkedIn 或 WhatsApp 的人工可编辑草稿、联系理由和推荐渠道。系统不发送草稿。

### 5.15 LeadHandoff

交接包创建后不可变，至少包含：

- Candidate 快照；
- 已审核 LeadInsight；
- 公开账号和建议联系人；
- SourceEvidence 快照及来源 URL；
- OutreachDraft；
- 创建人、审核人和创建时间；
- 导出版本和幂等键。

首期支持 JSON、CSV 和 Mock CRM。

## 6. 评分模型

总分只负责队列排序：

| 维度 | 分值 | 判断内容 |
| --- | ---: | --- |
| 采购意向 | 30 | 寻找、询价、替换、供应商或急件需求 |
| 企业匹配 | 25 | 国家、行业、公司类型和公开业务 |
| 需求明确度 | 20 | 产品、材料、精度、数量、标准和交期 |
| 能力匹配 | 15 | Ontology 中已批准且有证据的生产能力 |
| 时效与紧迫度 | 10 | 信号新近程度、停机、急件或明确时间 |

排序等级：

- `80–100`：高价值，进入优先人工审核；
- `60–79`：值得关注，进入普通审核；
- `40–59`：观察，等待更多信号；
- `0–39`：低价值，按保留政策处理。

进入高价值队列仍必须满足：至少一条可追溯 SourceEvidence，存在明确需求或可靠企业匹配，能力结论有 KnowledgeEvidence 支持，AI运行和本体快照完整。

以下信号不能单独推高为高价值：点赞、表情、普通夸奖、模糊公司名、招聘求职、广告、学生研究或供应商推销。

## 7. 数据保留

- 已确认潜客和交接证据：持续保存，直到有权限的用户删除或适用政策要求处理；
- 普通、低价值、未确认数据：默认保存 30 天，之后删除正文或匿名化；
- 被忽略对象：保留组织级去重指纹和忽略原因，避免重复推荐；
- 来源页面删除：保留允许保存的证据快照，并标记来源不可访问；
- 平台政策要求更短期限时，以 ProviderPolicy 为准。

保留和清理任务必须写审计日志，不得删除 LeadHandoff 引用的证据。

## 8. API

```text
/api/v1/monitoring-targets
/api/v1/ingestion-batches
/api/v1/source-accounts
/api/v1/source-contents
/api/v1/source-signals
/api/v1/source-evidences
/api/v1/public-actors
/api/v1/company-matches
/api/v1/company-intelligence-profiles
/api/v1/lead-candidates
/api/v1/lead-insights
/api/v1/lead-reviews
/api/v1/outreach-drafts
/api/v1/lead-handoffs
```

耗时操作返回 `202` 和 `job_id`。SourceEvidence 不提供普通更新接口；状态和保留动作通过受控服务完成。审核作为独立 `lead-reviews` 资源创建，不使用不可审计的字段覆盖。

## 9. 异步任务

```text
SOURCE_IMPORT
SOURCE_NORMALIZE
EVIDENCE_EXTRACT
COMPANY_RESOLVE
COMPANY_ENRICH
LEAD_ANALYZE
OUTREACH_GENERATE
LEAD_HANDOFF
RETENTION_CLEANUP
```

AI任务沿用 PromptVersion、AIRun、输入快照、结构化输出、置信度和人工修正。每次任务保存 Connector capability snapshot，避免以后平台能力变化时无法解释历史结果。

## 10. 幂等与一致性

- 官方平台数据使用组织、平台、资源类型和平台原始 ID 作为自然幂等键；
- 文件、粘贴和截图使用规范化内容指纹、来源和时间窗口去重；
- IngestionBatch 接受客户端幂等键；
- 重试不能重复创建 SourceEvidence、LeadInsight 或 LeadHandoff；
- CompanyMatch 合并和拆分在事务中执行并保留历史；
- LeadInsight 只引用已提交的 SourceEvidence 和具体 Ontology 快照；
- LeadHandoff 只能从 `READY_FOR_HANDOFF` 创建。

## 11. 权限

```text
sources.read
sources.manage
leads.read
leads.analyze
leads.review
leads.handoff
```

所有查询和服务都按活动组织隔离。截图和导入文件使用私有对象存储和短时下载 URL。连接器凭据保持只写，不进入序列化响应、日志或前端缓存。

## 12. 异常处理

- 平台拒绝或能力不足：停止任务，提示 URL、截图或文件导入；
- 文件部分错误：批次进入 `PARTIAL_SUCCESS`，成功行保留；
- AI结构化输出无效：自动重试一次，仍失败则进入人工处理；
- 企业匹配歧义：保留多个候选，不自动合并；
- 翻译失败：保留原文继续处理；
- 来源页面消失：标记不可访问，不篡改证据；
- 保留清理冲突：交接包和已确认潜客优先保护，任务失败并报警；
- 跨组织引用：返回安全的 404/403 错误，不泄露对象存在性。

所有写操作错误继续使用 Phase A 的 `code`、`message`、`recovery_action` JSON 包络。

## 13. 测试与验收

建立不少于 100 条人工标注的中英文工业评论和企业样本，包含明确需求、模糊需求、普通互动、广告、招聘、求职、同行和无评论企业主页。

首期验收目标：

- 明确采购需求召回率不低于 90%；
- 高价值队列准确率不低于 80%；
- AI结论证据引用覆盖率为 100%；
- 重复导入不产生重复证据或潜客；
- 弱企业匹配不自动合并；
- 人工修正保留 AI 原始版本；
- 交接包完整包含企业、联系人、洞察和证据；
- 组织间数据零泄漏；
- 30 天清理不删除已确认潜客和交接证据；
- 部分失败批次可以修正和幂等重试。

浏览器 E2E：

```text
创建监测目标
→ 导入含成功、重复和错误行的文件
→ 查看完整公开信号
→ 运行 AI 分析
→ 查看并修正 Company Intelligence
→ 审核高价值企业潜客
→ 修正一次企业匹配和评分
→ 生成联系建议
→ 导出带不可变证据的交接包
```

## 14. 推荐开发切片

### B1：Lead Intelligence 基础

先实现 URL、截图、CSV、JSON、粘贴导入，SourceContent、SourceSignal、SourceEvidence、LeadCandidate、LeadInsight、人工审核和离线评估集。

### B2：Company Intelligence 与交接

增加 SourceAccount、PublicActor、CompanyMatch、企业归并、OutreachDraft、LeadHandoff、雷达界面和 Mock CRM。

真实平台连接器后置到 B4。只有在 B1/B2 的 AI 判断达到验收门槛后，才扩大采集规模。
