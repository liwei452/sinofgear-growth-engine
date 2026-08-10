# AIEO Domain Design

日期：2026-08-10

状态：待用户最终审阅

所属阶段：Phase B3 与后续 B5

## 1. 目标

AIEO（AI Engine Optimization）让 SinofGear 的企业身份、产品、制造能力、行业经验和证据成为 AI 系统可以准确理解、引用和推荐的公开知识资产。

系统形成闭环：

```text
EntityProfile
→ AI Question Library
→ API Benchmark / Web Calibration
→ Visibility Observation
→ Visibility Gap
→ Asset Recommendation
→ Web Asset / Schema Artifact
→ Re-measure
```

首期目标是建立可信、可重复、可审计的可见度基线，不承诺短期排名、富结果或品牌提及增长。

## 2. 范围边界

### 2.1 本阶段包含

- SinofGear 企业实体及版本；
- 产品、能力、行业、工艺、标准和市场别名；
- 按国家、语言、行业、产品和采购角色组织的 AI 问题库；
- 官方 API 自动基准监测；
- 用户提交截图或回答的网页版人工校准；
- 品牌提及、推荐、引用、竞品、实体准确性和缺口指标；
- FAQ、产品页、能力页、案例页和标准 Schema.org JSON-LD 建议；
- 证据不足时创建补证据任务；
- 人工审核、版本、权限、审计和错误恢复。

### 2.2 明确不包含

- 自动登录 ChatGPT、Gemini、Perplexity 或批量抓取网页版输出；
- 把官方 API 结果宣称为消费者网页版的精确复现；
- 将不同 Provider、模型、国家、语言或观测模式合并成一个伪总分；
- 自创搜索引擎不识别的 Schema.org 类型；
- 在网页不可见内容中隐藏结构化营销声明；
- 无证据生成精度、产能、认证、设备、客户或案例事实；
- 自动发布到独立站；
- 保证 Google 富结果、AI引用或排名。

## 3. 架构位置

新增 `aieo` 领域模块，复用 Phase A 的 `knowledge`、`ai`、`jobs`、`audit`、`identity`、`assets` 和 `content`。

`aieo` 负责：

- EntityProfile 和发布版本；
- AIQuestion、QuestionVariant 和 QuestionSet；
- VisibilityRun、ManualObservation、VisibilityObservation 和 VisibilityMetric；
- VisibilityGap、AssetRecommendation、WebAsset 和 SchemaArtifact；
- ProviderPolicy 和观测合规处理。

网站资产建议经人工批准后，可以创建 Phase A ContentBrief，但 AIEO 不绕过现有内容审核和发布状态机。

## 4. 企业实体

### 4.1 EntityProfile

EntityProfile 表示 SinofGear 对外公开的企业实体。草稿可修改，发布后生成不可变版本。

内容包括：

- 法定或对外品牌名称；
- 企业类型和一句话定位；
- 官网主域名和批准的 `sameAs` 链接；
- 产品类型；
- 制造能力；
- 行业和应用；
- 工艺、材料、参数和标准；
- 服务国家和语言；
- 市场别名、缩写和常见写法；
- 对应 KnowledgeConcept、KnowledgeRelation 和 KnowledgeEvidence IDs。

只有 `APPROVED` Ontology 内容可以进入已发布 EntityProfile。历史 VisibilityRun 必须引用具体 EntityProfile 版本，不受后续更新影响。

状态：

```text
DRAFT → IN_REVIEW → APPROVED → PUBLISHED → SUPERSEDED / ARCHIVED
```

## 5. AI 问题库

### 5.1 AIQuestion

问题类型：

- `SUPPLIER_DISCOVERY`：供应商发现；
- `CAPABILITY`：制造能力；
- `QUALITY_STANDARD`：精度和标准；
- `APPLICATION`：行业应用；
- `REPLACEMENT_MAINTENANCE`：替换和维修；
- `COMPARISON`：供应商比较；
- `GEOGRAPHIC`：国家和区域选择；
- `EVIDENCE_VALIDATION`：设备、检测和案例证据。

每个问题关联商业重要度、目标产品、行业、Requirement 概念和预期企业事实。

### 5.2 QuestionVariant

同一个语义问题可以按以下维度生成明确版本：

- 语言；
- 国家或区域；
- 行业；
- 产品；
- 买方角色；
- 是否要求当前网页信息；
- 是否要求列出引用来源。

问题变体创建后版本化。修改措辞必须创建新版本，避免历史趋势被问题变化污染。

### 5.3 QuestionSet

- `DAILY_SAMPLE`：少量高价值问题；
- `WEEKLY_MONITOR`：主要产品和市场；
- `MONTHLY_BENCHMARK`：固定问题、模型和参数；
- `MANUAL_CALIBRATION`：网页版抽检清单。

## 6. 两类观测模式

### 6.1 API_BENCHMARK

通过获准的官方 API 和固定运行条件自动执行，适合重复趋势监测。

保存：Provider、模型、API能力、问题版本、国家、语言、运行时间、PromptVersion、EntityProfile版本、Ontology快照和 ProviderPolicy 版本。

### 6.2 WEB_CALIBRATION

用户在真实网页版手动提问后上传截图或粘贴回答。系统可以识别和结构化用户主动提交的内容，但不自动登录或批量提取网页。

API_BENCHMARK 与 WEB_CALIBRATION 永久分开统计，只允许并排比较。

## 7. ProviderPolicy

每个 Provider 和连接模式保存版本化策略：

- `automation_allowed`；
- `raw_response_retention_allowed`；
- `citation_retention_allowed`；
- `screenshot_retention_allowed`；
- `maximum_retention_days`；
- `required_display_attribution`；
- `supported_countries`；
- `supported_models`；
- `rate_limit_policy`；
- `terms_reference`；
- `effective_at`。

若条款不允许保存完整回答，VisibilityEvidence 只保存允许的聚合结果、哈希、模型审计和人工确认，不保存原文或链接。

ProviderPolicy 是运行时硬门槛，不是页面提示。

## 8. 可见度对象

### 8.1 VisibilityRun

一次问题集在一个 Provider、模型、国家、语言和观测模式下的执行。

状态：

```text
QUEUED → RUNNING → PARTIAL_SUCCESS / SUCCEEDED / FAILED / CANCELLED
```

API限流、Provider错误或问题失败不能计为“未提及”。

### 8.2 VisibilityObservation

每个有效问题产生一个观测：

- 是否明确提及 SinofGear；
- 是否作为合格供应商推荐；
- 推荐理由；
- 是否引用官网或批准资产；
- 允许保存的引用 URL；
- 出现的竞品实体；
- 关于 SinofGear 的事实声明；
- 与 Ontology 的一致和冲突项；
- Evidence Confidence 和 AI Confidence；
- 人工修正。

### 8.3 VisibilityEvidence

按 ProviderPolicy 保存允许的回答片段、引用、截图、文件哈希和采集元数据。它不是 KnowledgeEvidence，不能直接证明 SinofGear 的制造能力。

### 8.4 ManualObservation

保存用户提交的截图或文本、问题、平台、模型、国家、语言和实际观察时间。OCR置信度不足时必须由用户核对后才能进入指标。

## 9. 指标体系

所有分母只包含成功且符合 ProviderPolicy 的有效观测。

| 指标 | 定义 |
| --- | --- |
| Mention Rate | 明确提及 SinofGear 的有效问题比例 |
| Qualified Recommendation Rate | 将 SinofGear 作为匹配供应商推荐的比例 |
| Citation Rate | 引用官网或批准企业资产的比例 |
| Entity Accuracy | 关于 SinofGear 的事实中有 Ontology 证据支持且无冲突的比例 |
| Competitor Share | 同一问题集内各供应商实体的相对提及份额 |
| Capability Coverage | 有证据的目标能力被正确识别的比例 |
| Answer Stability | 相同固定条件多次运行时核心结论的一致程度 |
| Gap Trend | 未提及、错误陈述和无引用缺口随时间的变化 |

指标必须按以下维度过滤：观测模式、Provider、模型、国家、语言、产品、行业、问题集和时间。

系统不生成跨 Provider 的单一“AI排名”。

## 10. VisibilityGap

缺口类型：

- `NOT_MENTIONED`；
- `NOT_RECOMMENDED`；
- `NO_CITATION`；
- `WRONG_ENTITY_FACT`；
- `MISSING_CAPABILITY`；
- `COMPETITOR_DOMINATED`；
- `UNSTABLE_ANSWER`；
- `INSUFFICIENT_ENTERPRISE_EVIDENCE`。

缺口关联问题、市场、产品、Observation、Ontology概念和证据状态。

## 11. 网站资产与 Schema

系统生成 JSON-LD 草稿，但不自创 Schema.org 类型。

| 页面 | 主要 Schema.org 类型 |
| --- | --- |
| 首页 | `Organization`、`WebSite` |
| 产品页 | `Product` 或 `ProductGroup` |
| 制造能力页 | `Service`、`DefinedTerm` |
| 案例页 | `Article`，不使用不存在的 `CaseStudy` 类型 |
| FAQ页 | `FAQPage`，问题和答案必须在页面中可见 |
| 规格和标准 | `PropertyValue`、`QuantitativeValue` |
| 导航 | `BreadcrumbList` |
| 图片和视频 | `ImageObject`、`VideoObject` |

制造能力可以通过 `Service`、企业 `knowsAbout`、`DefinedTerm`、`PropertyValue`、`sameAs`、`subjectOf` 和页面可见正文表达。优先使用具体标准属性；没有标准属性时才使用 `PropertyValue`。

FAQ 标记用于语义一致性，不承诺普通工业网站获得 Google FAQ 富结果。

### 11.1 WebAsset 状态

```text
DRAFT
→ VALIDATING
→ READY_FOR_REVIEW
→ APPROVED
→ PUBLISHED
→ SUPERSEDED / ARCHIVED
```

发布前检查：JSON-LD语法、Schema类型、必需字段、可见内容一致性、内部链接、语言版本、证据有效性和失效声明。

首期输出可下载的页面内容包和 JSON-LD，不直接修改生产网站。

## 12. 推荐规则

AssetRecommendation 优先级由四项组成：

```text
缺口严重度 × 商业重要度 × 证据就绪度 × 实施成本
```

证据充分时可建议：FAQ、产品页、能力页、案例页、行业专题页、结构化数据或已有页面修正。

证据不足时禁止生成营销事实，改为创建：补充证书、设备记录、检测报告、产品文档或案例证据的任务。

每条资产声明必须引用具体 Ontology concept、relation 和 KnowledgeEvidence。

## 13. API

```text
/api/v1/entity-profiles
/api/v1/ai-questions
/api/v1/question-sets
/api/v1/visibility-runs
/api/v1/manual-observations
/api/v1/visibility-observations
/api/v1/visibility-metrics
/api/v1/visibility-gaps
/api/v1/asset-recommendations
/api/v1/web-assets
/api/v1/schema-artifacts
/api/v1/provider-policies
```

耗时写操作返回 `202 + job_id`。ProviderPolicy 的写权限仅限管理员；普通用户只能看到安全的能力和限制摘要。

## 14. 异步任务

```text
AIEO_VISIBILITY_RUN
AIEO_OBSERVATION_ANALYZE
AIEO_MANUAL_IMAGE_EXTRACT
AIEO_METRICS_AGGREGATE
AIEO_GAP_DETECT
AIEO_ASSET_RECOMMEND
AIEO_SCHEMA_GENERATE
AIEO_SCHEMA_VALIDATE
```

每个 AI 任务保存 PromptVersion、AIRun、输入快照、结构化输出、模型、置信度、EntityProfile版本、Ontology快照和人工修正。

## 15. 权限

```text
aieo.read
aieo.manage_questions
aieo.run
aieo.review
aieo.manage_assets
aieo.publish_assets
```

Provider密钥只写不读，不进入日志、OpenAPI示例或前端缓存。所有资源按活动组织隔离。

## 16. 异常处理

- API限流或额度耗尽：等待后重试，不生成未提及结果；
- 模型不可用：记录样本缺失，不替换成其他模型冒充；
- 部分问题失败：运行进入 `PARTIAL_SUCCESS`；
- ProviderPolicy不允许保留原文：保存允许的聚合和审计信息；
- 截图OCR置信度不足：等待人工核对；
- EntityProfile更新：历史运行继续引用旧版本；
- Schema验证失败：禁止进入审核通过或发布状态；
- 页面内容和JSON-LD不一致：验证失败；
- 无证据声明：丢弃并创建补证据任务；
- API与网页版差异：并排展示，不计算平均值。

写操作错误继续使用 `code`、`message`、`recovery_action` 包络。

## 17. 测试与验收

- EntityProfile 每项能力可追溯到已批准 Ontology 证据；
- 问题库支持国家、语言、行业、产品和采购角色变体；
- 固定问题集、模型和参数可以重复执行；
- API监测和网页版抽检始终分开；
- 每个提及、引用、竞品和事实判断都有审计依据；
- ProviderPolicy 能阻止不允许保存的数据；
- JSON-LD 语法有效且与可见页面内容一致；
- 没有证据时不生成制造能力声明；
- 缺口能转化为网站资产或补证据任务；
- 人工修正保留原AI结果；
- 组织间数据零泄漏。

浏览器 E2E：

```text
发布 EntityProfile
→ 建立固定 QuestionSet
→ Fake Provider 运行
→ 查看 VisibilityObservation 与指标
→ 添加一次 ManualObservation
→ 验证两种模式分开统计
→ 发现缺口
→ 生成网站资产建议
→ 验证并审核 SchemaArtifact
```

## 18. 推荐开发切片

### B3：AIEO 基础

EntityProfile、问题库、FAQ/页面草稿、标准 JSON-LD 生成、验证和人工审核。

### B5：AI Visibility 监测

在 Lead Intelligence 和首批连接器稳定后，增加官方 API 基准监测、人工校准、指标、缺口和推荐闭环。

## 19. 外部标准参考

- Schema.org `Organization`：https://schema.org/Organization
- Schema.org `PropertyValue`：https://schema.org/PropertyValue
- Schema.org `DefinedTerm`：https://schema.org/DefinedTerm
- Google structured data guidelines：https://developers.google.com/search/docs/appearance/structured-data/sd-policies
- Google FAQ rich result change：https://developers.google.com/search/blog/2023/08/howto-faq-changes
- OpenAI API web search：https://platform.openai.com/docs/quickstart/make-your-first-api-request
- Gemini grounding terms：https://ai.google.dev/gemini-api/terms
- Perplexity Sonar API：https://docs.perplexity.ai/docs/sonar/quickstart
