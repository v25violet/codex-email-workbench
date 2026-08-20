---
name: codex-email-workbench
description: "Use for Gmail/Outlook contact imports, personalized email drafts or controlled outbound batches, inbox and reply triage, reply drafting, and follow-up workflows; applies to outreach campaigns and ordinary single-thread outreach tasks, not unrelated bulk mailing."
---

# Codex 邮箱工作台

这是一个以“先校验、后预览、再批准”为核心的 Gmail/Outlook 外联工作台。它只使用当前 Codex 中已经连接且实际可用的邮箱能力；不保存密码、OAuth token、Cookie 或真实邮箱数据，不绕过连接器，也不部署服务器。

## 入口与模式路由

- 用户首次使用或说“开始设置”时，先读取 [references/onboarding.md](references/onboarding.md)，再按需读取所选提供商的 `gmail-notes.md` 或 `outlook-notes.md`。
- 联系人导入、去重、活动计划和发送前审批，读取 [references/campaign-workflow.md](references/campaign-workflow.md)；安全、授权或重试判断同时读取 [references/safety-and-compliance.md](references/safety-and-compliance.md)。可复制的活动 brief、联系人和 profile 模板在 `assets/` 中。
- 新邮件扫描、回信分类、完整线程和回复草稿，读取 [references/inbox-and-replies.md](references/inbox-and-replies.md)，再读取对应提供商说明。
- 到期 follow-up 候选和停止规则，读取 [references/followup-rules.md](references/followup-rules.md)；不要把候选清单当成已发送结果。
- 用户询问定期任务时，只读取并提供 [references/automation-prompts.md](references/automation-prompts.md) 中的模板；除非用户另行明确要求，不创建自动化。

默认时区为 `Asia/Shanghai`，默认只创建草稿；发送不设 Skill 固定的单批或每日数量上限，由执行时根据连接器、邮箱反馈和用户自定义偏好自适应限速。follow-up 最多 3 次，间隔 2、4、7 个工作日。安装者可在自己的 profile 或台账中修改这些偏好，不能改写 Skill 包内模板。

## 权限与不变量

- 只读搜索、线程读取、分类和报表在用户请求且连接器允许的范围内执行；已读、打开信号只能作辅助信息。
- 本地台账、计划和草稿属于内部写入；创建草稿必须明确报告“已创建草稿，未发送”，不得把草稿描述为已发送。
- 外部发送必须有明确授权；单封发送前确认收件人、主题和最终正文。批量发送必须依次完成台账校验、退信/退订/回信检查、5 封真实变量替换样本预览、发件邮箱/数量/发送节奏确认和人工批准。发送过程中按连接器反馈自适应分批、暂停和降速，不绕过服务商限流或账号策略。
- 执行发送前重新读取最新台账与停止状态，不能依赖对话中旧的联系人状态。回信、拒绝、退订、硬退信、人工暂停和达到次数上限都阻止后续 follow-up；不确定匹配只能进入人工确认。
- 联系人、模板或发件邮箱变化会使旧审批失效。任务中断后重跑必须先重新读取台账，已完成步骤不得重复发送。

## 连接器不可用时的诚实降级

如果 Gmail/Outlook 插件未连接、不可访问、权限不足或账号不匹配，停止邮箱动作，说明需要用户本人完成连接或修正账号；可以继续做本地 CSV 校验、活动计划、样本预览和回复草稿文本，但不能声称搜索、创建草稿或发送已经完成。若连接器只支持草稿，就只建草稿并明确未发送；若定时任务不能调用邮箱连接器，就提供提醒用户打开任务的降级方案。认证、权限、限流或瞬时错误不通过浏览器或其他账号绕过；瞬时错误最多自动重试一次，随后输出失败清单并停止。

显式调用示例：`$codex-email-workbench 开始设置`。
