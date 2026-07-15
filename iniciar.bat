@echo off
setlocal EnableExtensions
title NeveLudens - Iniciar
cd /d "%~dp0"

set "ROOT=%CD%"
set "PYTHONUTF8=1"
set "DEBUG=0"
set "HF_HOME=%ROOT%\.cache\huggingface"
set "HF_HUB_CACHE=%ROOT%\.cache\huggingface\hub"
set "TRANSFORMERS_CACHE=%ROOT%\.cache\huggingface\transformers"
set "TORCH_HOME=%ROOT%\.cache\torch"
set "PIP_CACHE_DIR=%ROOT%\.cache\pip"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente Python local em .venv...
    python -m venv .venv
    if errorlevel 1 py -3.11 -m venv .venv
    if errorlevel 1 goto pyfail
)

set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
set "PATH=%ROOT%\.venv\Scripts;%PATH%"

call :check_ready
if errorlevel 1 (
    call :install_deps
    if errorlevel 1 goto depfail
    call :check_ready
    if errorlevel 1 goto depfail
)

if not exist "models\ng.pt" (
    echo Baixando checkpoint local para models\ng.pt...
    if not exist "models" mkdir "models"
    set "MODEL_OWNER=nvidia"
    set "MODEL_NAME=Nitro"
    set "MODEL_SUFFIX=Gen"
    "%ROOT%\.venv\Scripts\hf.exe" download "%MODEL_OWNER%/%MODEL_NAME%%MODEL_SUFFIX%" ng.pt --local-dir models
    if errorlevel 1 goto modelfail
)

"%VENV_PY%" scripts\launcher.py
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" echo NeveLudens encerrou com codigo %EXITCODE%.
pause
exit /b %EXITCODE%

:check_ready
"%VENV_PY%" -c "import torch, torchvision, neveludens, cv2, dxcam, vgamepad, xspeedhack, zmq; raise SystemExit(0 if torch.cuda.is_available() else 1)" >nul 2>nul
exit /b %ERRORLEVEL%

:install_deps
echo Preparando dependencias dentro da .venv local...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 exit /b 1
"%VENV_PY%" -m pip install -e .
if errorlevel 1 exit /b 1
"%VENV_PY%" -m pip install --force-reinstall torch==2.13.0+cu132 --index-url https://download.pytorch.org/whl/cu132
if errorlevel 1 exit /b 1
"%VENV_PY%" -m pip install --force-reinstall torchvision==0.28.0+cu132 --index-url https://download.pytorch.org/whl/cu132
if errorlevel 1 exit /b 1
exit /b 0

:pyfail
echo.
echo Nao consegui criar a .venv. Confirme que Python 3.10+ esta instalado e no PATH.
pause
exit /b 1

:depfail
echo.
echo Falha ao preparar dependencias locais.
echo O NeveLudens precisa de uma GPU NVIDIA com CUDA funcionando no PyTorch.
pause
exit /b 1

:modelfail
echo.
echo Falha ao baixar models\ng.pt pelo Hugging Face.
echo Tente novamente mais tarde ou baixe manualmente o checkpoint base.
pause
exit /b 1
