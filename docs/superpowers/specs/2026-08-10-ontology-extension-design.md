# Gear Manufacturing Ontology Extension Design

日期：2026-08-10

状态：待用户最终审阅

所属阶段：Phase B 基础设计

## 1. 目标

本设计在 Phase A 已完成并验证的 Gear Manufacturing Ontology 上增加企业制造能力和客户需求语义，使同一知识层同时服务：

- Content Intelligence：生成有企业证据支持的工业内容；
- Lead Intelligence：把公开信号映射为可复用需求并匹配制造能力；
- AIEO：发布准确企业实体、网站资产和 AI 可见度基准；
- Future Market Intelligence：聚合需求和市场信号形成趋势建议。

扩展采用加法迁移，不重建本体、不修改历史 ID、不回写历史 AIRun 快照。

## 2. Phase A 基线

现有 `knowledge` 模块已经具备：

- `KnowledgeConcept`；
- `KnowledgeRelation`；
- `KnowledgeAlias`；
- 不可变 `KnowledgeEvidence`；
- SYSTEM 与 ORGANIZATION 两级作用域；
- SUGGESTED、APPROVED、REJECTED、DEPRECATED 生命周期；
- 概念和关系证据关联；
- 关系类型规则；
- `IS_A` 同类型和无环校验；
- 组织可见性校验；
- 最深两层的不可变 Ontology 快照；
- Product 与 Concept 的版本化关联。

现有概念类型继续保留：

```text
PRODUCT_TYPE
PARAMETER
MATERIAL
PROCESS
STANDARD
APPLICATION
INDUSTRY
CUSTOMER_TYPE
PURCHASE_INTENT
```

## 3. 建模原则

### 3.1 Process 不等于 Capability

`Grinding`、`Hobbing` 和 `Carburizing` 是可复用的加工过程。`SinofGear can grind DIN 6 helical gears` 是带产品、参数、适用范围和企业证据的能力。

因此现有 `Grinding` 保持 `PROCESS`，不迁移为 `CAPABILITY`。

### 3.2 Parameter 不等于 Requirement

`Accuracy Grade`、`Quantity` 和 `Delivery Days` 是参数。`DIN 6 accuracy`、`200 replacement gears` 和 `urgent delivery` 是客户或市场需求。

PARAMETER 描述维度，REQUIREMENT 描述要满足的业务需要。

### 3.3 Purchase Intent 不等于 Requirement

`looking for supplier`、`need replacement` 和 `request quote` 是购买意向。需求描述需要什么，意向描述购买行为处于什么状态。

### 3.4 Evidence 不是 Concept

Phase A 已有一级 `KnowledgeEvidence`。本阶段不增加 `EVIDENCE` ConceptType，也不创建 `SUPPORTED_BY` 图边。概念和关系继续通过现有证据关联表获得支持。

### 3.5 客户事实不污染共享本体

单个 Lead 的数量、交期和原始评论保存在 LeadInsight 与 SourceEvidence。Ontology 只保存可复用的 Requirement 语义和已批准市场知识。

## 4. 新增概念类型

### 4.1 CAPABILITY

表示组织能够可靠完成、并有证据支持的制造或质量能力。

示例：

- `DIN 6 Helical Gear Grinding Capability`；
- `Small Batch Custom Gear Manufacturing`；
- `Klingelnberg Gear Inspection Capability`；
- `Carburized Gear Shaft Production Capability`。

CAPABILITY 通常为 ORGANIZATION 作用域。SYSTEM 作用域可以保存通用能力分类，例如 `Gear Grinding Capability`，但不能声称 SinofGear 已具备该能力。

批准一个组织级 CAPABILITY 至少需要一条 APPROVED KnowledgeEvidence。

### 4.2 REQUIREMENT

表示可以跨潜客、内容和市场复用的客户或市场需要。

示例：

- `Replacement Helical Gear`；
- `DIN 6 Accuracy`；
- `Small Batch Production`；
- `Urgent Delivery`；
- `Reverse Engineering from Sample`；
- `Packaging Machine Gear Reliability`。

通用 REQUIREMENT 优先保存为 SYSTEM 作用域。组织特有的市场术语可以在 ORGANIZATION 作用域建议和审核。

## 5. 新增关系谓词

| Predicate | Subject | Object | 含义 |
| --- | --- | --- | --- |
| `SUPPORTS_PRODUCT` | CAPABILITY | PRODUCT_TYPE | 能力可以服务的产品 |
| `USES_PROCESS` | CAPABILITY | PROCESS | 能力依赖的加工过程 |
| `SATISFIES_REQUIREMENT` | CAPABILITY | REQUIREMENT | 能力能够满足的需求 |
| `REQUIREMENT_FOR` | REQUIREMENT | PRODUCT_TYPE、APPLICATION、INDUSTRY | 需求适用的产品或场景 |

现有谓词扩展允许类型：

| Existing Predicate | 新增 Subject / Object 规则 |
| --- | --- |
| `APPLIES_TO` | Subject 增加 CAPABILITY；Object 保持 APPLICATION、INDUSTRY |
| `COMPLIES_WITH` | Subject 增加 CAPABILITY；Object 保持 STANDARD |
| `REQUIRES_PARAMETER` | Subject 增加 REQUIREMENT 和 CAPABILITY；Object 保持 PARAMETER |
| `RELEVANT_TO_CUSTOMER_TYPE` | Subject 增加 CAPABILITY、REQUIREMENT |

`IS_A` 继续要求 subject 和 object 为同一 ConceptType，并继续拒绝环。

不添加语义重复的双向关系。反向查询由数据库关系和服务层实现。

## 6. 关系示例

```text
org:din6-helical-grinding [CAPABILITY]
    SUPPORTS_PRODUCT         → system:helical-gear [PRODUCT_TYPE]
    USES_PROCESS             → system:grinding [PROCESS]
    COMPLIES_WITH            → system:din [STANDARD]
    APPLIES_TO               → system:packaging-machinery [INDUSTRY]
    REQUIRES_PARAMETER       → system:accuracy-grade [PARAMETER]
    SATISFIES_REQUIREMENT    → system:din6-accuracy [REQUIREMENT]

system:replacement-helical-gear [REQUIREMENT]
    REQUIREMENT_FOR          → system:helical-gear [PRODUCT_TYPE]
    RELEVANT_TO_CUSTOMER_TYPE→ system:machine-maintainer [CUSTOMER_TYPE]
```

组织级能力概念和关键关系都必须关联例如检测报告、设备记录、产品文档或批准案例等 KnowledgeEvidence。

## 7. Evidence 扩展

保留现有 EvidenceType：

```text
PRODUCT_DOCUMENT
PUBLIC_SOURCE
HUMAN_ENTRY
STANDARD_REFERENCE
```

新增细分类型：

```text
EQUIPMENT_RECORD
CERTIFICATE
INSPECTION_REPORT
CASE_RECORD
```

建议新增不可变元数据：

- `content_hash`：证据内容指纹；
- `language`；
- `issued_at`；
- `valid_until`；
- `asset_reference`：通过现有 source object 机制关联私有 Asset；
- `provenance_method`：上传、系统生成、公开页面或人工录入。

证据质量由四项独立描述，不压缩成一个不可解释总分：

- `authority`：来源权威性；
- `directness`：是否直接证明声明；
- `recency`：时效性；
- `scope_fit`：证据覆盖范围是否匹配声明。

四项判断保存在版本化 `KnowledgeEvidenceAssessment` 中，包含 reviewer、reviewed_at 和理由；不回写 KnowledgeEvidence 的不可变来源事实。证据过期后可以创建新评估，历史评估继续保留。

过期证书或失效设备记录不删除，通过 `DEPRECATED` 和 `valid_until` 阻止进入新的对外快照。

## 8. SourceEvidence 与 KnowledgeEvidence

Lead Intelligence 的 SourceEvidence 证明“某公开账号在某来源留下了某信号”。KnowledgeEvidence 证明“SinofGear 或通用工业知识的某项事实”。

SourceEvidence 不得自动成为 KnowledgeEvidence。

允许的提升流程：

```text
SourceEvidence
→ AI建议市场 Requirement
→ 人工核对来源和代表性
→ 创建 SUGGESTED KnowledgeEvidence / Requirement
→ 人工审核
→ APPROVED 后进入新 Ontology 快照
```

潜客评论永远不能直接证明 SinofGear 的制造能力。

## 9. 作用域

### SYSTEM

用于通用工业语义：产品类型、过程、材料、标准、行业、参数、客户类型、购买意向和通用需求。

### ORGANIZATION

用于 SinofGear 特有能力、企业术语、已验证案例关联和私有证据。

组织级关系可以引用本组织概念或 SYSTEM 概念，但不能引用其他组织概念。SYSTEM 关系只能引用 SYSTEM 概念。

## 10. 生命周期与审批

继续沿用：

```text
SUGGESTED → APPROVED / REJECTED → DEPRECATED
```

审批硬门槛：

- CAPABILITY 必须有至少一条 APPROVED KnowledgeEvidence；
- 组织级 CAPABILITY 的 `COMPLIES_WITH`、`SUPPORTS_PRODUCT` 和 `SATISFIES_REQUIREMENT` 关系必须有证据；
- AI只能创建 SUGGESTED 概念、别名、关系和证据；
- 只有人工审核能批准；
- APPROVED 对象修改时创建新版本，不静默覆盖；
- 已被历史 AIRun 引用的版本不可删除。

## 11. Ontology 快照

现有不可变快照机制继续使用。调用方显式选择根概念：

- Content：产品、能力、工艺、材料、标准和行业；
- Lead：Requirement、Purchase Intent、客户类型、产品和匹配能力；
- AIEO：EntityProfile 中批准的产品、能力、标准和证据。

最大图展开深度继续保持 0–2。若调用方需要更多内容，应显式增加根概念，而不是无限遍历整个图。

快照新增类型和谓词后继续保存：概念版本、关系版本、证据引用和组织覆盖。历史快照不迁移、不重算。

## 12. 产品知识库集成

现有 ProductConceptLink 角色继续保留：TYPE、MATERIAL、PROCESS、STANDARD、APPLICATION、PARAMETER。

新增可选角色：

- `CAPABILITY`：Product 依赖或证明的组织能力；
- `REQUIREMENT`：Product 可以满足的客户需求。

角色类型规则：

- CAPABILITY 只能链接 APPROVED CAPABILITY；
- REQUIREMENT 只能链接 APPROVED REQUIREMENT；
- 链接继续不可变并通过 retire 创建历史；
- ARCHIVED Product 不能接受新链接。

## 13. API 与服务

不创建第二个 Ontology 应用，继续使用：

```text
/api/v1/knowledge/concepts
/api/v1/knowledge/relations
/api/v1/knowledge/aliases
/api/v1/knowledge/evidence
/api/v1/knowledge/resolve
```

列表接口增加 concept type、predicate、status、scope、evidence validity 和更新时间过滤。

服务层新增明确查询：

- 产品的已批准能力；
- Requirement 对应的产品、行业和参数；
- 能满足某 Requirement 的已批准 Capability；
- EntityProfile 可发布能力和证据；
- LeadInsight 可用的 Requirement 匹配上下文。

所有查询继续执行组织可见性和状态过滤。

## 14. 数据迁移

1. 增加 `CAPABILITY`、`REQUIREMENT` choices 和新谓词；
2. 扩展 relation type rules；
3. 增加 EvidenceType 和不可变元数据；
4. 增加 ProductConceptLink 的 CAPABILITY、REQUIREMENT 角色；
5. 以幂等 seed 增加通用 Requirement 和 Capability 分类；
6. 按人工确认创建 SinofGear 组织级 CAPABILITY；
7. 不修改现有概念、关系、产品链接和 AIRun 快照；
8. 运行迁移漂移、OpenAPI 和生成 TypeScript 契约检查。

数据迁移不得把现有 PROCESS 自动转换为 CAPABILITY，也不得根据产品自由文本自动创建 APPROVED 能力。

## 15. 与其他领域集成

### Lead Intelligence

LeadInsight 保存识别出的 Requirement concept IDs、匹配 Capability IDs、KnowledgeEvidence IDs 和具体 Ontology 快照。SourceEvidence 继续作为潜客证据。

### AIEO

EntityProfile 只选择 APPROVED Product、Capability、Industry、Process、Standard、Requirement 和 KnowledgeEvidence。无证据能力不能发布。

### Content Intelligence

ContentBrief 和 AIRun 可以引用新 Capability 和 Requirement，但继续使用现有人工审核状态机。

### Future Market Intelligence

B6 可以聚合匿名化 Requirement 和 SourceSignal 趋势。本阶段不新增 Market Intelligence 模型，也不把单个潜客数据写入共享 SYSTEM 图谱。

## 16. 测试与验收

- 新 ConceptType 可以创建、建议、批准、拒绝和废弃；
- 所有新谓词严格执行 subject/object 类型规则；
- `IS_A` 同类型和无环规则不退化；
- SYSTEM/ORGANIZATION 可见性不退化；
- 无 APPROVED Evidence 的组织级 CAPABILITY 不能批准；
- 失效证据不会进入新 AIEO 或 Content 快照；
- SourceEvidence 不能绕过审核成为 KnowledgeEvidence；
- Product CAPABILITY/REQUIREMENT 链接遵守类型、版本和归档规则；
- Lead 快照包含 Requirement 和匹配 Capability；
- AIEO EntityProfile 不包含未批准或无证据能力；
- 历史 AIRun 快照在迁移后字节级语义不变；
- 组织间概念、关系和证据零泄漏；
- seed 重跑幂等；
- OpenAPI、生成契约和迁移检查通过。

浏览器 E2E：

```text
创建组织级 DIN 6 Grinding Capability
→ 关联 Product、Process、Standard、Industry 和 Requirement
→ 因缺证据无法批准
→ 上传并批准 Inspection Report Evidence
→ 批准 Capability 和关系
→ 在 LeadInsight 中匹配该 Capability
→ 在 EntityProfile 中发布该 Capability
→ 查看两个 AIRun 各自保存的不可变 Ontology 快照
```

## 17. 开发顺序约束

Ontology 扩展是 Lead Intelligence 分析和 AIEO EntityProfile 的共同前置，但只实现本设计中的加法类型、关系、证据规则和查询。不要借此重写 Phase A 图谱、产品库或 AI 审计架构。
