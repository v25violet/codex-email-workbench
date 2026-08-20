# Outlook/Hotmail Graph 说明

- 所有账号通过同一个 Entra public client 分别完成 MSAL delegated OAuth；支持个人 Microsoft 账号，不使用 client secret、ROPC 或密码认证。
- 每个 helper 命令都必须带明确的 `--account-key`。调用 Graph 前先读取该账号的 Keychain cache，再调用 `/me`；返回邮箱与计划账号不一致时停止。
- Graph 的 `/me/messages`、`createReply` 和 `/send` 都绑定当前 token 对应的 `/me`，不能用浏览器槽位、默认账号或消息中的 `from` 字段伪造切换。
- 默认只创建纯文本草稿。创建成功后报告草稿 ID 和“未发送”；只有计划批准摘要匹配且用户显式确认，才允许发送草稿。
- `isRead` 只表示当前邮箱的读取状态，不表示外部收件人打开了邮件；第一版不做外部打开状态判断。
- 429、权限不足、账号不匹配、认证失败或连续失败立即暂停，不通过其他账号或浏览器绕过。
