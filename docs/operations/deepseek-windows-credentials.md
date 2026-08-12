# DeepSeek Windows credential operations

> 中文摘要：DeepSeek 密钥只保存在当前 Windows 用户的“凭据管理器”中。换用户或换电脑必须重新输入；Git、备份、数据库、浏览器、日志和安装包均不包含密钥。卸载软件不会自动删除密钥，如需删除请先在“高级设置 > AI 模型”中明确执行“删除连接”。

## Security boundary

SinofGear stores a DeepSeek API key in **Windows Credential Manager**, scoped to
the Windows user who entered it. The application database keeps only safe state
such as `CONNECTED`, budgets, limits and test time. It does not keep the key.

The key is not carried by Git, repository exports, `.env`, database dumps,
backup or zip files, browser storage, logs, the installer, or an installation
package. `DEEPSEEK_API_KEY` is unsupported and ignored. Each Windows user and
each new computer must enter the key again through **Advanced Settings > AI
model**.

## Configure and test

1. Sign in as an administrator with permission to manage credentials.
2. Open **Advanced Settings > AI model**.
3. Paste the key into the protected field, set the daily budget and limits, then
   choose **Test and save**.
4. Confirm the page reports **Connected**. Never paste the key into a terminal,
   ticket, email, chat, screenshot, log or browser address.

The settings test is a small paid connection request. A deeper command-line
smoke test is reserved for an administrator who has explicitly approved cost:

```powershell
cd backend
.\.venv\Scripts\python.exe manage.py deepseek_smoke_test `
  --organization-slug YOUR_ORGANIZATION_SLUG `
  --acknowledge-paid-call
```

It makes one minimal Flash request and prints only a generated run ID, model,
thinking status, token counts, estimated cost and pass/fail. It never prints the
key, key target/suffix, prompt, provider response or reasoning. Add
`--include-content-generation` only when a second representative, schema-bound
paid request has also been approved. Automated tests must not run either paid
form.

## Rotate or recover

To rotate a key, create/retrieve the replacement in DeepSeek, return to the AI
model settings, enter it and choose **Test and save**. The replacement becomes
active only after a successful test. Revoke the old key in DeepSeek after the
new connection is confirmed.

After Windows profile migration, reinstallation under another Windows user, or
moving to a new computer, install/sign in normally and enter the key again. A
copied database may still say that a connection existed; absence of the local
credential must be treated as **Reconnect required**, never as permission to
fall back to fake AI.

## Delete, reinstall and uninstall

Use **Delete connection** in the AI model settings before uninstalling when the
credential should be removed. This is an explicit destructive choice: verify
the organization and connection first. Application uninstall does **not**
silently delete the Windows credential, so an accidental uninstall remains
recoverable. Reinstalling as the same Windows user may reuse an intentionally
retained credential only after the application verifies the connection state;
other users/computers must enter it again.

## Backup and restore

Back up the repository and application data as normal, but record only that the
DeepSeek connection must be re-entered after restoration. Do not export Windows
Credential Manager entries or add the key to a backup script. Keep key recovery
inside the DeepSeek account's own controlled administrator process.

## Incident response

If exposure is suspected:

1. Revoke the affected key in DeepSeek immediately.
2. Use **Delete connection** for the affected organization.
3. Review DeepSeek usage and SinofGear AI audit records using run IDs and safe
   usage metadata; do not copy raw secrets into the incident record.
4. Create a replacement key, configure it through the settings page and test it.
5. Investigate the disclosure channel and rotate any unrelated credentials that
   may also have been exposed.

Provider errors shown to users and operators are controlled codes. Do not enable
debug logging of authorization headers, request bodies, provider response bodies
or reasoning content during troubleshooting.
