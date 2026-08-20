# Mailhub 多域名/多账号说明

Mailhub 是可自托管的邮件工作台，适合把多个 IMAP 来源、域名和业务发件人身份放进一个界面。当前后端扩展支持多个独立 SMTP transport，但必须把“收信聚合”“发件身份”和“实际发信通道”分开判断。

## 后端模型

- 多个 IMAP 来源用于收信同步、搜索、线程和状态管理；这不等于拥有多个可发信的 Outlook 登录会话。
- `smtp_transports` 是独立的远端 SMTP 登录配置；每条记录对应一个实际可用的 SMTP 账号，包含 host、端口、用户名和密码/应用专用密码。
- `senders.smtp_transport_id` 把发件身份绑定到具体 transport。绑定时要求 `senders.email` 与 transport 的 `from_email` 完全一致，后端不会根据域名猜账号。
- 旧的全局 `smtp_config` 和本机 Postfix 仍保持兼容；没有绑定 transport 的托管域发件人继续走原有全局配置。
- 多个 Hotmail/Outlook 账号必须分别配置自己的 SMTP 通道并逐个测试；这不是 Outlook OAuth 会话轮换，也不能绕过服务商的账号策略、限流或配额。

## Excel 路由列

批量联系人 Excel/CSV 使用 `sender_email` 列指定每一行的发件身份。发送前必须：

1. `sender_email` 是合法邮箱地址，且与 Mailhub 中已配置的 sender identity 完全一致。
2. 该 sender identity 已绑定一个启用且测试通过的 `smtp_transport`。
3. 同一批次按 `sender_email` 分组，逐行路由；未知、停用、未测试或空白值直接阻止发送，不自动回退到另一个账号。
4. Excel 只保存邮箱地址，不保存 SMTP 密码、应用专用密码、OAuth token 或 `.env` 内容。

后端配置接口：`GET/POST/PUT/DELETE /api/config/smtp-transports`，单个账号测试使用 `POST /api/config/smtp-transports/{id}/test`；`/api/senders` 的创建请求使用 `smtp_transport_id` 绑定身份。

## 使用前检查

当用户明确要求走 Mailhub 时：

1. 确认 Mailhub 实例地址、用户身份和当前登录状态；不要猜测 API 地址或绕过登录。
2. 读取/查看已配置的 `senders`、`smtp_transports` 和测试状态；不要读取 `.env`、数据库密钥、邮箱密码或 token。
3. 逐个确认计划中的 `sender_email`、sender identity 和 SMTP transport 三者匹配。
4. 如果只有 IMAP 聚合而没有对应发信 transport，停止外发，改为生成计划/草稿并报告缺失项。
5. 发送前仍需执行联系人去重、5 封变量样本、数量/节奏确认和人工批准；Mailhub 不会替代这些闸门。

## 多账号批次

- 切换批次后重新读取当前 sender identity 和送达状态；身份不匹配、认证失败、429、配额、风控或连续失败时立即暂停。
- 发送程序应保留可暂停、可恢复的队列和每个账号的结果记录；不通过更换账号来规避服务商限流或账号策略。

## 安全

- 不把邮箱密码、应用专用密码、OAuth token、`.env` 或 Postgres 导出放入 Skill、台账、普通日志或 GitHub。
- 不通过 Mailhub 的 sender identity 绕过 Outlook、SMTP 服务商或域名的发信策略。
- 若 Mailhub 部署在本地或私有服务器，只通过用户明确提供并已授权的地址访问；未部署或不可访问时，诚实降级到现有 Outlook/Gmail 连接器。
