@echo off
setlocal EnableExtensions
cd /d "%~dp0"

start "" powershell.exe -Sta -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-NeveLudensGui.ps1"
exit /b 0
