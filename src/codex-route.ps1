# Interactive menu: list routes, add a third-party API, switch and restart Codex.
param()
$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding($false)
$OutputEncoding = $utf8; [Console]::InputEncoding = $utf8; [Console]::OutputEncoding = $utf8
$root = $PSScriptRoot
$helper = Join-Path $root 'engine\desktop-helper.py'
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }

function Invoke-Route([string]$Operation, [hashtable]$Arguments = @{}) {
    $request = @{ operation = $Operation; args = $Arguments } | ConvertTo-Json -Compress -Depth 6
    $reply = ($request | & $python -I $helper | Out-String) | ConvertFrom-Json
    if ($reply.error) { throw $reply.error }
    $reply.result
}

function Read-Secret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function Show-Routes($State) {
    Write-Host ''
    Write-Host '==== Codex 额度线路 ====' -ForegroundColor Cyan
    $index = 0
    foreach ($route in @($State.providers)) {
        $index++
        $mark = if ($route.id -eq $State.activeProfile) { '*' } else { ' ' }
        $detail = if ($route.kind -eq 'official') { '使用官方 Plus 额度' } else { "$($route.baseUrl) · 默认 $($route.model) · 共 $(@($route.models).Count) 个模型" }
        $running = if ($route.id -eq $State.confirmedProfile) { '  [运行中]' } else { '' }
        Write-Host (' {0} {1}. {2}  {3}{4}' -f $mark, $index, $route.name, $detail, $running)
    }
    Write-Host ''
    Write-Host '  输入数字：切换到该线路并重启 Codex（* 为当前选中）'
    Write-Host '  a：添加第三方 API    d：删除线路    q：退出'
}

function Add-Route {
    $name = (Read-Host '名称（例如：我的第三方 API）').Trim()
    $baseUrl = (Read-Host 'API 地址（通常以 /v1 结尾）').Trim()
    $key = (Read-Secret 'API Key（输入时不显示）').Trim()
    Write-Host '正在拉取模型…'
    $catalog = Invoke-Route 'models' @{ baseUrl = $baseUrl; key = $key }
    if (-not $catalog.ok) { throw $catalog.detail }
    $models = @($catalog.models)
    Write-Host $catalog.detail
    for ($i = 0; $i -lt $models.Count; $i++) { Write-Host ('  {0}. {1}' -f ($i + 1), $models[$i]) }
    $pick = Read-Host '默认模型编号（直接回车选 1；全部模型都能在 Codex 里切换）'
    $default = if ($pick -match '^\d+$' -and [int]$pick -ge 1 -and [int]$pick -le $models.Count) { $models[[int]$pick - 1] } else { $models[0] }
    $id = 'api-' + (Get-Date -Format 'yyyyMMddHHmmss')
    $null = Invoke-Route 'save' @{ id = $id; name = $name; baseUrl = $baseUrl; model = $default; models = $models; key = $key }
    Write-Host "已保存「$name」，密钥已由 Windows 加密保存。" -ForegroundColor Green
}

function Switch-Route($Route) {
    $null = Invoke-Route 'select' @{ id = $Route.id }
    Write-Host "正在切换到「$($Route.name)」并重启 Codex…（第一次使用第三方 API 时需要准备兼容副本，约十几秒）"
    $state = Invoke-Route 'launch' @{ id = $Route.id; restart = $true; allowForce = $true }
    Write-Host '已启动 Codex。' -ForegroundColor Green
    if ($state.launchedUnpatched) { Write-Host '提示：当前 Codex 版本还没有适配的兼容副本，Plus 额度用完后可能暂时发不出消息。' -ForegroundColor Yellow }
}

function Remove-Route($State) {
    $routes = @($State.providers)
    $pick = Read-Host '要删除的线路编号'
    if ($pick -notmatch '^\d+$' -or [int]$pick -lt 1 -or [int]$pick -gt $routes.Count) { return }
    $route = $routes[[int]$pick - 1]
    if ($route.kind -eq 'official') { Write-Host '官方线路不能删除。'; return }
    if ((Read-Host "确定删除「$($route.name)」？(y/n)") -eq 'y') { $null = Invoke-Route 'remove' @{ id = $route.id }; Write-Host '已删除。' }
}

# Dot-sourcing (for tests) loads the functions without starting the menu.
if ($MyInvocation.InvocationName -eq '.') { return }
if (-not $python) { Write-Host '需要先安装 Python 3：https://www.python.org/downloads/' -ForegroundColor Red; exit 1 }
if (-not (Test-Path -LiteralPath (Join-Path $root 'engine\codex-route-bridge.exe'))) {
    Write-Host '首次运行，正在编译桥接程序…'
    & (Join-Path $root 'build.ps1') | Out-Null
}
while ($true) {
    try {
        $state = Invoke-Route 'list'
        Show-Routes $state
        $choice = (Read-Host '请选择').Trim().ToLower()
        if ($choice -eq 'q') { break }
        elseif ($choice -eq 'a') { Add-Route }
        elseif ($choice -eq 'd') { Remove-Route $state }
        elseif ($choice -match '^\d+$' -and [int]$choice -ge 1 -and [int]$choice -le @($state.providers).Count) { Switch-Route @($state.providers)[[int]$choice - 1] }
    } catch { Write-Host "出错了：$($_.Exception.Message)" -ForegroundColor Red }
}
