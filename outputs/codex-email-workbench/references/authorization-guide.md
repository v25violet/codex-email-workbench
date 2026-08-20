# OAuth 授权引导

## 不接收秘密

Codex 不索取、代填或保存密码、应用专用密码、client secret、OAuth token、Cookie、恢复码或 MFA 验证码。用户只在对应官方 OAuth 页面输入密码和 MFA。Microsoft client ID 和 Google Desktop OAuth credentials 路径是本地配置，不放进 Skill 包。

MSAL 和 Google OAuth token cache 只能存 macOS Keychain，并按 `provider + account_key` 隔离。Keychain 不可用时直接停止；不允许把缓存写成 JSON、YAML、SQLite、日志、压缩包或 Git 文件。

## 首次配置

1. 检查 `scripts/outlook_workbench.py env`，确认 MSAL、Google OAuth 和 Keychain 可用。
2. Outlook 分支创建支持个人 Microsoft 账号的 Entra public client，并添加 delegated `User.Read`、`Mail.ReadWrite`、`Mail.Send`；不使用 client secret、用户名密码认证或 ROPC。
3. Gmail 分支在 Google Cloud 创建 Desktop OAuth client，启用 Gmail API，保存 credentials JSON 路径；不把 JSON 文件复制进 Skill。
4. 分别用 `set-client-id` 和 `set-google-credentials` 保存本地配置。
5. 逐个运行 `authorize --provider outlook|gmail --account-key <目标邮箱>`。每次只处理一个提供商、一个账号。
6. Outlook 授权后调用 Graph `/me`；Gmail 授权后调用 `/users/me/profile`。只有返回邮箱与目标邮箱完全匹配，才写入对应 Keychain 和本地账号清单。
7. 返回“已完成 N/目标数量”，发现重复或错误账号时暂停。

重新运行时读取本地账号清单，从未完成账号继续；不要重新授权已验证账号。目标数量由用户输入，不写死为 10。

## 文档导入

可以读取文档中的邮箱地址、显示名、非敏感备注和计划映射；发现密码、token、Cookie、secret 或验证码时只报告“发现敏感字段，已跳过”，不复述、不保存、不提交。能读取文档不等于能自动登录。

## 结果报告

只报告：提供商、目标账号、对应 profile 返回的邮箱、显示名、授权状态、Keychain 引用和下一步。不要展示授权响应、token 或完整错误响应。
