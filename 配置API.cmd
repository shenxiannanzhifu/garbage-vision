@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".env" copy /y ".env.example" ".env" >nul
notepad "%~dp0.env"
