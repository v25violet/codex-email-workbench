# Follow-up 规则

默认候选时间为上次发送后的第 2、4、7 个工作日，最多 3 次；按本机时区计算。`scripts/outlook_workbench.py followups --provider ... --account-key ...` 只生成候选，不自动发送。

候选必须展示联系人标识、活动、step、上次发送时间、线程提示、计划提供商/账号和停止检查结果。`replied_*`、`bounced`、`unsubscribed`、`paused`、`completed`、明确拒绝、退订、投诉、任何人工回信和达到次数上限都不得进入候选。

生成候选前先检查指定账号的新回信并更新台账。发现回信、退信或人工暂停就移出候选。候选若要发送，仍需重新生成样本、节奏和批量预览，并获得当前人工批准。
