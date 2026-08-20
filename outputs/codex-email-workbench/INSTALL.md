# Codex 多邮箱工作台安装说明

## 作用与边界

这是一个本地 Python helper，不启动后台、不部署远程服务、不使用密码认证或 Codex 原生连接器切换账号。它通过 MSAL + Microsoft Graph 管理多个 Outlook/Hotmail 账号，通过 Google OAuth + Gmail API 管理多个 Gmail 账号。

默认只创建草稿。发送必须经过当前预览、人工批准、对应提供商账号复核和幂等台账检查。不会连接真实邮箱或发送测试邮件，直到用户明确运行真实操作。

## 安装

1. 下载并解压 `codex-email-workbench.zip`。
2. 将其中的 `codex-email-workbench/` 放进个人 Codex Skills 目录，通常为 `~/.codex/skills/`。
3. macOS 终端安装唯一运行依赖：

   ```bash
   python3 -m pip install --user -r ~/.codex/skills/codex-email-workbench/scripts/requirements.txt
   ```

4. 确认 macOS Keychain 命令可用：

   ```bash
   python3 ~/.codex/skills/codex-email-workbench/scripts/outlook_workbench.py env
   ```

   只有 `msal`、`google_oauth` 和 `keychain` 都显示 `available` 才继续。Keychain 不可用时不会降级到明文文件。

## 创建一个可支持个人 Microsoft 账号的 Entra 应用

在 [Microsoft Entra admin center](https://entra.microsoft.com/) 中由你本人完成：

1. App registrations → New registration。
2. Supported account types 选择同时支持组织账号和个人 Microsoft 账号的选项。
3. 创建后只记录 **Application (client) ID**；不要创建或提交 client secret。
4. Authentication 中启用 Public client / mobile and desktop flows。
5. API permissions → Microsoft Graph → Delegated permissions，添加 `User.Read`、`Mail.ReadWrite`、`Mail.Send`。

将 client ID 保存到本机配置；它不是密码：

```bash
python3 ~/.codex/skills/codex-email-workbench/scripts/outlook_workbench.py \
  set-client-id <你的-Application-client-ID>
```

## 创建 Gmail OAuth 应用

在 [Google Cloud Console](https://console.cloud.google.com/) 中启用 Gmail API，配置 OAuth consent screen，并创建 **Desktop app** OAuth client。下载 credentials JSON 到本机安全位置，不要复制进 Skill 目录或提交 GitHub：

```bash
python3 ~/.codex/skills/codex-email-workbench/scripts/outlook_workbench.py \
  set-google-credentials /你的安全路径/client_secret.json
```

helper 使用 Gmail delegated scope `https://www.googleapis.com/auth/gmail.modify`，同一个 Desktop OAuth client 可以逐个授权多个 Gmail 账号。

## 首次设置

在 Codex 中输入：

```text
$codex-email-workbench 开始设置 Gmail 和 Outlook 各10个账号
```

Codex 会逐个调用 `authorize --provider outlook|gmail --account-key <邮箱>`。每次在对应官方页面登录目标账号并完成 MFA；helper 随后调用对应 profile 验证邮箱。重复账号、错误账号或授权失败会暂停，重新运行会从本地台账继续，不重复已完成账号。

本地状态默认位于 `~/.codex-email-workbench/`：配置和账号元数据不含 token，SQLite 只保存 provider、邮箱、账号标识、状态、进度和 Keychain 引用，MSAL/Google OAuth 缓存只在 macOS Keychain。每位使用者都必须使用自己的 OAuth 应用配置和本机安全存储。

## 使用方式

所有邮箱命令都必须带 `--provider` 和 `--account-key`：

```bash
python3 .../outlook_workbench.py accounts
python3 .../outlook_workbench.py verify --provider gmail --account-key user@example.com
python3 .../outlook_workbench.py inbox --provider outlook --account-key user@example.com
python3 .../outlook_workbench.py draft --provider gmail --account-key user@example.com --to recipient@example.com --subject '主题' --body-file body.txt
python3 .../outlook_workbench.py reply-draft --provider outlook --account-key user@example.com --message-id <id> --body-file reply.txt
python3 .../outlook_workbench.py check-replies --provider gmail --account-key user@example.com
python3 .../outlook_workbench.py followups --provider outlook --account-key user@example.com
```

批量发送使用本地计划 JSON：先由 Codex 展示最终预览，再运行 `approve-plan` 保存摘要，最后仅在用户明确批准后带 `--approval-digest ... --confirm` 运行 `send-plan`。草稿内容、计划和联系人数据不要放入 Skill 包或 GitHub。

## 账号移除与撤销

```bash
python3 .../outlook_workbench.py remove --provider gmail --account-key user@example.com
```

这会移除该账号的本地 Keychain 缓存和本地元数据；如需全面撤销应用权限，还要在 Microsoft 账户的应用授权页面单独撤销。
