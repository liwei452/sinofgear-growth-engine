# 社媒 OAuth 外部激活运行手册

## 当前交付边界

本仓库已经具备 Facebook Page、Instagram Business、LinkedIn Company Page、TikTok 和 YouTube 的官方 OAuth 连接边界、加密凭据库、账号选择、生命周期状态、手工断开和发布连接器边界。

当前所有 Provider 默认关闭。本次开发和验收只使用本地 Fixture/Fake transport，没有创建平台应用、没有使用真实账号或密钥、没有发起真实 OAuth、没有提交平台审核、没有调用付费 API、没有发布任何真实内容，也没有进行生产部署或 DNS 修改。

## 外部激活前置门槛

以下工作必须由有权管理域名、云环境和平台开发者账号的负责人执行，且每一步都应单独留存审批记录：

1. 部署经过验收的稳定版本，并启用有效 HTTPS。
2. 将 `app.sinfogear.com` 指向该稳定环境，验证 TLS、CSRF、会话 Cookie 和回调路径。
3. 准备公开可访问且内容真实的隐私政策、服务条款和数据删除说明页面。
4. 分别在 Meta、LinkedIn、TikTok 和 Google Cloud 创建企业拥有的平台应用。
5. 在平台后台登记准确的 HTTPS 回调地址、允许域名、隐私政策、服务条款和数据删除地址。
6. 在生产 Secret Manager 中保存客户端密钥和 32 字节凭据加密主密钥；应用环境只保存秘密引用，不保存明文。
7. 配置公开客户端 ID、回调地址、允许来源、API 版本和秘密引用，但继续保持 Provider `enabled=false`。
8. 在各平台沙箱中核对所申请权限的最小性，完成所需企业验证与平台审核。
9. 每次只启用一个 Provider，先由管理员连接一个公司自有账号，确认账号选择、能力标签、探测、刷新、重新授权和断开流程。
10. 真实发布必须作为独立审批：选择一条已人工批准的测试内容，再由有权人员明确确认第一次真实发布。账号授权本身不代表允许发布。

## 建议回调地址

| Provider | 建议回调地址 | 说明 |
| --- | --- | --- |
| Meta（Facebook / Instagram） | `https://app.sinfogear.com/api/v1/platform-connections/FACEBOOK/callback` | Meta 共用一套应用和令牌交换，连接后再选择 Facebook Page 或其关联的 Instagram Business。 |
| LinkedIn | `https://app.sinfogear.com/api/v1/platform-connections/LINKEDIN/callback` | 仅选择管理员可管理的 Company Page。 |
| TikTok | `https://app.sinfogear.com/api/v1/platform-connections/TIKTOK/callback` | 未通过公开发布审核时必须显示“仅私密发布”。 |
| YouTube | `https://app.sinfogear.com/api/v1/platform-connections/YOUTUBE/callback` | 只申请上传所需最小权限；当前产品将其标记为上传型能力。 |

登记前必须以最终生产路由再次核对回调地址；不得使用本地地址、通配符或 HTTP。

## 服务端配置顺序

1. 设置 `SOCIAL_OAUTH_ALLOWED_ORIGINS=https://app.sinfogear.com`。
2. 在 Secret Manager 保存平台密钥，并分别设置 `*_CLIENT_SECRET_REFERENCE`；不要把明文放进 `.env`、数据库或前端。
3. 设置 `SOCIAL_OAUTH_TOKEN_KEY_REFERENCE` 和当前 `SOCIAL_OAUTH_TOKEN_KEY_VERSION`。
4. 设置各平台公开 ID、回调地址；LinkedIn 还必须设置已支持的 `LINKEDIN_API_VERSION`。
5. 保持 `META_OAUTH_ENABLED`、`LINKEDIN_OAUTH_ENABLED`、`TIKTOK_OAUTH_ENABLED`、`YOUTUBE_OAUTH_ENABLED` 为 `false`，先执行配置自检。
6. 平台审核完成后才设置对应 `*_AUDITED=true`；该值不得早于实际审核结果。
7. 在维护窗口内只把一个 Provider 的 `*_OAUTH_ENABLED` 改为 `true`，完成单账号验证后再考虑下一个。

密钥永不通过 API 响应、前端表单、日志或错误详情回显。轮换主密钥时先运行带 `--dry-run` 的轮换命令，按组织分批执行并保留回滚窗口。

## 单 Provider 激活检查

- 设置中心和推广页显示的平台名称、审核限制与发布模式与平台后台一致。
- OAuth state 一次性使用且按用户、组织和平台绑定；回调过期或重复使用会失败关闭。
- 账号选择器只显示当前授权人有权管理的公司账号。
- 数据库只出现不透明 `secret_reference`，没有 access token、refresh token、client secret 或授权码明文。
- 探测和刷新错误只显示稳定错误码；`INVALID_GRANT` 会进入“需要重新授权”，不会覆盖仍有效的旧凭据。
- 断开连接需要明确确认；即使平台撤销接口失败，也会停用本地连接、清除密文并保留内容、发布和效果历史。
- TikTok 未获公开发布资格时保持 `PRIVATE_ONLY`；YouTube 仅显示上传能力。
- 未人工批准内容、跨组织账号和缺少能力的账号均不能进入发布。
- 授权验证期间不得调用发布接口。

## 第一次真实发布的独立门槛

完成 OAuth 激活后仍保持真实发布关闭。第一次真实发布前需再次确认：内容已经人工批准、事实证据可追溯、素材版权明确、CTA/UTM 正确、目标公司账号正确、平台权限已审核、回滚和删除方式可用。由有权人员在界面进行一次明确确认，仅发布一条低风险测试内容并人工核对平台结果；不得自动扩展到其他渠道或批量内容。

## 回滚

1. 将对应 `*_OAUTH_ENABLED` 立即改回 `false`，阻止新的授权、刷新和平台调用。
2. 在产品中明确断开受影响账号，使密文凭据失效；保留业务与审计历史。
3. 必要时在平台开发者后台撤销应用令牌或暂停应用，但不要删除本地业务历史。
4. 若主密钥疑似泄露，暂停全部 Provider，按版本执行密钥轮换并复核所有活动凭据。
5. 记录稳定错误码、时间、组织、平台和处置结果；禁止把请求头、响应原文或令牌写入事故记录。

## 本地验收记录

2026-08-15 本地最终验收结果：

- 后端 `pytest -q`：1018 passed，1 skipped。
- 后端 Ruff：通过；迁移漂移：`No changes detected`。
- 后端 OpenAPI 合同已包含在全量测试中通过。
- 前端 Vitest：39 个测试文件、243 项测试全部通过。
- 前端 Playwright：4/4 通过，其中五渠道 Fixture OAuth 用例确认授权、账号选择、刷新保留，且发布接口调用为 0。
- 前端 ESLint、Vue TypeScript、API 生成物检查：全部通过。
- 前端生产构建：185 个模块转换完成并成功生成产物。
- 跟踪配置扫描：所有 Provider 默认 `false`；示例文件中的客户端 ID、回调、秘密引用和允许来源均为空；只存在显式测试用秘密引用。

这些结果只证明本地激活底座可验收，不代表任何真实平台已经连接或审核通过。
