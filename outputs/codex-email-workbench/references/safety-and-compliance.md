# 安全、授权与停止条件

## 凭据

- 不接受密码、client secret、OAuth token、Cookie、恢复码或 MFA 验证码。
- 只保存非敏感 Microsoft client ID 和 Google credentials 文件路径；每个 provider + 账号的 OAuth cache 只存 macOS Keychain，账号之间隔离。
- 本地 JSON、SQLite、日志、测试和压缩包不得出现 token、密码、授权响应或真实账号数据。
- Keychain 不可用时停止，不降级为明文文件。

## 邮箱与发送

- 每个操作显式指定 provider + 账号，并在对应 profile 接口复核。
- 默认只建草稿；发送前必须展示最终预览并获得明确批准。预览、账号、收件人、主题、正文、批次或节奏变化会立即使旧批准失效。
- 使用幂等键防重跑；中断的未知结果不得自动重发。
- 认证、权限、账号不匹配、429、配额、风控或连续失败立即暂停。

## 停止条件

回信、明确拒绝、退订、投诉、硬退信、人工暂停和 follow-up 达到上限都停止后续发送；自动回复和不确定匹配进入人工确认。`isRead` 与打开信号不改变营销状态。

## 分发边界

分发包只含 Skill 文档、标准库脚本、依赖声明、模板和 mock 测试。个人 client ID、账号、联系人、计划、台账和 Keychain 缓存都留在安装者本机。
