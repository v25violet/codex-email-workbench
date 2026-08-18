# Codex 邮箱工作台安装说明

## 作用与边界

这个 Skill 帮你在自己的 Codex 中连接 Gmail 或 Outlook，校验联系人、生成个性化邮件、创建草稿、在批准后执行小批次发送、扫描回信、生成回复草稿和管理 follow-up 候选。默认只创建草稿；它不保存邮箱密码或 OAuth token，不抓取联系人，不提供无限量群发，不部署 SMTP/IMAP/追踪服务器，也不把“已读”当作可靠转化指标。

## 安装

### 从 zip 安装

1. 下载 `codex-email-workbench.zip` 并解压。
2. 将解压后的 `codex-email-workbench/` 文件夹放入个人 Codex Skills 目录：通常是 `$CODEX_HOME/skills/`；未设置 `CODEX_HOME` 时通常是 `~/.codex/skills/`。
3. 保持 `SKILL.md` 位于该文件夹的第一层，不要只复制文件夹里的内容。

### 从 GitHub 安装

下载或克隆包含 `codex-email-workbench/` 文件夹的仓库，将该文件夹复制到同一个个人 Skills 目录。不要把用户自己的 profile、联系人 CSV 或运行日志提交回仓库。

安装后刷新或重启 Codex，使 Skill 列表重新加载。校验文件只用于核对下载完整性，不是邮箱授权凭据。

## 第一次使用

先在 Codex 输入：

`$codex-email-workbench 开始设置`

按引导选择 Gmail 或 Outlook，并由你本人完成插件授权。Skill 不会索要密码。若使用共享/委派 Outlook 邮箱，确认目标邮箱所有者标识与实际发件邮箱一致。

## 常见问题

- **插件未连接：** 通过 Codex 的插件管理能力连接 Gmail 或 Outlook；连接完成前只能做本地校验和草稿文本规划。
- **邮箱不匹配：** 浏览器 URL 中的 `/u/0/` 或 `/u/1/` 不是插件账号选择依据。停止操作，重新选择实际可访问的邮箱。
- **只能建草稿：** 这是安全降级；草稿明确表示“未发送”，需你审核后自行发送或在明确批准后再执行。
- **自动化不可用：** 使用 `references/automation-prompts.md` 的模板创建提醒；定时任务不能静默绕过连接器权限。
- **权限不足：** 不通过浏览器、其他账号或重复重试绕过权限；检查连接账号及共享/委派权限后再运行。

## 升级与卸载

升级时只替换 Skill 包文件，不要覆盖个人工作目录中的 profile、联系人台账或活动数据。卸载 Skill 不等于撤销 Gmail/Outlook 授权；如需撤销授权，必须在 Codex 插件管理或对应邮箱账户设置中单独断开连接。
