# SinofGear Growth Engine 换机交接与后续开发建议

更新时间：2026-08-10

## 1. 项目定位

SinofGear Growth Engine 是面向齿轮及机械制造外贸企业的 AI 社媒增长中台。

系统负责内容生产、多平台内容适配、发布排程、流量归因、公开社媒信号发现、潜客分析和 CRM 交接；不承担 CRM 客户管理、报价、销售跟进、自动成交、自动陌生私信或群发。

## 2. 当前代码状态

- 项目目录：`C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`
- Git 分支：`feature/phase-a`
- Phase A 最终代码提交：`7865358 fix: close phase a review round two`
- 此后只增加了本换机交接文档，未修改产品代码。
- 工作区：干净，无未提交源码
- Git 远程仓库：`https://github.com/liwei452/sinofgear-growth-engine.git`。
- 当前分支已跟踪：`origin/feature/phase-a`。
- GitHub 是换机恢复主路径；Git bundle 和源码 ZIP 继续作为离线备份。

## 3. 已完成的 Phase A

已完成并通过独立复审：

- 组织、成员、角色和权限隔离；
- Gear Manufacturing Ontology 工业知识层；
- 产品知识库、版本、知识关联和证据；
- 原始素材、产品关联及安全下载；
- Campaign 与 READY ContentBrief；
- 可审计 AI Job、PromptVersion、AIRun 和本体快照；
- MasterContent 与五个平台内容的生成、修改和人工审核；
- 平台账号、连接凭据与能力判断；
- 发布日历、幂等发布、失败记录和重试；
- UTM、短链、302、点击事件和活动/平台归因；
- 新手化中文界面、权限保护、键盘可用弹窗；
- OpenAPI、自动生成 TypeScript 契约和漂移检查；
- 独立种子数据和完整浏览器 E2E 验收。

最终验证基线：

- 后端：778 passed，1 个 Windows 符号链接权限测试 skipped；
- 前端：181 tests passed；
- 启动器：5 tests passed；
- Ruff、Django check、迁移漂移、OpenAPI、API drift、ESLint 零警告、typecheck、production build 全部通过；
- E2E 覆盖操作员与审核员切换、AI 审计、五平台审核、发布失败恢复、两次真实短链 302 和精确活动/平台归因。

## 4. 当前演示环境说明

当前 `http://localhost:3000` 是本机隔离演示环境：

- 使用临时 SQLite 数据库和临时文件存储；
- 使用 Fake AI 和 Mock 平台连接器；
- 数据不会迁移到新电脑，也不应作为正式业务数据；
- 测试账号：`phasea_e2e_admin`；
- 测试密码：`PhaseA-E2E-Only!`；
- 测试密码只能用于隔离演示，不能用于开发或生产。

## 5. 换机时必须带走的文件

代码已经上传 GitHub。仍建议将以下离线文件复制到移动硬盘或可信云盘：

1. `sinofgear-growth-engine-2026-08-10.bundle`：完整 Git 提交历史，推荐使用；
2. `sinofgear-growth-engine-source-2026-08-10.zip`：最终提交的纯源码快照；
3. 本交接文档。

不要复制：

- `.env`；
- `backend/.venv`；
- `frontend/node_modules`；
- `frontend/dist`；
- 临时 SQLite、临时素材和 Playwright 报告；
- 任何真实平台 Token 或生产密码。

## 6. 新电脑恢复方法

### 推荐：从 GitHub 恢复

安装 Git 后，在 PowerShell 执行：

```powershell
git clone "https://github.com/liwei452/sinofgear-growth-engine.git"
cd sinofgear-growth-engine
git switch feature/phase-a
git log --oneline -5
```

如果 GitHub 暂时无法连接，再使用下方 Git bundle 离线恢复。

### 离线备用：从 Git bundle 恢复

安装 Git 后，在 PowerShell 执行：

```powershell
git clone "D:\备份位置\sinofgear-growth-engine-2026-08-10.bundle" sinofgear-growth-engine
cd sinofgear-growth-engine
git switch feature/phase-a
git log --oneline -5
```

提交历史中必须包含：

```text
7865358 fix: close phase a review round two
```

### 仅使用源码 ZIP

解压 ZIP 即可获得源码，但不包含 Git 提交历史，不推荐作为唯一备份。

## 7. 新电脑建议安装

- Windows 11；
- Git；
- Python 3.12；
- Node.js 22 LTS；
- pnpm 10.14.0；
- Microsoft Edge 或 Google Chrome；
- Docker Desktop，用于正式的本地持久环境。

恢复后：

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec api python manage.py migrate
docker compose exec api python manage.py seed_initial_organization
```

浏览器打开 `http://localhost:3000`。

正式使用前必须替换 `.env` 中的所有开发密码和密钥。

## 8. Phase B 当前决策与边界

下一阶段是被动增长/潜客雷达：

```text
Keyword
→ MonitoringTask
→ SourceAccount / SourceContent
→ SourceSignal
→ LeadCandidate
→ LeadInsight
→ OutreachDraft
→ LeadHandoff
```

用户倾向选择浏览器辅助采集，但最终安全边界仍需在新电脑上确认。

建议只允许：

- 无需登录即可访问的公开页面；
- 用户提供链接、关键词或手动导入；
- 低频限速、可暂停和完整审计；
- 保存来源 URL、公开内容、平台和采集时间；
- 平台拒绝访问时停止。

明确不做：

- 模拟登录、验证码绕过、指纹浏览器、代理池或防封号；
- 抓取私信、隐藏联系方式或非公开数据；
- 自动陌生私信、群发或自动联系；
- CRM 销售管理。

## 9. 推荐的后续开发顺序

### Phase B1：公开来源与监测基础

- Keyword、KeywordGroup；
- MonitoringTask、运行频率、平台范围和审计；
- SourcePlatform、SourceAccount、SourceContent、PublicComment；
- SourceSignal 类型：COMMENT、POST_AUTHOR、CHANNEL_OWNER、PROFILE_MATCH、MENTION、HASHTAG_MATCH；
- 优先支持手动链接、CSV/JSON 导入和安全的浏览器辅助公开采集。

### Phase B2：潜客分析

- LeadCandidate 状态：DISCOVERED、ANALYZING、ANALYZED、REVIEWED、READY_FOR_HANDOFF、HANDED_OFF；
- 使用现有 Ontology、Job、PromptVersion 和 AIRun；
- 意向评分、公司/国家/行业/产品需求判断；
- 每个结论保留 SourceEvidence、模型、提示版本、置信度和人工修正。

### Phase B3：新手化潜客雷达界面

- 关键词库；
- 监测任务；
- 来源内容和信号；
- 潜客收件箱；
- 证据侧栏、评分解释、审核和批量忽略；
- 不设计自动发送按钮。

### Phase B4：联系建议与 CRM 交接

- OutreachDraft：公开回复建议、邮件/LinkedIn/WhatsApp 模板、联系理由和推荐渠道；
- LeadHandoff 必须包含 Candidate、Insight 和不可变 SourceEvidence；
- 先实现下载 JSON/CSV 与 Mock CRM；真实 CRM 连接后置。

### Phase C：真实连接与生产化

- 优先接官方 API：LinkedIn、Meta、YouTube；
- 正式 PostgreSQL、Redis、Celery、MinIO；
- HTTPS、域名、备份、监控、告警和密钥管理；
- 固定 MinIO 容器版本；
- 生产环境并发、任务恢复、对象存储和平台限流验证。

### 最终交付

- 服务器或云服务器部署；
- 浏览器版作为主系统；
- Windows 桌面快捷入口或 PWA，双击打开；
- Docker 安装包、管理员恢复手册和新手操作手册。

## 10. 新电脑继续开发时的第一句话

把本文件交给 Codex，并说明：

> 读取 `docs/project-handoff-2026-08-10.md`、现有架构文档和 Git 历史。Phase A 已完成，不要重做。先继续 Phase B brainstorming，确认受限公开采集边界，写独立设计文档并经我批准后，再写实施计划和代码。

## 11. 重要文档

- `README.md`
- `docs/architecture.md`
- `docs/phase-a-acceptance.md`
- `docs/superpowers/plans/2026-08-10-phase-a-review-round-2.md`
- `docs/superpowers/plans/2026-08-09-task-14-product-knowledge-libraries.md`
- `docs/superpowers/specs/2026-08-10-lead-intelligence-domain-design.md`
- `docs/superpowers/specs/2026-08-10-aieo-domain-design.md`
- `docs/superpowers/specs/2026-08-10-ontology-extension-design.md`

## 12. Phase B1 acceptance update (2026-08-11)

Phase B1 public-signal intake and lead intelligence is now implemented and accepted. The authoritative operating and verification record is `docs/phase-b1-acceptance.md`.

The completed boundary includes URL, screenshot, UTF-8 CSV, JSON, and paste intake; partial-success batches; immutable public evidence; deterministic low/watch/high evaluation; audited `LEAD_ANALYZE` execution; evidence-visible candidate review; organization isolation; retention redaction; an idempotent named-organization seed; atomic OpenAPI generation/checking; and a real browser journey through “确认值得跟进”.

The offline evaluation baseline contains 100 bilingual industrial samples and reached explicit-need recall 1.00, high-value precision 1.00, and evidence-reference coverage 1.00. Final verification reached 1185 passed / 1 skipped on the backend, 308 passed on the frontend, and 7 passed in the browser suite. Docker configuration could not be parsed on this particular machine because the `docker` executable is not installed or available on `PATH`; this is an environment limitation, not a successful Compose check.

The security and product boundary is unchanged: Phase B1 does not crawl protected platforms, collect private contacts, perform outreach, enrich companies, or hand data to a CRM. Company enrichment, outreach, and handoff remain Phase B2 work.
