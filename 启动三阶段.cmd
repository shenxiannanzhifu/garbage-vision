@echo off
cd /d "%~dp0"
start "Stage3 API" /min "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\run_stage3.py" api
start "Stage3 Web" /min "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\run_stage3.py" web
echo 三阶段网页：http://127.0.0.1:8503
echo 关闭对应的Stage3 API和Stage3 Web窗口即可停止本机服务。
