@echo off
rem -------------------------------------------------------------------
rem  ASCII ONLY. Do NOT put Chinese text or "chcp 65001" in this file.
rem  Reason: see the docstring at the top of build_api_console.py.
rem
rem  Fastest way to run the console on a machine that already has
rem  Python: no packaging at all, just run the source. Zero build time,
rem  starts instantly, and picks up code edits immediately. Build an
rem  .exe only when the tool must run where Python is not installed.
rem
rem  Uses "python" and not "pythonw" on purpose: the console window
rem  stays open so API errors and tracebacks are visible.
rem -------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"

"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python and add it to PATH.
    pause
    exit /b 1
)

"%PYTHON%" -c "import xhtml2pdf.pisa, requests, dotenv, openpyxl, xlrd, pdfplumber, pypdf, msoffcrypto, fitz; from PySide6 import QtWidgets, QtWebEngineCore" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies for first run, please wait ...
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency install failed.
        pause
        exit /b 1
    )
)

"%PYTHON%" app.py
if errorlevel 1 (
    echo.
    echo [ERROR] The app exited with an error. See the traceback above.
    pause
)
