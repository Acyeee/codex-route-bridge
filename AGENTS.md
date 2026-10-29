# 给 AI 助手的安装与使用说明

这份文件写给帮用户安装本项目的 AI 助手（Codex、Claude 等）。请按顺序执行，每一步完成后再进行下一步。

## 硬性约束

- **不要让用户在聊天里发送 API 密钥。** 密钥只能由用户在 `codex-route.cmd` 菜单里自己输入（输入时不显示），或由用户自己在本机终端里执行命令。
- **切换线路会关闭并重启用户正在用的 Codex。** 执行 `launch` 或在菜单里切换之前，先告诉用户并得到确认；提醒用户先保存正在进行的工作。
- **不要修改 Codex 的安装目录**（`C:\Program Files\WindowsApps\OpenAI.Codex_*`），也不要修改用户的 `%USERPROFILE%\.codex\config.toml`。本项目不需要改这两处。
- 不要删除 `%USERPROFILE%\.codex\` 下除 `route-switch\` 以外的任何内容。

## 1. 检查环境

```powershell
Get-AppxPackage -Name OpenAI.Codex | Select-Object Version   # 必须有输出：需要 Microsoft Store 版 Codex
python --version                                             # 需要 3.10 及以上
node --version                                               # 需要 Node.js（生成兼容副本时做语法校验）
```

缺少 Python 或 Node.js 时，征得用户同意后安装，例如：

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id OpenJS.NodeJS.LTS
```

安装后需要重新打开终端，让 PATH 生效。

## 2. 获取代码并编译

```powershell
git clone https://github.com/Acyeee/codex-quota-boost.git
cd codex-quota-boost
.\src\build.ps1                                      # 用 Windows 自带的 .NET Framework 编译桥接程序
.\src\engine\codex-route-bridge.exe --self-test      # 应输出 Route contract checks passed
python -I src\tests\test_desktop_helper.py           # 应全部通过
```

没有 git 时，可以从仓库页面下载 ZIP 解压。

## 3. 添加第三方 API

让用户双击 `codex-route.cmd`，按 `a`，依次输入名称、API 地址（通常以 `/v1` 结尾）和密钥。菜单会自动拉取模型并保存。拉取模型需要密钥，所以这一步始终由用户自己在菜单里完成。

## 4. 切换线路

征得用户同意后，让用户在菜单里输入线路编号；或者执行：

```powershell
'{"operation":"list"}' | python -I src\engine\desktop-helper.py
'{"operation":"launch","args":{"id":"<线路 id>","restart":true,"allowForce":true}}' | python -I src\engine\desktop-helper.py
```

第一次切换到第三方 API 时，会在 `%USERPROFILE%\.codex\route-switch\compat\` 生成 Codex 兼容副本，约需十几秒、占约 2.3GB。切回官方 Plus：选 `official` 线路即可。

## 5. 验证

- 切换后，Codex 的模型选择器里应出现该第三方 API 的全部模型。
- `list` 返回结果中的 `confirmedProfile` 等于所选线路 id，表示已经生效（发起第一个任务后才会出现）。

## 常见问题

| 现象 | 处理 |
|---|---|
| `Official Codex installation missing.` | 用户的 Codex 不是 Microsoft Store 版，本项目暂不支持 |
| `Required desktop component missing.` | 先运行 `.\src\build.ps1` 编译桥接程序 |
| `上游返回 HTTP 401` | 密钥错误或已失效，让用户在菜单里重新添加 |
| `上游返回 HTTP 404` | API 地址通常需要以 `/v1` 结尾 |
| 一直提示旧实例未退出 | 让用户在托盘里完全退出 Codex 后重试 |

更多细节见 [docs/技术说明.md](docs/技术说明.md)。
