@echo off
cd /d "%~dp0"
title ViralCraft AI -- Starting Backend
color 0A

echo.
echo  +======================================+
echo  |   ViralCraft AI -- Reel Script Gen   |
echo  +======================================+
echo.

:: Check Python
set PYTHON_CMD=python
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Install Python 3.10+ from python.org
        pause
        exit /b 1
    ) else (
        set PYTHON_CMD=py
    )
)

:: Check if venv exists and is complete, create if not
if exist "backend\venv\" (
    if not exist "backend\venv\Scripts\activate.bat" (
        echo [WARNING] venv exists but is incomplete. Recreating...
        rmdir /s /q backend\venv
    )
)

if not exist "backend\venv\" (
    echo [SETUP] Creating Python virtual environment...
    %PYTHON_CMD% -m venv backend\venv
)

:: Activate venv
call backend\venv\Scripts\activate.bat


:: Check if dependencies installed
pip show groq >nul 2>&1
if errorlevel 1 (
    echo [SETUP] Installing dependencies - first run may take a few minutes...
    pip install -r backend\requirements.txt
    echo.
)

:: Check for .env
if not exist "backend\.env" (
    echo [SETUP] Creating .env from template...
    copy backend\.env.example backend\.env
    echo.
    echo  +======================================================+
    echo  |  ACTION REQUIRED:                                    |
    echo  |  Open backend\.env and set your GROQ_API_KEY        |
    echo  |  Free key at: console.groq.com                      |
    echo  |  OR set LLM_PROVIDER=ollama for fully local AI      |
    echo  |  Then re-run this file.                             |
    echo  +======================================================+
    echo.
    start notepad backend\.env
    pause
    exit /b 0
)

:: Check ffmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] FFmpeg not found in PATH.
    echo           Video download may fail. Install ffmpeg from https://ffmpeg.org
    echo           and add it to your system PATH.
    echo.
)

echo [OK] Starting ViralCraft AI backend...
echo [OK] Open http://127.0.0.1:8000 in your browser
echo.

:: Launch browser after 3 seconds
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8000"

:: Start server
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

pause
