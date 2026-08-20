# 本地 helper 操作路由

所有邮箱命令都必须显式提供 `--provider` 和 `--account-key`，而且该账号必须已经通过对应 profile 验证。Codex 负责先读取本文件，再按 provider 读取 `outlook-notes.md` 或 `gmail-notes.md`。

## 只读与草稿

- `accounts`：列出本地非敏感账号元数据。
- `verify --provider ... --account-key ...`：重新调用对应 profile，确认没有串号。
- `inbox --provider ... --account-key ...`：读取新邮件摘要，不把未读状态当作外部已读。
- `draft --provider ... --account-key ...`：创建纯文本新邮件草稿。
- `reply-draft --provider ... --account-key ...`：按消息 ID 创建线程回复草稿。
- `check-replies --provider ... --account-key ...`：读取 Inbox、匹配台账并清除相关 follow-up。
- `followups --provider ... --account-key ...`：只生成到期候选，不发送。

## 发送

Codex 先创建草稿并生成计划预览：实际 provider、账号、收件人、主题、正文、数量、cadence 和每封间隔都要展示。用户明确批准后才运行 `approve-plan`，再运行带同一 digest 和 `--confirm` 的 `send-plan`。计划或草稿任意变化都会使批准失效；helper 会按 `interval_seconds` 在成功发送之间等待。

发送成功后写入幂等键；重跑跳过已发送项。`in_flight` 表示中断后结果未知，必须先在对应提供商中人工核对，再用 `resolve-operation`，不得自动重发。
