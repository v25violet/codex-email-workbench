# 联系人、计划与受控发送

## 联系人

使用 `assets/contacts-template.csv`。每行用 `provider` + `account_key` 指定已授权账号，不使用默认发件人。导入前运行 `scripts/validate_contacts.py`，检查必填列、地址、提供商、重复 email、重复唯一键、owner 冲突、状态和停发标记；未知来源名单不得直接外发。

核心唯一键是 `contact_id + campaign_id + step`。重复 email、账号未授权、账号与计划不一致或停发标记都进入人工复核。

## 计划与预览

为每个账号生成独立发送计划 JSON，必须包含 `provider`、`account_key`、`batch_id`、`cadence`、`interval_seconds` 和 `items`。每个 item 必须有 `idempotency_key`、`contact_id`、对应提供商的草稿 ID、收件人、主题和最终纯文本正文。Codex 在批准前展示实际提供商、账号、收件人、主题、正文、数量和发送节奏；批量预览至少展示 5 封实际变量替换样本（不足 5 封则全部展示）。

正文、联系人数据和计划文件只放在用户本机运行目录，不进入 Skill 包或 GitHub。`approve-plan` 只保存预览摘要，不保存正文。

## 发送闸门

默认 `draft_only`。发送必须同时满足：

1. 当前提供商 profile 与计划 `provider` + `account_key` 完全匹配；
2. 当前草稿的收件人、主题和纯文本正文与批准预览一致；
3. 批次无新回信、拒绝、退订、硬退信、人工暂停或其他强停止条件；
4. 发送计划的 digest 与最新批准记录一致；
5. 用户明确提供 `--confirm`，且每个幂等键未成功发送。

任何变化都会使旧批准失效。发送按计划中的 cadence 执行，遇到 429、配额、风控、认证失败或连续错误立即暂停；不自动绕过服务商限制。

## 中断恢复

发送成功后才将幂等键写为 `sent`。已发送项在重跑时跳过；未知结果的 `in_flight` 项必须先由用户核对 Graph 结果，再用 `resolve-operation` 标记，禁止盲目重发。
