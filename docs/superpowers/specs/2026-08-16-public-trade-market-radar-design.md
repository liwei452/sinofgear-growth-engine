# 公开贸易数据市场雷达设计

## 目标与边界

本切片把 UN Comtrade 官方公共贸易统计接入为“国家市场背景证据”，用于回答某国对 HS 848340、848390 或用户自定义 HS 的进口规模、同比变化、连续性、新鲜度和中国份额。宏观统计不得创建或暗示具体买家、联系人、采购意向或公司级海关记录。

不访问付费 API，不抓取网站，不接未知许可证数据，不真实外发，不修改独立站。测试和浏览器验收只用明确 Fake transport；正式模式未配置时显示真实空状态。

## 方案选择

采用独立的贸易快照域，而不是把统计塞进 `MarketCountryProfile` 的 JSON，也不复用 `IntentSignal`：

- `TradeDatasetSnapshot` 保存一条标准化官方统计记录，组织隔离且以规范查询与记录哈希幂等。
- `TradeSyncRun` 保存查询、来源能力、状态、计数和错误，允许同一请求安全重跑。
- 指标从快照透明计算，响应同时返回公式、分子、分母、期间和来源。
- 市场配置继续表达研究与观察状态；贸易快照只补充真实证据，不覆盖人工判断。

## 官方适配器边界

新增 `integrations.sources.comtrade`：

- 固定官方 HTTPS 主机 `comtradeapi.un.org`，禁止调用方传入 URL。
- `TradeQuery` 明确 reporter、partner、flow、HS、period、frequency 和记录上限。
- `TradeRow` 标准化 reporter/partner/flow/HS/period/value/quantity/unit/source URL/dataset version/fetched_at/provenance。
- `ComtradeSource` 依赖注入 `JsonTransport`；测试只使用 Fake transport，不访问外网。
- 限制超时、响应体、记录数、字段类型、HS 格式与允许 flow；错误统一为脱敏 `SourceAdapterError`。
- 来源治理记录 UNSD 所有者、官方公共 API、API 非网页抓取、允许字段、保留期、再分发限制和抓取时间。

真实 transport 的存在不等于自动启用。产品运行时默认关闭，只有后续明确配置时才允许官方请求；失败不得静默回退 Fake。

## 数据模型与幂等

`TradeSyncRun`：organization、source_code、trigger、status、query_snapshot、query_hash、capability_snapshot、fetched/created/duplicate/skipped、error_code、finished_at。相同组织和 query_hash 的成功运行可直接复用结果。

`TradeDatasetSnapshot`：organization、run、reporter_code/name、partner_code/name、flow、hs_code、period、frequency、trade_value_usd、quantity、quantity_unit、source_url、source_dataset、dataset_version、observed_at、fetched_at、freshness_days、record_hash、provenance。`organization + record_hash` 唯一，禁止物理删除。

记录哈希基于来源、reporter、partner、flow、HS、period、value、quantity、dataset version 的规范 JSON；重跑只增加运行审计，不重复建快照。

## 透明指标

按市场、HS 和期间返回：

- 进口规模：所选最新期间、partner=World 的进口 `trade_value_usd`；若仅有伙伴明细，则明确标记为伙伴明细求和。
- 同比变化：`(本期进口额 - 上年同期进口额) / 上年同期进口额 × 100%`；分母缺失或为零时显示无数据。
- 连续性：最近 N 个请求期间中有有效进口记录的期间数 / N；返回期间列表。
- 新鲜度：当前日期减最新 `observed_at` 或期间结束日的天数，并返回计算基准。
- 中国份额：同期 partner=China 进口额 / 同期 World 进口额 × 100%；任一输入缺失时显示无数据。

接口不产生加权总分或 AI 排名。每项都返回公式、输入记录 ID、数值、单位、来源 URL、dataset version 和 fetched_at。

## API 与页面

新增组织级接口：

- `POST /api/v1/growth/trade-syncs`：管理权限；验证 reporter、HS 和期间；默认配置关闭时返回 `CONFIGURATION_REQUIRED`。
- `GET /api/v1/growth/trade-snapshots`：读取权限；按 country/HS/period 过滤。
- `GET /api/v1/growth/trade-indicators`：读取权限；返回透明指标和证据输入。

现有市场工作台只增加轻量展开区：HS 输入默认 848340/848390、同步状态、快照表、公式明细与原始来源链接。未同步时解释“当前没有官方贸易快照；宏观数据不会生成买家公司”，并给出可执行的同步入口或未配置状态。既有“查看候选公司/导入许可名单/公开线索”链路保持不变。

## 企业级交易记录后续合同

定义文档化/类型化导入合同但不落地买家生成：角色 `IMPORTER`、`CONSIGNEE`、`SHIPPER`、`NOTIFY_PARTY`；每个主体包含原名、规范名、国家、地址、注册号/域名（若有）、实体匹配置信度、货代判定及理由。每批必须包含 source owner、access method、license/contract、allowed fields、retention、redistribution、territory、customer authorization、record date、source URL。货代或身份不确定记录必须进入人工审核，不能自动成为 Target Account 或联系人。

## 安全与测试

- 所有查询和快照严格按 organization 过滤；跨组织返回 404 或空集合。
- Fake 数据必须明确 `is_demo=true`，正式空工作区不得自动出现。
- 单测覆盖查询验证、规范化、响应上限、超时、非法 JSON、幂等、重跑、组织隔离、指标缺失分母和宏观记录不创建公司。
- 前端覆盖空状态、未配置、快照/公式/来源展示和刷新保留。
- 浏览器验收使用 fixture transport 完成同步→查看快照→查看公式，同时证明候选公司数量不变。

## 依据

UNSD 官方资料说明 UN Comtrade 是按 reporter、partner、commodity 和 flow 组织的国际商品贸易统计，包含价值及可用时的数量信息；数据会持续补充和修订。因此本产品保存抓取时点和数据集版本，并只把它解释为市场级统计背景。

