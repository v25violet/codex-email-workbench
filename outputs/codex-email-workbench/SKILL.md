---
name: codex-email-workbench
description: "Use for Codex-guided local Outlook/Hotmail and Gmail work with multiple user-authorized accounts: OAuth setup, mailbox reads, drafts, approved sends, reply checks, and follow-up candidates."
---

# Codex 多邮箱工作台

本 Skill 支持 Outlook/Hotmail 和 Gmail。运行时由 Codex 引导本地 `scripts/outlook_workbench.py`：Outlook 使用 MSAL + Microsoft Graph，Gmail 使用 Google OAuth + Gmail API。两个提供商都支持多个独立账号；不使用外置后端、容器或密码登录。

## 入口

- “开始设置”或 `$codex-email-workbench 开始设置 Gmail 和 Outlook 各10个账号`：读取 [references/onboarding.md](references/onboarding.md) 和 [references/oauth-setup.md](references/oauth-setup.md)，一次只推进一个提供商、一个账号授权阶段。
- 需要读取邮件、建草稿、检查回信或生成回复：读取 [references/operations.md](references/operations.md)，再按 `provider` 读取 [references/outlook-notes.md](references/outlook-notes.md) 或 [references/gmail-notes.md](references/gmail-notes.md)。
- 导入联系人、生成样本或准备发送计划：读取 [references/campaign-workflow.md](references/campaign-workflow.md)，并运行 `scripts/validate_contacts.py` 与 `scripts/validate_campaign_state.py`。
- 回信分类读取 [references/inbox-and-replies.md](references/inbox-and-replies.md)；follow-up 候选和停止规则只读取 [references/followup-rules.md](references/followup-rules.md)。
- 安全判断读取 [references/safety-and-compliance.md](references/safety-and-compliance.md)。

## 必须保持的不变量

- 每个邮箱操作都必须显式指定已验证的 `provider` 和 `account_key`；禁止使用缓存中的第一个账号、浏览器当前账号或隐式 `from` 猜测发件人。
- 每个账号必须由用户本人在对应官方 OAuth 页面登录并完成 MFA。Codex 不索取、代填或保存密码、MFA、恢复码、Cookie 或 token；两个提供商的 OAuth 缓存都只能在 macOS Keychain，Keychain 不可用时停止。
- Outlook 授权完成后必须调用 Graph `/me`，Gmail 授权完成后必须调用 Gmail `/users/me/profile`；只有返回邮箱与 `account_key` 完全匹配才登记为已授权账号。
- 默认只创建草稿。发送前必须展示实际账号、收件人、主题、最终正文、批量数量和发送节奏；只有当前预览被明确批准，且批准摘要仍匹配，才可发送。
- 发送计划使用幂等键和本地台账防止重跑重复发送。中断、账号不匹配、认证失败、限流、退信、退订、拒绝、人工暂停或任何已匹配回信都停止相关后续动作。
- `isRead` 和其他打开信号不代表外部收件人已读；第一版不做外部打开状态判断。

## 运行边界

Skill 包只包含脚本、模板、文档和 mock 测试。个人 `client_id`、账号清单、Keychain 引用、SQLite 台账和运行计划都放在安装者本机，不提交到 GitHub。没有真实授权或用户批准时，只能做本地校验、计划和草稿文本工作。

显式调用示例：`$codex-email-workbench 开始设置 Gmail 和 Outlook 各10个账号`。
