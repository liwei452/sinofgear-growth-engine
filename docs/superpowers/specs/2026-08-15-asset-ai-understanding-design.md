# 资料 AI 理解与事实确认设计

## 目标

在现有素材库中增加一条可见、可追溯的纵向闭环：用户上传 PDF/图片或选择已有素材，选择关联产品，启动可重试的解析任务；系统展示明确标注为 Fake Provider 的候选事实及页码/区域/原文证据；用户逐条批准或驳回；只有批准项进入产品事实库。当前不接真实多模态模型、OCR、付费 API 或独立站。

## 用户体验

素材卡片增加“准备产品事实”。启动前必须选择现有产品。详情区只显示五类信息：解析状态、提供方真实性、已识别内容、缺失/不确定项、候选事实。每条事实显示分类、值、置信度、风险、文件、页码/区域和原文引用。

- `Fake Provider · 本地演示` 始终醒目标注，不能出现“AI 已真实理解”的措辞。
- 高风险字段（价格、交期、精度、认证、材料、产能）必须人工批准。
- 低风险字段也先进入待确认，不自动写入已验证事实。
- 图片或扫描 PDF 在未配置 OCR 时返回“部分完成”，保留已有元数据但不编造视觉事实。
- 失败任务可从同一素材重试，无需重新上传。

## 数据与边界

### Job

新增 `ASSET_UNDERSTAND` 类型，沿用现有 Job/JobAttempt 的排队、认领、失败、重试和不可删除审计语义。`input_snapshot` 只保存组织、素材、产品、校验和和安全限制，不保存二进制或密钥。

### ProductEvidenceFact

在 `assets` 应用新增组织隔离模型：

- 关联 `Product`、`MaterialAsset`、`Job`、`AIRun`；
- `category`: PRODUCT / SPECIFICATION / PROCESS / APPLICATION / STANDARD / ADVANTAGE；
- `field_name`、`value`、`confidence`；
- `source_page`、`source_region`（归一化 `[x, y, width, height]`，整页文本可为空）、`source_excerpt`；
- `risk_level`: STANDARD / HIGH；
- `review_status`: SUGGESTED / VERIFIED / REJECTED；
- `provider_label`、`is_demo`、审核人/时间/备注。

批准意味着该候选事实成为现有产品事实库中的“已验证证据事实”；下游 ICP 与内容只能读取 `VERIFIED` 项。首期不把值自动回填到 Product 的结构化高风险字段，避免无意覆盖用户已有产品数据。

## 解析与 Fake Provider

处理器分两层：

1. `DocumentTextExtractor` 只负责从机器可读 PDF 提取有界文本和页码，不执行文档指令；
2. `FakeAssetUnderstandingProvider` 只从明确的 `Label: Value` 行生成候选事实，原文逐字作为证据。它不推断联系人、认证、性能、价格或采购意图。

图片在当前切片只完成文件安全检查和任务审计，返回无候选事实的部分结果，并提示真实 OCR/图像理解尚未配置。这样能验证上传、任务、失败/重试和人工确认边界，同时不把文件名或既有产品名伪装成视觉识别结果。

## 安全限制

- 解析仅接受 PDF、JPEG、PNG、WebP；视频不可进入理解任务。
- 单份解析上限 20 MiB、PDF 最多 30 页、每页解压内容流最多 10 MiB、总提取文本最多 100,000 字符。
- 文本作为 JSON 数据传入提供方，不拼接成可执行指令；对提示注入短语只记录风险提示，不服从内容。
- 部分页面失败时保留成功页面与告警；完全失败才标记 Job FAILED。
- 所有查询和审核均按当前组织过滤，防止跨组织读取或审核。

## 开源组件评估与复用记录

| 组件 | 版本/许可证 | 维护与体量 | 决定 | 修改与回滚 |
|---|---|---|---|---|
| pypdf | 6.14.x / BSD-3-Clause | 活跃、纯 Python、依赖小 | 选用，仅机器可读 PDF 文本和页码 | 不复制源码；通过 `DocumentTextExtractor` 适配。移除依赖并替换适配器即可回滚 |
| pdfplumber | 0.11.x / MIT | 活跃，但引入 pdfminer/Pillow/pypdfium2 | 暂缓，后续真实表格提取再评估 | 当前无代码/依赖 |
| Tesseract OCR | 5.x / Apache-2.0 | 成熟，但需系统二进制和语言包 | 暂缓，保持 OCR 连接器边界 | 当前无二进制/模型数据 |
| pypdfium2 | 5.x / Apache-2.0 与 BSD 组件 | 活跃，需平台二进制 wheel | 暂缓，后续 PDF 渲染再评估 | 当前无代码/依赖 |
| PyMuPDF | 双许可证（AGPL/商业） | 成熟但与当前闭源产品许可证边界不合 | 排除 | 不引入 |

第三方代码不 Fork、不复制。唯一新增运行依赖固定为 `pypdf>=6.14,<6.15`；升级必须重新跑恶意/超大 PDF 限制测试。

## API

- `POST /api/v1/assets/{asset_id}/understanding`：以 `product_id` 创建并本地执行任务；重复请求幂等返回同一结果。
- `GET /api/v1/assets/{asset_id}/understanding`：返回最近任务、告警和候选事实。
- `POST /api/v1/assets/{asset_id}/understanding/retry`：仅重试失败且未超限的任务。
- `POST /api/v1/assets/facts/{fact_id}/review`：`APPROVE` 或 `REJECT`，记录审核人和备注，不触发外部动作。

## 验收

浏览器证明：上传/选择 PDF → 选择产品 → 准备事实 → 查看 Fake 标识、状态、候选值和页码原文 → 批准高风险事实 → 刷新后仍为已验证。另验证图片无 OCR 时不编造事实、跨组织不可见、超限被拒绝、失败任务无需重传即可重试。最后运行定向后端/前端测试、全量测试、构建和 E2E。
