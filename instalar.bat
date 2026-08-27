@echo off
chcp 65001 >nul
setlocal EnableExtensions
title NeveLudens
cd /d "%~dp0"

set "ROOT=%CD%"
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
set "MODEL_PATH=%ROOT%\models\ng.pt"
set "PYTHON_CMD="

set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "DEBUG=0"
set "BNB_CUDA_VERSION=130"
set "HF_HOME=%ROOT%\.cache\huggingface"
set "HF_HUB_CACHE=%ROOT%\.cache\huggingface\hub"
set "TRANSFORMERS_CACHE=%ROOT%\.cache\huggingface\transformers"
set "TORCH_HOME=%ROOT%\.cache\torch"
set "PIP_CACHE_DIR=%ROOT%\.cache\pip"
set "PATH=%ROOT%\.venv\Scripts;%PATH%"

goto menu

:menu
cls
call :banner
echo [1] Instalar
echo [2] Verificar ambiente
echo [3] Sair
echo.
choice /c 123 /n /m "Escolha uma opcao: "
if errorlevel 3 exit /b 0
if errorlevel 2 (
    call :verify_environment
    echo.
    pause
    goto menu
)
if errorlevel 1 goto confirm_install
goto menu

:confirm_install
echo.
echo Esta instalacao pode baixar pacotes Python, PyTorch CUDA e o checkpoint do modelo.
echo Tudo do projeto sera instalado dentro desta pasta:
echo %ROOT%
echo.
choice /c SN /n /m "Iniciar instalacao agora? [S/N]: "
if errorlevel 2 goto menu

call :install_project
if errorlevel 1 goto fail

echo.
echo Instalacao concluida.
echo Agora execute iniciar.bat para abrir o NeveLudens.
echo.
pause
exit /b 0

:install_project
call :prepare_dirs
call :ensure_python
if errorlevel 1 exit /b 1

call :step "1. Ambiente Python local (.venv)"
if exist "%VENV_PY%" (
    echo .venv ja existe: %VENV_PY%
) else (
    call :run %PYTHON_CMD% -m venv ".venv"
    if errorlevel 1 exit /b 1
)

call :step "2. Ferramentas de instalacao"
call :run "%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 exit /b 1

call :step "3. Dependencias do NeveLudens"
call :run "%VENV_PY%" -m pip install -e .
if errorlevel 1 exit /b 1

call :step "4. PyTorch CUDA local"
call :run "%VENV_PY%" -m pip install --force-reinstall torch==2.13.0+cu132 torchvision==0.28.0+cu132 --index-url https://download.pytorch.org/whl/cu132 --extra-index-url https://pypi.org/simple
if errorlevel 1 exit /b 1

call :step "5. Checkpoint do modelo"
if exist "%MODEL_PATH%" (
    echo Modelo ja existe: %MODEL_PATH%
) else (
    call :download_default_model
    if errorlevel 1 exit /b 1
)

call :step "6. Validacao"
call :run "%VENV_PY%" -c "import sys, torch, torchvision, neveludens, cv2, dxcam, vgamepad, xspeedhack, zmq, transformers, accelerate, bitsandbytes, safetensors; print('torch:', torch.__version__); print('torchvision:', torchvision.__version__); print('bitsandbytes:', bitsandbytes.__version__); cuda=torch.cuda.is_available(); print('CUDA disponivel:', cuda); sys.exit(0 if cuda else 2)"
if errorlevel 1 exit /b 1

call :run "%VENV_PY%" -c "import torch, vgamepad; print('GPU:', torch.cuda.get_device_name(0)); gamepad=vgamepad.VX360Gamepad(); gamepad.reset(); gamepad.update(); print('Controle virtual: OK'); print('Importacoes principais: OK')"
if errorlevel 1 exit /b 1

exit /b 0

:banner
echo ================================================================
echo NeveLudens
echo ================================================================
echo Projeto: %ROOT%
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

:ensure_python
call :find_python
if not errorlevel 1 (
    echo Python encontrado: %PYTHON_CMD%
    exit /b 0
)

echo.
echo Nenhum Python 3.11 ou 3.12 foi encontrado.
echo O NeveLudens foi testado principalmente com Python 3.11.
echo.
echo [1] Instalar Python 3.11 via winget (recomendado)
echo [2] Instalar Python 3.12 via winget
echo [3] Cancelar
echo.
choice /c 123 /n /m "Escolha uma opcao: "
if errorlevel 3 exit /b 1
if errorlevel 2 (
    call :install_python "Python.Python.3.12"
    if errorlevel 1 exit /b 1
    call :find_python
    exit /b %ERRORLEVEL%
)
if errorlevel 1 (
    call :install_python "Python.Python.3.11"
    if errorlevel 1 exit /b 1
    call :find_python
    exit /b %ERRORLEVEL%
)
exit /b 1

:install_python
set "PYTHON_PACKAGE=%~1"
where winget >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERRO: winget nao esta disponivel neste Windows.
    echo Instale Python 3.11 ou 3.12 manualmente e rode este instalador novamente.
    exit /b 1
)

echo.
echo Instalando %PYTHON_PACKAGE%...
winget install --id %PYTHON_PACKAGE% -e --source winget --accept-source-agreements --accept-package-agreements
if errorlevel 1 exit /b 1
echo.
echo Python instalado. Conferindo novamente...
exit /b 0

:find_python
set "PYTHON_CMD="
call :test_python py -3.11
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.11"
    exit /b 0
)
call :test_python py -3.12
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.12"
    exit /b 0
)
call :test_python python
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    exit /b 0
)
call :find_python_file "%LocalAppData%\Programs\Python\Python311\python.exe"
if not errorlevel 1 exit /b 0
call :find_python_file "%LocalAppData%\Programs\Python\Python312\python.exe"
if not errorlevel 1 exit /b 0
call :find_python_file "%ProgramFiles%\Python311\python.exe"
if not errorlevel 1 exit /b 0
call :find_python_file "%ProgramFiles%\Python312\python.exe"
if not errorlevel 1 exit /b 0
exit /b 1

:find_python_file
if not exist "%~1" exit /b 1
call :test_python "%~1"
if errorlevel 1 exit /b 1
set "PYTHON_CMD="%~1""
exit /b 0

:test_python
%* -c "import sys; raise SystemExit(0 if sys.version_info[:2] in [(3, 11), (3, 12)] else 1)" >nul 2>nul
exit /b %ERRORLEVEL%

:verify_environment
call :banner
call :find_python
if errorlevel 1 (
    echo Python 3.11/3.12: nao encontrado
) else (
    echo Python 3.11/3.12: %PYTHON_CMD%
    call :run %PYTHON_CMD% --version
)

if exist "%VENV_PY%" (
    echo.
    echo .venv: encontrado em %VENV_PY%
    call :run "%VENV_PY%" --version
    call :run "%VENV_PY%" -c "import sys; print('Python da .venv:', sys.executable)"
) else (
    echo.
    echo .venv: nao encontrado
)

if exist "%MODEL_PATH%" (
    echo Modelo: encontrado em %MODEL_PATH%
) else (
    echo Modelo: nao encontrado em %MODEL_PATH%
)

if exist "%VENV_PY%" (
    echo.
    echo Validacao rapida:
    call :run "%VENV_PY%" -c "import torch, neveludens; print('torch:', torch.__version__); print('CUDA disponivel:', torch.cuda.is_available())"
)
exit /b 0

:download_default_model
call :run "%VENV_PY%" -c "from pathlib import Path; from huggingface_hub import snapshot_download; root=Path(r'%ROOT%'); target=root/'models'/'ng.pt'; snapshot_download(repo_id='nvidia/NitroGen', allow_patterns=['ng.pt'], local_dir=root/'models', cache_dir=root/'.cache'/'huggingface'/'hub', max_workers=1); raise SystemExit(0 if target.exists() and target.stat().st_size > 0 else 1)"
exit /b %ERRORLEVEL%

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

:fail
echo.
echo ERRO: instalacao interrompida.
echo Confira a mensagem acima e rode instalar.bat novamente quando corrigir.
echo.
pause
exit /b 1
