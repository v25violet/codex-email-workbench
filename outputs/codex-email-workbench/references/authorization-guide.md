# 授权引导

## 核心原则

Skill 可以引导用户完成授权、检查当前账号和读取非敏感配置，但不能接收、保存或代填邮箱密码、应用专用密码、OAuth token、Cookie、恢复码或 MFA 验证码。用户必须在官方授权页、连接器弹窗、Mailhub 设置页或本地 API 客户端中自己输入密钥。

用户提供的文档可以作为配置参考。允许读取：邮箱地址、显示名、SMTP/IMAP host、端口、TLS 类型、发件映射和非敏感备注；遇到密码、token、Cookie、密钥或验证码时跳过，不写入日志、台账、Skill 或 GitHub，并提醒用户撤回/轮换已暴露的密钥。

## Outlook 连接器授权

1. 检查当前会话是否实际提供 Outlook Email 能力；推荐先调用 `get_profile`，不要把浏览器已登录状态当成连接器已授权。
2. 未连接时，提示用户通过 Codex 的 Outlook 连接器/插件管理入口完成官方 OAuth 授权、同意权限并自行完成 MFA。不要让用户把密码粘贴到聊天里。
3. 授权完成后重新调用 `get_profile`，记录连接器返回的当前邮箱、账号类型和可用权限；没有返回 profile 就不能声称授权成功。
4. 每个批次开始前重新读取 profile。若当前邮箱与计划中的 `sender_email` 不一致，暂停，不猜测 `from`，也不通过浏览器槽位或其他账号绕过。
5. 如果连接器只支持一个当前账号，Skill 不声称可以在三个 Outlook 账号之间自动切换；改为引导用户逐个授权（仅当连接器明确支持多连接）或使用 Mailhub 的多个 SMTP transport。

## Mailhub 多账号配置

1. 用户在自己可控的 Mailhub 管理页或 API 客户端打开 `/docs`，使用管理员会话配置 `/api/config/smtp-transports`；密码只在该安全输入框或本地客户端中提交。
2. 每个 transport 单独调用 `/api/config/smtp-transports/{id}/test`，只有测试状态为 `ok` 才能用于发送。
3. 通过 `/api/senders` 创建或更新 sender identity，并让 `sender.email` 与 transport 的 `from_email` 完全一致。
4. Skill 只读取 transport 的邮箱、启用状态、测试状态和掩码字段；不读取数据库、`.env` 或密码原文。
5. Excel 每行的 `sender_email` 必须精确匹配一个已测试 sender identity；未知、停用、未测试或空白值直接阻止发送。

## 文档导入

当用户提供 Excel、CSV、Markdown、TXT 或 PDF 配置文档时：

- 先报告发现的非敏感账号、发件映射和连接参数；不自动登录、不自动提交密码。
- 发现疑似密码、token、Cookie 或验证码时只报告“发现敏感字段，已跳过”，不要在回复中复述原文。
- 账号归属、发件身份、共享邮箱所有者或权限范围不明确时停止并请求用户在官方页面确认。
- 文档中的联系人名单仍需经过校验、去重、退订/拒绝检查和发送闸门；文档本身不等于外发授权。

## 授权结果格式

完成后用以下字段报告，不展示任何秘密：

```text
授权方式：Outlook 连接器 / Mailhub SMTP transport
当前账号：<连接器返回的邮箱或已配置的发件邮箱>
权限状态：已授权 / 未授权 / 需要重新授权
发件通道：已测试 / 未测试 / 测试失败
可用发件身份：<邮箱列表>
```
