# DeepSeek 产品 AI Provider

该适配层用于产品内的 Agent 判断和受控内容生成，不是开发代码助手。默认使用 `fake` 离线模式；离线结果会在界面明确标识，且仍需人工审核。

## 推荐启用方式

组织管理员进入 **设置 → AI 模型**（`/settings/ai-model`），选择 `deepseek-chat` 或 `deepseek-reasoner`、填写每日预估费用上限并保存 API Key。

- API Key 在服务端加密保存，保存后不会由 API 返回或在界面回显。
- 组织配置优先于环境变量；停用或删除组织配置后，不会绕过该选择使用环境密钥。
- 测试连接只访问固定的 DeepSeek 官方地址 `https://api.deepseek.com/chat/completions`。

开发环境仍兼容服务端环境变量：

```text
PRODUCT_AI_PROVIDER=deepseek
PRODUCT_AI_MODEL=deepseek-chat
DEEPSEEK_API_KEY=<development-only server secret>
```

生产组织应使用管理员页面，而不是共享环境密钥。没有组织配置时，`PRODUCT_AI_PROVIDER=fake` 保持完全离线；选择 DeepSeek 但缺少密钥时接口返回 `CONFIGURATION_REQUIRED`，不会静默退回 Fake 并宣称成功。

## 费用估算

当前版本化价格表为 `deepseek-usd-2026-08-18`：

| 模型 | 输入 / 百万 Token | 输出 / 百万 Token |
| --- | ---: | ---: |
| `deepseek-chat` | $0.27 | $1.10 |
| `deepseek-reasoner` | $0.55 | $2.19 |

系统在调用前预留估算费用，结束后按 Provider 返回的 Token 用量结算；页面显示的是预估值，最终账单以 DeepSeek 为准。价格变化时必须新增价格表版本并重新审核预算口径。

## 安全边界

- 固定调用 DeepSeek 官方 HTTPS `/chat/completions`。
- 使用 JSON Output，并在 Provider 与编排层执行 JSON Schema 校验。
- 单次请求 30 秒超时，最多尝试两次，响应上限 1 MB。
- 错误不包含响应原文、请求头或密钥。
- 输出只能成为待审草稿；真实发布仍需人工批准和独立渠道授权。
- 真实邮箱目前未接入，Agent 只准备草稿，不会发送邮件。
- Facebook、Instagram、LinkedIn、TikTok、YouTube 的真实发布还需要各平台应用、权限范围与审核分别通过；配置 AI 模型不会自动获得社媒发布权限。

接口依据：[DeepSeek JSON Output 官方文档](https://api-docs.deepseek.com/guides/json_mode/) 与 [Chat Completion 官方接口](https://api-docs.deepseek.com/api/create-chat-completion)。

自动化测试使用隔离的 Fake/fixture transport，不产生真实或付费请求，也不会把测试密钥写入 DOM、浏览器存储或快照。
