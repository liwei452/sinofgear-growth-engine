# AI 原生界面验收

这份说明用于验收 SinofGear Growth Engine 的普通模式。验收重点不是像素截图，而是用户能否从五个入口完成真实工作、看懂 AI 结论与下一步，并且不会看到内部对象名、原始状态或内部 ID。

## 打开普通模式

1. 按项目根目录 `README.md` 启动本地服务。
2. 打开 `http://localhost:3000` 并登录。
3. 产品默认进入普通模式，导航只显示“今天、推广、客户机会、效果、我的公司”。
4. 如果当前浏览器此前停留在高级功能，点击“返回普通功能”。切换不会退出登录，也不会改变当前组织。

## 浏览器验收范围

隔离的 Playwright launcher 会创建一次性 SQLite 数据库、文件存储和动态本机端口，写入稳定的验收记录，然后在 Chromium 中验证：

- “今天”只提供当前角色能处理的决定，并能进入正确普通页面；
- 推广方案从产品、目标、素材、审核、确定性生成一直走到五个渠道版本、发布、失败重试和效果回写；
- 客户机会可查看来源证据、完成人工复核，并下载真实 JSON 导出；CRM 未配置时不会显示“已交给 CRM”之类的假成功；
- “效果”展示基于真实点击记录的结论和业务名称，不把活动、平台或产品 UUID 当成界面标签；
- “我的公司”展示真实资料覆盖和缺口任务；没有产品时会引导补充产品；
- 普通与高级导航来回切换后，登录态和组织保持不变；
- 桌面 `1440×900`、平板 `820×1180`、手机 `390×844` 下五个普通入口均可访问，页面没有横向溢出。

浏览器旅程使用角色、文本、表单标签和真实响应作为同步点，不使用像素级截图基线。

## 运行验收

需要符合 `frontend/package.json` 要求的 Node.js 与 pnpm。完整浏览器验收：

```powershell
cd frontend
pnpm run test:e2e
```

按旅程定向运行：

```powershell
cd frontend
pnpm run test:e2e ai-decision-cockpit.spec.ts phase-b1-lead-intelligence.spec.ts
pnpm run test:e2e phase-a-active-growth.spec.ts
```

完整交付验证：

```powershell
cd frontend
pnpm test --run
pnpm run typecheck
pnpm run lint
pnpm run build
pnpm run api:check
pnpm run test:e2e:launcher
cd ..
backend\.venv\Scripts\python.exe -m pytest -q
cd frontend
pnpm run test:e2e
```

2026-08-12 的定向浏览器验证结果：决策驾驶舱 8 项通过，客户机会与 CRM 导出 2 项通过，Phase A 完整增长闭环 1 项通过。随后完整浏览器套件 12 项全部通过，其中还包含现有的 390px 长内容溢出回归。

## 确定性边界

验收环境中的 AI 内容生成和客户机会分析使用确定性 provider。它们会产生可重复、可审计的生成记录，适合验证权限、状态、来源和界面流程，但不会调用真实大模型服务。发布流程使用本地 mock connector，可稳定覆盖成功、失败和重试，也不会连接真实社交平台账号。

CRM 导出是真实能力：浏览器收到并下载由当前客户机会与来源证据生成的 JSON 文件，验收会读取文件内容并核对公司与证据。CRM 传输当前未配置；界面明确说明连接状态，不伪造远端已接收结果，也不在验收中调用外部 CRM。

## 当前限制

- 尚未接入真实 LLM provider；模型质量、费用、限流与生产延迟不在本轮验收范围内。
- 尚未配置真实 CRM connector；当前交付物是可下载、可审计的本地 JSON 导出。
- 尚未连接真实社交平台发布账号；浏览器闭环验证的是 connector 契约、任务状态、失败恢复与效果归因。
- 浏览器验收覆盖 Chromium 的三个代表性 viewport，不等同于所有浏览器和设备矩阵。
- 验收使用一次性本地数据，不读取或修改普通开发数据库、对象存储、生产密钥或外部账号。

## DeepSeek 验收边界

DeepSeek 正式能力已经接入，但自动验收仍使用确定性测试替身，不读取真实密钥，也不产生付费请求。真实冒烟测试只能由管理员明确使用 `--acknowledge-paid-call` 批准。

密钥只保存在当前 Windows 用户的凭据管理器中。Git、zip/备份、数据库、浏览器、日志和安装包都不携带密钥；更换 Windows 用户或电脑后必须重新输入。
