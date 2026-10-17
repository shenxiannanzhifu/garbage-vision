param([switch]$Check)
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 必须将本文件保存为 UTF-8 BOM；终端也统一用 UTF-8。
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
New-Item -ItemType Directory -Force '.tools', '.local' | Out-Null
$Gh = Join-Path $ProjectRoot '.tools\gh\bin\gh.exe'
if ($Check) {
    if (!(Test-Path -LiteralPath $Gh)) { throw 'GitHub CLI 尚未准备好。' }
    & $Gh --version
    if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI 无法运行。' }
    Write-Host '检查通过：中文脚本可正常运行，GitHub CLI 已就绪。此检查未登录或上传代码。'
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
& $Gh auth login --hostname github.com --git-protocol https --web
if ($LASTEXITCODE -ne 0) { throw '登录未完成，请将不含密码或令牌的错误提示告知助手。' }
& $Gh auth status
if ($LASTEXITCODE -ne 0) { throw '登录状态校验失败，请保留窗口中的错误提示。' }
Write-Host '登录完成。本脚本没有上传代码。可以关闭窗口并回复助手：已登录。'
