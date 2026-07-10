# manmankan 一键安装脚本 · Windows PowerShell
#
# 推荐安装：
#   uv tool install manmankan
#
# 想使用脚本时,请先下载并审阅 release tag 对应版本。
#
# 设计原则：命令行新手可读 · 全程中文 · idempotent · 失败给 fallback · 不留半成品
#
# 注意 ExecutionPolicy：
# 如果跑脚本被拦，先在 PowerShell 跑一行（只影响当前用户，安全）：
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# 详情见 https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies

$ErrorActionPreference = 'Stop'

# ── 输出 helper ──────────────────────────────────────────────────
function Say  ([string]$msg) { Write-Host $msg }
function Ok   ([string]$msg) { Write-Host "✅ $msg" -ForegroundColor Green }
function Warn ([string]$msg) { Write-Host "⚠️  $msg" -ForegroundColor Yellow }
function Fail ([string]$msg) { Write-Host "❌ $msg" -ForegroundColor Red }
function Info ([string]$msg) { Write-Host "→ $msg" -ForegroundColor Cyan }
function Hint ([string]$msg) { Write-Host "   $msg" -ForegroundColor DarkGray }
function Step ([string]$title) { Say ""; Write-Host "━━━ $title ━━━" -ForegroundColor Cyan }

# ── Banner ───────────────────────────────────────────────────────
Say ""
Say "🐙 慢慢看 (manmankan) 一键安装脚本"
Say "   普通 A 股散户的本地观察台 · 本地存储 · 开源 · AGPL-3.0"
Say ""
Say "📋 即将做这 4 件事："
Say "   1. 检查你的系统 (Windows + PowerShell 版本)"
Say "   2. 检查 / 安装 uv (Python 工具管理器)"
Say "   3. 安装 manmankan"
Say "   4. 验证安装成功"
Say ""
Hint "全程约 1-3 分钟 · 失败可以重跑 · Ctrl-C 可随时中断"
Say ""

# 交互式调用才给「按回车继续」· iex 管道模式直接跑
if ([Console]::IsInputRedirected -eq $false) {
    try {
        Read-Host "↩️  按回车继续 · 或 Ctrl-C 取消" | Out-Null
    } catch {
        # iex pipeline 下 Read-Host 可能抛错 · 忽略继续
    }
}

# ── 1/4 系统检查 ─────────────────────────────────────────────────
Step "1/4 系统检查"

if ($PSVersionTable.PSVersion.Major -lt 5) {
    Fail "需要 PowerShell 5+ · 当前是 $($PSVersionTable.PSVersion)"
    Hint "升级 PowerShell: https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell"
    exit 1
}
Ok "PowerShell $($PSVersionTable.PSVersion)"

# ExecutionPolicy 提示（仅警告 · 不强制改）
$policy = Get-ExecutionPolicy -Scope CurrentUser
if ($policy -eq 'Restricted' -or $policy -eq 'Undefined') {
    Warn "PowerShell ExecutionPolicy = $policy · 后续步骤可能被拦"
    Hint "建议改成 RemoteSigned (只影响当前用户 · 安全):"
    Hint "   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned"
    Hint "详细 https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies"
    Say ""
}

# ── 2/4 uv 检查 / 安装 ───────────────────────────────────────────
Step "2/4 检查 uv (Python 工具管理器)"

$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd) {
    $uvVersion = (uv --version 2>$null) -replace "\r?\n", ""
    if (-not $uvVersion) { $uvVersion = "未知版本" }
    Ok "uv 已安装: $uvVersion"
} else {
    Info "uv 未安装 · 即将从 astral.sh 下载安装"
    Say ""
    Hint "📋 安装 URL: https://astral.sh/uv/install.ps1"
    Hint "💡 不放心? 可以 Ctrl-C 退出 · 然后:"
    Hint "      irm https://astral.sh/uv/install.ps1 > `$env:TEMP\uv-install.ps1"
    Hint "      Get-Content `$env:TEMP\uv-install.ps1   # 自己看完再装"
    Hint "      `$env:TEMP\uv-install.ps1"
    Say ""
    Info "继续 · 下载安装中..."

    try {
        Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' | Invoke-Expression
        Ok "uv 安装完成"
        # 刷新当前 session 的 PATH · 让后续步骤能调到 uv
        $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
    } catch {
        Fail "uv 安装失败: $_"
        Warn "备用方案 (任选一个):"
        Hint "  winget install astral-sh.uv         # Windows winget"
        Hint "  pipx install manmankan              # 跳过 uv · 直接装 manmankan"
        Hint "详细文档 https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    }
}

# 再次检查 uv 现在能调到
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    Fail "uv 装完了但当前 PowerShell 找不到 (PATH 没更新)"
    Warn "解决办法:"
    Hint "  1. 关掉这个 PowerShell 窗口"
    Hint "  2. 重新打开一个新 PowerShell"
    Hint "  3. 重跑本安装脚本"
    exit 1
}

# ── 3/4 安装 manmankan ───────────────────────────────────────────
Step "3/4 安装 manmankan"

$existing = & uv tool list 2>$null | Select-String "^manmankan "
if ($existing) {
    Info "manmankan 已装过 · 升级到最新版"
    try {
        & uv tool install --upgrade manmankan
        if ($LASTEXITCODE -ne 0) { throw "uv tool install --upgrade 退出码 $LASTEXITCODE" }
        Ok "manmankan 升级完成"
    } catch {
        Fail "升级失败: $_"
        Warn "可以试 --reinstall (彻底重装):"
        Hint "  uv tool install --reinstall manmankan"
        exit 1
    }
} else {
    Info "首次安装 manmankan"
    Hint "大约 30-60 秒 · 在下载 pandas / akshare 等依赖"
    try {
        & uv tool install manmankan
        if ($LASTEXITCODE -ne 0) { throw "uv tool install 退出码 $LASTEXITCODE" }
        Ok "manmankan 安装完成"
    } catch {
        Fail "安装失败: $_"
        Warn "备用方案:"
        Hint "  pipx install manmankan       # 用 pipx 试试"
        Hint "  uv tool install --reinstall manmankan"
        Hint "或来 https://github.com/piklen/manmankan/issues 提问"
        exit 1
    }
}

# ── 4/4 验证 ──────────────────────────────────────────────────────
Step "4/4 验证安装"

$needsReshell = $false
$kanCmd = Get-Command kan -ErrorAction SilentlyContinue
if (-not $kanCmd) {
    Warn "kan 命令暂时调不到 · 这是正常的 · PATH 还没刷新"
    $needsReshell = $true
} else {
    try {
        $kanVer = (& kan --version 2>&1) -join " "
        if ($LASTEXITCODE -eq 0) {
            Ok "kan 命令可用: $kanVer"
        } else {
            Warn "kan 命令好像装上了但跑不动: $kanVer"
            $needsReshell = $true
        }
    } catch {
        Warn "kan 命令调起异常: $_"
        $needsReshell = $true
    }
}

# ── 完成 ──────────────────────────────────────────────────────────
Say ""
Say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Ok "🎉 安装完成!"
Say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Say ""

if ($needsReshell) {
    Warn "⚠️  重要: 关掉这个 PowerShell · 重新打开一个新的"
    Hint "(只有重开后 kan 命令才能用 · 这是 PATH 加载的限制)"
    Say ""
}

Say "📖 下一步 · 打开本地观察台:"
Say ""
Say "   kan web                         # 在网页里添加自选和持仓"
Say ""
Say "   想留在终端可运行: kan daily"
Say ""
Say "📚 看完整命令:  kan --help"
Say "📖 README:    https://github.com/piklen/manmankan"
Say "❓ 装坏了:    https://github.com/piklen/manmankan/issues"
Say ""
Hint "🔒 manmankan 本地存储自选 · 没账号 · 没推送 · 没广告"
Hint "   你的自选股存 `$env:LOCALAPPDATA\kan\ · 完全是你的"
Say ""
