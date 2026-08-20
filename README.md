# codex-email-workbench

一个完全由 Codex 引导的本地多邮箱工作台：同时支持 Outlook/Hotmail 和 Gmail。使用安装者自己的 Microsoft Entra 公共客户端或 Google Desktop OAuth 客户端，逐个授权多个账号，并通过本地 Keychain、SQLite 台账和人工发送闸门管理草稿、回信与 follow-up。

本项目只包含本地 helper、Skill 文档和 mock 测试，不包含远程后端、容器、密码认证或真实账号数据。每次操作都必须显式指定 `provider` 和 `account_key`，不能依赖浏览器当前账号或缓存中的第一个账号。安装和首次设置请阅读 [outputs/codex-email-workbench/INSTALL.md](outputs/codex-email-workbench/INSTALL.md)。
