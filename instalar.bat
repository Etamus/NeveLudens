@echo off
chcp 65001 >nul
setlocal EnableExtensions
title NeveLudens - Instalacao
cd /d "%~dp0"

set "ROOT=%CD%"
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
set "HF_EXE=%ROOT%\.venv\Scripts\hf.exe"
set "MODEL_PATH=%ROOT%\models\ng.pt"

set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "DEBUG=0"
set "HF_HOME=%ROOT%\.cache\huggingface"
set "HF_HUB_CACHE=%ROOT%\.cache\huggingface\hub"
set "TRANSFORMERS_CACHE=%ROOT%\.cache\huggingface\transformers"
set "TORCH_HOME=%ROOT%\.cache\torch"
set "PIP_CACHE_DIR=%ROOT%\.cache\pip"
set "PATH=%ROOT%\.venv\Scripts;%PATH%"

call :banner
call :prepare_dirs

call :find_python
if errorlevel 1 goto pyfail
echo Python encontrado: %PYTHON_CMD%

call :step "1. Ambiente Python local (.venv)"
if exist "%VENV_PY%" (
    echo .venv ja existe: %VENV_PY%
) else (
    call :run %PYTHON_CMD% -m venv ".venv"
    if errorlevel 1 goto venvfail
)

call :step "2. Ferramentas de instalacao"
call :run "%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto depfail

call :step "3. Dependencias do NeveLudens"
call :run "%VENV_PY%" -m pip install -e .
if errorlevel 1 goto depfail

call :step "4. PyTorch CUDA local"
call :run "%VENV_PY%" -m pip install --force-reinstall torch==2.13.0+cu132 torchvision==0.28.0+cu132 --index-url https://download.pytorch.org/whl/cu132 --extra-index-url https://pypi.org/simple
if errorlevel 1 goto torchfail

call :step "5. Checkpoint do modelo"
if exist "%MODEL_PATH%" (
    echo Modelo ja existe: %MODEL_PATH%
) else (
    if not exist "%HF_EXE%" goto hffail
    call :run "%HF_EXE%" download "nvidia/NitroGen" ng.pt --local-dir models
    if errorlevel 1 goto modelfail
)

call :step "6. Validacao"
call :run "%VENV_PY%" -c "import sys, torch, torchvision, neveludens, cv2, dxcam, vgamepad, xspeedhack, zmq; print('torch:', torch.__version__); print('torchvision:', torchvision.__version__); cuda=torch.cuda.is_available(); print('CUDA disponivel:', cuda); sys.exit(0 if cuda else 2)"
if errorlevel 1 goto validatefail

call :run "%VENV_PY%" -c "import torch, vgamepad; print('GPU:', torch.cuda.get_device_name(0)); gamepad=vgamepad.VX360Gamepad(); gamepad.reset(); gamepad.update(); print('Controle virtual: OK'); print('Importacoes principais: OK')"
if errorlevel 1 goto validatefail

echo.
echo Instalacao concluida.
echo Agora execute iniciar.bat para abrir o NeveLudens.
echo.
pause
exit /b 0

:banner
echo ================================================================
echo NeveLudens - instalacao local
echo ================================================================
echo Projeto: %ROOT%
echo Tudo sera instalado dentro desta pasta.
echo Nada sera instalado globalmente pelo pip.
echo.
exit /b 0

:prepare_dirs
if not exist ".cache\pip" mkdir ".cache\pip" >nul 2>nul
if not exist ".cache\huggingface" mkdir ".cache\huggingface" >nul 2>nul
if not exist ".cache\torch" mkdir ".cache\torch" >nul 2>nul
if not exist "models" mkdir "models" >nul 2>nul
if not exist "logs" mkdir "logs" >nul 2>nul
if not exist "out" mkdir "out" >nul 2>nul
if not exist "debug" mkdir "debug" >nul 2>nul
exit /b 0

:find_python
set "PYTHON_CMD="
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    exit /b 0
)
py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.11"
    exit /b 0
)
py -3.10 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.10"
    exit /b 0
)
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    exit /b 0
)
exit /b 1

:step
echo.
echo ================================================================
echo %~1
echo ================================================================
exit /b 0

:run
echo.
echo ^> %*
%*
exit /b %ERRORLEVEL%

:pyfail
echo.
echo ERRO: Nao encontrei Python 3.10 ou superior no PATH.
goto fail

:venvfail
echo.
echo ERRO: Nao consegui criar o ambiente local .venv.
goto fail

:depfail
echo.
echo ERRO: Falha ao instalar dependencias do projeto.
goto fail

:torchfail
echo.
echo ERRO: Falha ao instalar PyTorch CUDA local.
goto fail

:hffail
echo.
echo ERRO: hf.exe nao foi encontrado na .venv.
echo Confira se o passo de dependencias terminou corretamente.
goto fail

:modelfail
echo.
echo ERRO: Falha ao baixar models\ng.pt pelo Hugging Face.
goto fail

:validatefail
echo.
echo ERRO: A validacao falhou.
echo Confira se a GPU NVIDIA com CUDA e o controle virtual estao funcionando.
goto fail

:fail
echo.
echo Instalacao interrompida.
echo.
pause
exit /b 1
