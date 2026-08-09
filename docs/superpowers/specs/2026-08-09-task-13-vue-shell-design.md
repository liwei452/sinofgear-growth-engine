# Task 13 Vue 应用框架与会话登录设计

## 目标与边界

建立可真实运行的 Vue 3 应用壳、基于 Django Session 的登录流程、统一 API 客户端和新手首页。任务 14–16 的业务功能不在本阶段实现；对应导航保留独立受保护路径，并共享一个明确标注“功能即将开放”的占位页。

## 方案选择

采用“路由守卫 + 轻量认证状态 + 原生 fetch API 客户端”的方案。相比在每个页面自行拉取会话，它能在受保护内容挂载前完成 `/api/v1/auth/me`，避免未认证界面闪烁；相比引入完整状态管理框架，它更小、更容易审计。TanStack Vue Query 只承担服务端会话缓存与失效，不保存 CSRF token 或密码。

备选方案一是 Pinia 管理会话，但会增加当前阶段不需要的客户端状态层。备选方案二是每页 Query 加载认证，会造成守卫重复、潜在闪烁和不一致 redirect 处理。因此均不采用。

## 前端架构

- `src/api/client.ts`：所有请求统一 `credentials: "include"`；非 GET/HEAD/OPTIONS 请求先确保 CSRF cookie，再从 cookie 读取 token 写入 `X-CSRFToken`。统一处理 JSON、文本、204、网络错误和 HTTP 错误。
- `src/modules/auth/auth.ts`：定义会话类型与 `getCurrentUser`、`login`、`logout`。不使用 localStorage。
- `src/app/router.ts`：受保护路由在进入前查询真实会话；401/403 保存经过站内校验的目标路径并跳转登录。登录页只接受以单个 `/` 开头的本地路径，丢弃协议相对、绝对 URL 和非法值。
- `src/app/queryClient.ts`：保守重试策略；认证请求不自动重试。
- `src/app/AppShell.vue`：桌面侧栏、窄屏可开关导航、当前项状态、组织/用户信息和退出。
- `src/modules/dashboard/DashboardPage.vue`：含加载、错误、空状态和默认三步“下一步建议”；一个主要行动。
- `src/shared/components/NextStepPanel.vue`：可访问的建议列表和主要行动。
- `src/shared/components/PlaceholderPage.vue`：八个独立业务路径共享，解释阶段边界并提供返回首页/查看下一步建议。
- `src/modules/auth/LoginPage.vue`：产品定位、用户名、密码、提交禁用、统一失败提示和安全返回。

## 路由与导航

受保护路径包括：`/`、`/products`、`/knowledge`、`/assets`、`/content-factory`、`/reviews`、`/publishing-calendar`、`/platform-accounts`、`/analytics`。首页使用真实 Dashboard，其余路径使用占位页并通过路由 meta 提供中文标题，使侧栏当前项可识别。

未认证访问受保护路径时，登录 URL 使用 `redirect` query 保存原站内完整路径。只有以单个 `/` 开头且能解析为站内路径的值可被使用；`//host`、带协议 URL、反斜杠和控制字符均回退首页。

## CSRF 与后端改动

新增允许匿名 GET 的 `/api/v1/auth/csrf`，使用 Django `ensure_csrf_cookie` 发放 CSRF cookie并返回 204。登录、退出等非安全请求必须携带 cookie 和 `X-CSRFToken`；不关闭任何 CSRF 中间件，不把 token 写入 localStorage。Vite 将 `/api` 同源代理至本地后端。

## 视觉与可访问性

CSS token 定义 `--sg-brand: #005BA8`、hover、focus 和浅色辅助色。页面使用浅灰背景、白色卡片、明确标题层级和单一主按钮。表单具显式 label；状态消息使用 `role="status"` 或 `aria-live`；焦点轮廓清楚；窄屏导航可通过按钮打开、关闭和键盘访问；在 `prefers-reduced-motion` 下关闭非必要动画。

## 错误模型

`ApiError` 保存状态码、中文用户消息和可选恢复建议。响应优先读取 `detail`、`message`、`recovery_action`，但登录失败始终显示不区分账号存在性的固定中文提示。网络异常、401、403、5xx 映射为可恢复中文信息，界面不显示响应堆栈或内部对象。

## 测试策略

- Vitest + Testing Library + jsdom 测试真实组件与路由行为。
- API 客户端覆盖 credentials、CSRF、204、错误字段和网络/状态映射。
- 路由覆盖认证加载防闪烁、未登录跳转、安全返回和恶意 redirect。
- 登录覆盖提交禁用与统一失败。
- AppShell/Dashboard 覆盖中文导航、下一步建议、状态呈现和窄屏导航。
- Django focused test 覆盖 CSRF endpoint 发 cookie、204 和登录仍受 CSRF 保护。
- 最终执行 frontend test、lint、typecheck、build，以及后端 focused tests、Ruff、check、migration drift。
