# DeepSeek 产品内容 Provider

该适配层只用于产品中的内容草稿生成，不是开发代码助手。默认使用 `fake` 离线模式；离线结果会在界面明确标识，且仍需人工审核。

## 启用

仅在服务端环境设置：

```text
PRODUCT_AI_PROVIDER=deepseek
PRODUCT_AI_MODEL=deepseek-chat
DEEPSEEK_API_KEY=<server-only secret>
```

密钥不会写入数据库、API 响应、前端缓存或测试快照。缺少密钥时生成接口返回 `CONFIGURATION_REQUIRED`，不会静默退回 Fake 并宣称成功。

## 安全边界

- 固定调用 DeepSeek 官方 HTTPS `/chat/completions`。
- 使用 JSON Output，并在 Provider 与编排层执行 JSON Schema 校验。
- 单次请求 30 秒超时，最多尝试两次，响应上限 1 MB。
- 错误不包含响应原文、请求头或密钥。
- 输出只能成为待审草稿；真实发布仍需人工批准和独立渠道授权。

接口依据：[DeepSeek JSON Output 官方文档](https://api-docs.deepseek.com/guides/json_mode/) 与 [Chat Completion 官方接口](https://api-docs.deepseek.com/api/create-chat-completion)。

当前本地环境没有配置密钥，因此本切片只执行离线契约测试，没有产生真实或付费请求。
