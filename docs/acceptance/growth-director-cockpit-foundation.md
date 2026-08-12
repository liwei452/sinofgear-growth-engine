# Growth Director 驾驶舱基础验收

验收日期：2026-08-13

## 本批次交付

- 后端 Growth Director 提案、人工决定、组织隔离、权限、并发保护和审计记录。
- `GET /api/v1/director/cockpit` 聚合最多三项待决定事项、真实任务和真实近期结果。
- 首页只消费驾驶舱合同，并提供批准、要求调整、拒绝和可恢复错误交互。
- 普通模式固定五个入口：今天、产品资料、推广、客户机会、效果。
- 管理员 AI Agent 中心展示 Growth Director、Content Agent、Lead Agent、AIEO Agent、Analytics Agent 的真实就绪状态；本批次没有自动调度开关。
- 只读用户可查看提案依据，但不会看到决定按钮。

批准只记录人工授权；本批次不会绕过现有内容、潜客、发布或 CRM 服务执行后续动作。

## 可复现验证记录

从 `backend` 执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
$env:DJANGO_SETTINGS_MODULE='config.test_settings'
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py spectacular --file "$env:TEMP\sinofgear-openapi.yml" --validate
```

结果：1432 passed、5 skipped；Ruff 通过；无迁移漂移；OpenAPI 0 errors（存在 6 个既有 enum 命名警告）。

真实 PostgreSQL 16 并发套件：

```powershell
$env:DIRECTOR_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:55432/postgres'
$env:DJANGO_SETTINGS_MODULE='config.postgres_test_settings'
.\.venv\Scripts\python.exe -m pytest apps/director/tests/test_concurrency_postgres.py -q
```

结果：4 passed in 10.62s。测试使用本机临时 PostgreSQL 16 实例，完成后已正常停止。

从 `frontend` 执行：

```powershell
pnpm api:check
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
pnpm test:e2e
```

结果：API 合同、ESLint、TypeScript、545 个单元测试和生产构建通过；一次完整 `pnpm test:e2e` 运行中 20/20 通过（47.6s）。

浏览器验收覆盖 1440×900 桌面与 390×844 手机：五入口顺序，加载/错误/空/成功状态，真实批准，调整与拒绝中文理由，只读控制隐藏，五 Agent 诚实状态，导航和对话框焦点返回，横向溢出检查。页面使用蓝白主色、清晰卡片层级和中文普通模式文案；普通模式未发现伪造指标或内部对象名。

## 后续已批准批次

本批次不包含以下能力，也不会在界面中宣称它们已经运行：

1. 产品手册上传、解析与自动形成企业知识；
2. 五个平台的真实 OAuth、账号连接和自动发布；
3. 公开互动的自动监测、采集、证据化与潜客筛选；
4. AIEO 实际执行与完整 Analytics 反馈闭环。

CRM 接口边界继续保留；真实 CRM 交接仍需后续批次接入，并维持人工批准和证据链。
