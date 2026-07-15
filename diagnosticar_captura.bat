@echo off
setlocal EnableExtensions
title NeveLudens - Diagnosticar captura
cd /d "%~dp0"

set "ROOT=%CD%"
set "PYTHONUTF8=1"
set "DEBUG=0"
set "HF_HOME=%ROOT%\.cache\huggingface"
set "HF_HUB_CACHE=%ROOT%\.cache\huggingface\hub"
set "TRANSFORMERS_CACHE=%ROOT%\.cache\huggingface\transformers"
set "TORCH_HOME=%ROOT%\.cache\torch"
set "PIP_CACHE_DIR=%ROOT%\.cache\pip"
set "PATH=%ROOT%\.venv\Scripts;%PATH%"

if not exist ".venv\Scripts\python.exe" (
    echo A .venv nao existe. Rode iniciar.bat primeiro.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" scripts\capture_check.py
echo.
pause
