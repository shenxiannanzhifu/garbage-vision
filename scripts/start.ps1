$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
if (!(Test-Path '.venv\Scripts\python.exe')) { throw '请先运行 scripts\install.ps1' }
$env:PYTHONUTF8 = '1'
$env:YOLO_CONFIG_DIR = Join-Path $ProjectRoot '.local\ultralytics'
& '.venv\Scripts\python.exe' -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
