# SINOF 工业 B2B 外贸 Lead Intelligence Engine — 设计要点

日期：2026-08-16
状态：从外部调研吸收、待逐步落地

## 1. 目标架构

不再把重点放在「Google Maps 爬虫」，而是把发现、贸易、信号三类来源统一到一条工业获客链：

`Discovery / Customs / Signals → Company Resolution → Enrichment → Contact → ICP Scoring → Outreach → Email/LinkedIn/Website → Intent → Reply/RFQ → Quote → Won/Lost → Learning`

## 2. 吸收的六个关键思想

### ① 证据链（citation on every cell）
每个 AI 判断都应有：`value + confidence + source + evidence + updated_at`。现有 `IntentSignal.evidence_envelope`、`DiscoveryCandidate.source_governance`、`CandidateEnrichmentSnapshot.evidence_envelope` 已具备雏形，后续统一成一份可复用的引用结构，确保销售能回答「AI 为什么这么判断」。

### ② 联系人情报层（Contact Intelligence）
Maps 只回答「哪家公司值得开发」，不负责「找谁」。联系人发现、邮箱/领英、邮箱验证应作为独立能力，不塞进发现 Agent。

### ③ 工业采购信号（Signal Agent）
不监测 SaaS 式融资信号，而是监测工业信号：矿山扩产、新生产线、新水泥厂、设备大修、破碎机/减速机大修、停机检修、备件/设备招标、MRO 合同、工厂升级、招聘维修工程师。Signal Agent 回答「谁『现在』可能要买」。

### ④ 触达状态机
从「已发/未发」升级为多步状态：`DISCOVERED → QUALIFIED → ENRICHED → CONTACT_FOUND → EMAIL_VERIFIED → OUTREACH_READY → EMAIL_1_SENT → OPENED → SITE_VISITED → FOLLOW_UP_1 → REPLIED → RFQ → QUOTED → WON/LOST`，每步可追溯。

### ⑤ 贸易情报链（Customs Agent）
`HS Code → 贸易记录 → Importer → Company Resolution → Website → Company Intelligence → Product Match → Buyer Qualification`，而不是只下载海关 Excel。

### ⑥ 销售生命周期与学习闭环
报价审批、长期培育、人工/自动交接、成交反馈回流到评分与信号权重。

## 3. 落地顺序

1. 工业采购信号词汇表与检测器（Signal Agent 基础）
2. 联系人情报模型与邮箱验证边界
3. 触达状态机（扩展 Lead/FollowUp/Outreach 状态）
4. 证据链统一为可复用结构
5. 贸易情报链（在现有 UN Comtrade 之上扩展 Company Resolution）
