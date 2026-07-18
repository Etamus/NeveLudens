@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "GUI_PS1=%CD%\scripts\Start-NeveLudensGui.ps1"

start "" powershell.exe -Sta -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%GUI_PS1%"
exit /b 0
