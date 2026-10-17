param([switch]$Check)
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 必须将本文件保存为 UTF-8 BOM；终端也统一用 UTF-8。
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
# 仅对本窗口及其子进程禁用 HTTP/2，保留 TLS 证书校验与其他 Go 配置。
# 这是代理环境下连接中断的兼容性措施，实际授权是否成功仍以 GitHub 返回为准。
$DebugOptions = @($env:GODEBUG -split ',' | Where-Object { $_ -and $_ -notmatch '^http2client=' })
$env:GODEBUG = (($DebugOptions + 'http2client=0') -join ',')
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
New-Item -ItemType Directory -Force '.tools', '.local' | Out-Null
$Gh = Join-Path $ProjectRoot '.tools\gh\bin\gh.exe'
if ($Check) {
    if (!(Test-Path -LiteralPath $Gh)) { throw 'GitHub CLI 尚未准备好。' }
    & $Gh --version
    if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI 无法运行。' }
    if ($env:GODEBUG -notmatch '(^|,)http2client=0(,|$)') { throw '连接兼容配置未生效。' }
    Write-Host '检查通过：中文脚本可正常运行，GitHub CLI 已就绪。此检查未登录或上传代码。'
    Write-Host '本窗口已启用 HTTP/1.1 连接兼容设置，TLS 证书校验保持开启。'
    exit 0
}
if (!(Test-Path -LiteralPath $Gh)) {
    $Zip = Join-Path $ProjectRoot '.local\gh.zip'
    Invoke-WebRequest 'https://github.com/cli/cli/releases/download/v2.102.0/gh_2.102.0_windows_amd64.zip' -OutFile $Zip
    Expand-Archive -LiteralPath $Zip -DestinationPath '.tools\gh' -Force
}
# 授权配置仅保存在被 Git 忽略的本地目录；不要上传该目录。
$env:GH_CONFIG_DIR = Join-Path $ProjectRoot '.local\github-cli'
$Proxy = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
if ($Proxy.ProxyEnable -eq 1 -and $Proxy.ProxyServer -match '^127\.0\.0\.1:\d+$') {
    $env:HTTPS_PROXY = 'http://' + $Proxy.ProxyServer
    $env:HTTP_PROXY = $env:HTTPS_PROXY
}
Write-Host '本窗口只负责登录，不会上传代码。'
Write-Host '第一步：出现 Authenticate Git ... (Y/n) 时按回车。'
Write-Host '第二步：出现 One-time code 后，再按回车打开浏览器。'
Write-Host '第三步：在网页输入本次验证码，点击 Continue，再确认授权 GitHub CLI。'
Write-Host '如果没有自动打开网页，请访问 https://github.com/login/device 。'

# 重试必须由用户按回车发起；最多三次，每次使用新的设备验证码。
for ($Attempt = 1; $Attempt -le 3; $Attempt++) {
    Write-Host "`n正在开始第 $Attempt 次登录，请使用这一次新显示的验证码。"
    & $Gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -eq 0) {
        & $Gh auth status
        if ($LASTEXITCODE -ne 0) {
            Write-Host '授权命令已结束，但状态检查未通过。请将当前错误提示告知助手。' -ForegroundColor Yellow
            exit 1
        }
        Write-Host '登录完成。本脚本没有上传代码。可以关闭窗口并回复助手：已登录。' -ForegroundColor Green
        exit 0
    }
    Write-Host '本次登录没有完成；上方若显示 unexpected EOF 或 timeout，表示网络连接中断。' -ForegroundColor Yellow
    Write-Host '不用重新创建仓库，也不要沿用刚才的验证码。'
    if ($Attempt -lt 3) {
        $RetryChoice = Read-Host '按回车重新尝试；输入 Q 后按回车退出'
        if ($RetryChoice) { exit 1 }
    }
}
Write-Host '已尝试三次，请把最后的错误提示发给助手进一步排查。' -ForegroundColor Yellow
exit 1
