param([string]$Python = "", [switch]$Cpu)
$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1：本文件保存为 UTF-8 BOM，子进程输出也使用 UTF-8。
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
New-Item -ItemType Directory -Force '.tools', '.local' | Out-Null
$env:UV_CACHE_DIR = Join-Path $ProjectRoot '.local\uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $ProjectRoot '.local\python'
$Uv = Join-Path $ProjectRoot '.tools\uv.exe'
if (!(Test-Path -LiteralPath $Uv)) {
    $Zip = Join-Path $ProjectRoot '.local\uv.zip'
    Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-pc-windows-msvc.zip' -OutFile $Zip
    Expand-Archive -LiteralPath $Zip -DestinationPath '.tools' -Force
}
if (!(Test-Path '.venv\Scripts\python.exe')) {
    if (!$Python) { $Python = '3.12' }
    & $Uv venv '.venv' --python $Python
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败' }
}
$Index = if ($Cpu) { 'https://download.pytorch.org/whl/cpu' } else { 'https://download.pytorch.org/whl/cu128' }
& $Uv pip install --python '.venv\Scripts\python.exe' torch==2.9.1 torchvision==0.24.1 --index-url $Index
if ($LASTEXITCODE -ne 0) { throw '安装 PyTorch 失败' }
& $Uv pip install --python '.venv\Scripts\python.exe' -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw '安装项目依赖失败' }
& '.venv\Scripts\python.exe' scripts/check_environment.py
if ($LASTEXITCODE -ne 0) { throw '环境验证失败' }
Write-Host '安装完成。运行 scripts\start.ps1 启动网页。'
