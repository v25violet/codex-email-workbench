# Outlook 与 Gmail OAuth 配置

## Outlook/Hotmail

在 [Microsoft Entra admin center](https://entra.microsoft.com/) 中创建一个应用，Supported account types 选择支持个人 Microsoft 账号的选项。启用 Public client / mobile and desktop flows，不创建 client secret。

添加 Microsoft Graph delegated permissions：`User.Read`、`Mail.ReadWrite`、`Mail.Send`。用户本人在每个官方 OAuth 页面分别登录；helper 使用 `common` authority，不使用用户名密码认证或 ROPC。

本机命令：

```bash
python3 scripts/outlook_workbench.py set-client-id <client-id>
python3 scripts/outlook_workbench.py authorize --provider outlook --account-key user@example.com
python3 scripts/outlook_workbench.py verify --provider outlook --account-key user@example.com
```

授权后必须调用 `/me`。若返回邮箱不是目标账号，立即停止且不保存缓存。MSAL cache 只写 Keychain，账号按 provider + 邮箱隔离；重新运行只补未授权账号。

## Gmail

在 [Google Cloud Console](https://console.cloud.google.com/) 创建项目并启用 Gmail API，配置 OAuth consent screen，然后创建 **Desktop app** OAuth client。下载 credentials JSON 到 Skill 目录之外，并执行：

```bash
python3 scripts/outlook_workbench.py set-google-credentials /secure/path/client_secret.json
python3 scripts/outlook_workbench.py authorize --provider gmail --account-key user@gmail.com
python3 scripts/outlook_workbench.py verify --provider gmail --account-key user@gmail.com
```

Gmail 使用 delegated `https://www.googleapis.com/auth/gmail.modify`。同一个 Desktop OAuth client 可以逐个授权多个 Gmail 账号；每个账号的 Google OAuth cache 使用独立 Keychain 项。授权后必须调用 Gmail API `/users/me/profile`，返回邮箱不匹配时不保存 cache。
