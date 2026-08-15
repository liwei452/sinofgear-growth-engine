# Google Maps 客户发现管道 — 设计文档

日期：2026-08-16
状态：待用户审阅
所属阶段：Phase B1 潜客雷达 · 第一条自动化数据管道

## 1. 目标

在现有「发现引擎」上增加 Google Maps / Places 数据源，实现每天自动执行：

`城市 × 行业关键词 → 发现企业 → 去重 → 读取官网 → AI 判断行业/需求 → 发现公开联系方式 → 邮箱验证(可选) → AI 评分 → A/B/C 分级 → 生成开发信草稿 → 进入审批队列`

系统无人值守到「生成开发信草稿」为止，最终发送保留人工批准。

## 2. 已确认边界（合规，不越线）

- 只用官方 Google Places API；不抓地图网页、不模拟人工、不绕反爬。
- 原始 Places 数据按 Google 缓存政策处理（除 Place ID 外短期缓存）；永久库只存稳定去重键 + 我们自己的 AI 结论与证据快照。
- 官网只读公开页面，尊重 robots.txt，低频限速；不登录、不绕过、不抓私密或隐藏联系方式。
- 邮箱仅从公开渠道发现，验证为可选项；系统不自动发送，开发信只生成草稿并人工批准。
- 海关数据作为第二条管道，本次只做接口与字段预留，不实现。

## 3. 架构

复用现有 `growth` 模块的发现骨架，不做重写：

- 新增 `GooglePlacesSource`，与现有 `TedSource` / `ContractsFinderSource` 并列，统一实现 `fetch(query)` 与治理元数据。
- 新增「地图发现配置」：国家/城市、行业关键词、搜索半径、每日配额、执行时间（默认 02:00）、启用开关。
- 去重历史库：`Place ID` + 规范化域名/公司名/地址指纹作为稳定键，复用现有 `content_hash` / `record_hash` / `source_identity` 模式。
- 富化：官网抓取 → AI 行业/需求判断 → 公开联系方式发现 → 评分分级（A/B/C）→ OutreachDraft。
- 调度：复用现有 Celery beat `scan_due_discovery_profiles`（每小时扫描，`next_run_at` 控制每日 02:00）。

## 4. 数据模型（新增/扩展）

- `DiscoveryProfile` 增加 `source_code=GOOGLE_MAPS` 与地图配置字段（cities、keywords、radius_km、daily_quota、schedule_time）。
- `DiscoveryRun` 复用，`query_snapshot` 记录城市/关键词/配额。
- 去重键新增 `place_id`、`domain_fingerprint`、`address_fingerprint`。
- `CandidateEnrichmentSnapshot` 从「仅整理导入事实」扩展为「真实富化」模式：官网、公开联系方式、AI 结论、证据来源。

## 5. API 设置（用户只需填写）

新增「设置 → 数据源 → Google Maps」页，用户只需填/选最少内容：

- 填 Google Maps API Key（只填写、不回显、不明文记录）
- 选国家/城市（可多选，AI 可推荐工业城市）
- 选行业关键词（预置 gear / mining / conveyor / crusher / industrial machinery / gearbox repair / cement / agricultural / packaging 等，AI 可按产品推荐）
- 每日配额（默认 500）
- 执行时间（默认 02:00）
- 启用开关

## 6. 小白化 + AI 减少表单

- 向导式：先「连数据源」→「AI 推荐关键词/城市」→「确认配额」→「启动」。
- 所有复杂字段给默认值与中文解释；能自动推的由 AI 预填，用户只点确认。
- 每日早报：一张卡显示「今日发现 / 去重后新增 / AI 有效 / A 级 / 找到邮箱 / 已生成草稿」，一键进入待审核。

## 7. 分阶段落地

- M1：API 设置页（先让用户能填 key，并保存到安全配置）
- M2：Google Places 适配器 + 去重历史库 + 调度（先跑通「发现 → 去重 → 入库」）
- M3：官网富化 + AI 行业/需求判断 + 评分分级
- M4：开发信草稿 + 审批队列（不发信）
- M5：小试点（免费额度，每天 200–500 家），验证转化率后再放量

## 8. 成功指标

- 每天自动运行，到「草稿生成」全程无人干预。
- 同一家公司被多个关键词重复搜到时只建一条。
- 用试点数据评估：AI 有效客户率、A 级命中率、公开邮箱发现率。
