# Codex 额度扩容

**Plus 额度不够用？保留原账号和聊天记录，无感接上第三方 API 继续用。**

Codex 的 Plus 额度经常不够用。cc-switch、Codex++ 这类工具切到第三方 API 时，会把 Codex 改成 API Key 登录，官方账号的聊天记录就看不到了，Chat、Work 也用不了。

本项目只切换 Codex 任务的**额度来源**，其他一切照旧：

- **官方登录不变**：Chat、Work 和聊天记录照常使用；
- **额度自由切换**：在官方 Plus 和任意第三方 API（兼容 OpenAI 接口的服务，或你自建的聚合服务）之间随时切换；
- **额度用完也能用**：Plus 额度用完后，继续用第三方 API。

## 适用场景

- **订阅额度不够用**：用的是 ChatGPT 订阅账号（特别是 Plus），Codex 额度经常不够，需要补充其他额度；
- **想保留对话记录**：试过其他切换工具，但不想因为换成 API Key 登录而看不到原账号的聊天记录；
- **想按任务选额度**：重要任务用官方额度，日常或大批量任务交给第三方 API，随时切换。

适用于 Windows 版 Codex 桌面应用。

## 文件

| 文件 | 用途 |
|---|---|
| `codex-route.cmd` | 双击打开线路菜单：添加第三方 API、切换线路、删除线路 |
| `src/` | 程序代码：线路引擎、兼容副本生成、桥接程序和测试 |
| `docs/技术说明.md` | 工作原理、命令行接口、本地文件、安全设计与已知限制 |

## 使用方法

- **准备**：安装 [Python 3](https://www.python.org/downloads/)（勾选 “Add python.exe to PATH”）和 [Node.js](https://nodejs.org/)，点右上角 **Code → Download ZIP** 下载本仓库并解压。
- **使用**：双击 `codex-route.cmd`，按 `a` 添加第三方 API，输入编号即可切换；该 API 的全部模型会出现在 Codex 的模型选择器里。
- **恢复**：在菜单里选“官方 Plus”；卸载时删除 `%USERPROFILE%\.codex\route-switch\` 和本项目文件夹。

第一次切换到第三方 API 时，会生成一份 Codex 本机兼容副本（约十几秒、占用约 2.3GB），官方安装目录不会被修改。密钥只加密保存在本机，本项目不收集任何数据，也不提供任何 API 服务或额度。

## 使用须知

本项目仅供个人在自己的电脑上使用，请使用本人的 ChatGPT 账号和有权使用的第三方 API，并遵守 OpenAI 及所用服务商的条款。以 MIT 许可证免费开源，按现状提供，不作任何担保；Codex 更新后可能需要等待适配。本项目与 OpenAI 无关，Codex、ChatGPT 是 OpenAI 的商标。
