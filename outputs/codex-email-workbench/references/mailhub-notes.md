# Mailhub 多域名/多账号说明

Mailhub 是可自托管的邮件工作台，适合把多个 IMAP 来源、域名和业务发件人身份放进一个界面。它可以作为本 Skill 的可选后端，但必须把“收信聚合”和“发信路由”分开判断。

## 能力边界

- 多个 IMAP 来源用于收信同步、搜索、线程和状态管理；这不等于拥有多个可发信的 Outlook 登录会话。
- `senders` 是发件人身份记录，通常绑定 Mailhub 已托管并完成域名配置的地址；它不是任意外部邮箱的登录凭据。
- 当前 Mailhub 版本使用单一全局 SMTP/Postfix delivery transport。仅增加多个 sender identity，不会自动创建多个独立 SMTP 账号或多个 Outlook OAuth 会话。
- 因此，三个 Outlook/Hotmail 账号不能仅凭把地址录入 Mailhub 就实现轮换发信。每个账号必须有明确可用的发信通道、委派权限或经服务商允许的 relay 配置。

## 使用前检查

当用户明确要求走 Mailhub 时：

1. 确认 Mailhub 实例地址、用户身份和当前登录状态；不要猜测 API 地址或绕过登录。
2. 读取/查看已配置的 domains、senders 和 SMTP/transport 诊断状态；不要读取 `.env`、数据库密钥、邮箱密码或 token。
3. 逐个确认计划中的发件地址与 Mailhub sender identity 完全匹配，并确认其 delivery transport 已通过测试。
4. 如果只有 IMAP 聚合而没有对应发信 transport，停止外发，改为生成计划/草稿并报告缺失项。
5. 发送前仍需执行联系人去重、5 封变量样本、数量/节奏确认和人工批准；Mailhub 不会替代这些闸门。

## 多账号批次

- 如果每个账号实际上使用不同 SMTP/OAuth 通道，只有在 Mailhub 明确提供并验证了每个通道的 sender identity/transport 选择时，才可以按批次切换。
- 如果 Mailhub 只有一个全局 SMTP 配置，不能声称发送来自三个不同 Outlook 账号；应使用同一已验证发件身份，或暂停并要求管理员配置独立通道。
- 切换批次后重新读取当前 sender identity 和送达状态；身份不匹配、认证失败、429、配额、风控或连续失败时立即暂停。

## 安全

- 不把邮箱密码、应用专用密码、OAuth token、`.env` 或 Postgres 导出放入 Skill、台账、普通日志或 GitHub。
- 不通过 Mailhub 的 sender identity 绕过 Outlook、SMTP 服务商或域名的发信策略。
- 若 Mailhub 部署在本地或私有服务器，只通过用户明确提供并已授权的地址访问；未部署或不可访问时，诚实降级到现有 Outlook/Gmail 连接器。
