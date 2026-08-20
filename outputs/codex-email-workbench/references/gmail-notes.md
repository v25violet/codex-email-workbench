# Gmail API 说明

- Gmail 账号通过 Google Desktop OAuth 逐个授权；多个 Gmail 账号可以共用一个 OAuth client，但每个账号的 cache 必须按 `gmail + account_key` 隔离。
- 授权后调用 `/gmail/v1/users/me/profile` 验证邮箱。不能把浏览器中的 Gmail `/u/0/`、`/u/1/` 当成 helper 账号切换依据。
- `messages.list` 只返回摘要 ID；helper 会按 ID 读取必要的邮件元数据。回信匹配使用发件人、主题、日期、`threadId`、RFC Message-ID 和台账，不把未读当作回信或外部已读。
- 新邮件草稿通过 `users.drafts.create` 创建，回复草稿带原线程 `threadId`、`In-Reply-To` 和 `References`；草稿成功后明确“未发送”。
- 批准发送通过 `users.drafts.send`，发送前重新读取当前草稿并核对收件人、主题、正文和 provider/账号。发送后 Gmail draft 会被移除并生成已发送消息，这是 Gmail API 的正常行为。
- 429、配额、权限、OAuth 过期或账号不匹配立即暂停，不通过 Gmail 浏览器槽位或另一个账号绕过。
