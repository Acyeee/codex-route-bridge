# Codex 额度扩容

**Plus 额度不够用？保留原账号和聊天记录，无感接上第三方 API 继续用。**

Codex 的 Plus 额度经常不够用。直接改成 API Key 登录的话，官方账号的聊天记录就看不到了，Chat、Work 也用不了。

本项目只切换 Codex 任务的**额度来源**，其他一切照旧：

- **官方登录不变**：Chat、Work 和聊天记录照常使用；
- **额度自由切换**：在官方 Plus 和任意第三方 API（兼容 OpenAI 接口的服务，或你自建的聚合服务）之间随时切换；
- **额度用完也能用**：Plus 额度用完后，继续用第三方 API。

## 适合谁

- **适合**：只有一个 Plus 账号、额度经常不够用，想补充第三方 API，又不想丢掉原账号聊天记录的人；
- **适合**：不想折腾配置文件，希望点几下就能切换的新手；
- **不太需要**：已经在用 cc-switch、Codex++ 或多账号自动切换，并且用得顺手的人，继续用原来的方案就好。

适用于 Windows 版 Codex 桌面应用。

## 下载使用（推荐）

1. 到 [Releases](https://github.com/Acyeee/codex-route-bridge/releases/latest) 下载 `XiaoluluCodexHelper-…-windows-x64.zip`，解压整个文件夹；
2. 安装 [Python 3](https://www.python.org/downloads/)（勾选 “Add python.exe to PATH”）。不会装可以让你的 AI 助手帮忙；
3. 双击「小噜噜Codex助手.exe」→ 左侧「线路管理」→ 添加第三方 API → 启动 Codex。之后在 Codex 自带的模型选择器里切换模型即可。

想回到官方 Plus，选回「官方订阅」再重启 Codex 就行。

第一次切换到第三方 API 时，会生成一份 Codex 本机兼容副本（约十几秒、占用约 2.3GB），官方安装目录不会被修改。密钥只加密保存在本机，本项目不收集任何数据。

## 命令行版

不想装图形界面的话，点右上角 **Code → Download ZIP** 下载本仓库，双击 `codex-route.cmd`：按 `a` 添加第三方 API，输入编号即可切换。卸载时删除 `%USERPROFILE%\.codex
oute-switch\` 和本项目文件夹。

| 文件 | 用途 |
|---|---|
| `codex-route.cmd` | 命令行线路菜单：添加第三方 API、切换线路、删除线路 |
| `src/` | 程序代码：线路引擎、兼容副本生成、桥接程序和测试 |
| `src/docs/技术说明.md` | 工作原理、命令行接口、本地文件、安全设计与已知限制 |

## 使用须知

本项目仅供个人在自己的电脑上使用，请使用本人的 ChatGPT 账号和有权使用的第三方 API，并遵守 OpenAI 及所用服务商的条款。以 MIT 许可证免费开源，按现状提供，不作任何担保；Codex 更新后可能需要等待适配。本项目与 OpenAI 无关，Codex、ChatGPT 是 OpenAI 的商标。

---

<sub>作者另外提供 [小噜噜 API](https://xiaolulu.cc) 和 AI 订阅代充服务，也欢迎 API 服务商合作推荐。有需要可加微信：xiaolulu28256</sub>
