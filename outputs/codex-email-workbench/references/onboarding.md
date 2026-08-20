# 首次设置流程

触发例：`$codex-email-workbench 开始设置 Gmail 和 Outlook 各10个账号`。

每次只推进一个阶段，并在阶段末报告已确认内容和下一步；不要要求用户一次性提交全部密码或验证码。

## 阶段 1：环境

运行 `scripts/outlook_workbench.py env`。若 Python、MSAL、Google OAuth 或 macOS Keychain 不可用，停止并给出安装/修复提示，不执行邮箱动作。

## 阶段 2：配置 OAuth 应用

读取 [oauth-setup.md](oauth-setup.md)，按用户选择的提供商配置 Microsoft Entra public client 或 Google Desktop OAuth client；只保存本地配置，不收集邮箱密码、MFA 或 token。

## 阶段 3：逐个授权

从用户给出的每个提供商目标数量和账号清单建立待办：

1. 选择一个尚未完成的 `provider` + `account_key`。
2. 启动对应官方 OAuth 授权，用户本人登录并完成 MFA。
3. 调用对应 profile 接口验证真实邮箱：Outlook 为 Graph `/me`，Gmail 为 `/users/me/profile`。
4. 只有完全匹配才保存 Keychain 缓存和本地元数据。
5. 输出“已完成 N/目标数量”，再询问是否继续下一个账号。

重复账号、错误账号、权限不足或授权失败立即暂停。重新运行从台账继续，不重复已完成账号；目标数量可为任意正整数。

## 阶段 4：本地能力验证

授权完成后只做每个账号的 `/me` 验证和本地台账检查。不要自动读取收件箱、创建草稿或发送测试邮件，除非用户另行请求。

## 设置结束

输出不含秘密的账号清单：`provider`、`account_key`、profile 邮箱、显示名、授权状态、Keychain 引用。说明后续可用命令：读取新邮件、创建草稿、创建回复草稿、检查回信、生成 follow-up 候选和批准后发送。
