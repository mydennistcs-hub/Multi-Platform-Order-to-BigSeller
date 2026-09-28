@echo off
rem -------------------------------------------------------------------
rem  ASCII ONLY. Do NOT put Chinese text or "chcp 65001" in this file.
rem  Reason: see the docstring at the top of build_converter_exe.py.
rem  (This exact .bat broke with garbled "'el' is not recognized ..."
rem  errors on another PC on 2026-08-02 because of Chinese text here.)
rem
rem  Fastest way to run the converter on a machine that already has
rem  Python: no packaging at all, just run the source. Zero build time,
rem  starts instantly, and picks up code edits immediately. Build an
rem  .exe only when the tool must run where Python is not installed.
rem -------------------------------------------------------------------
setlocal
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python and add it to PATH.
    pause
    exit /b 1
)

python -c "import openpyxl, xlrd, pdfplumber, pypdf, msoffcrypto" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies for first run, please wait ...
    python -m pip install -q openpyxl xlrd pdfplumber pypdf msoffcrypto-tool
    if errorlevel 1 (
        echo [ERROR] Dependency install failed.
        pause
        exit /b 1
    )
)

python converter.py
if errorlevel 1 (
    echo.
    echo [ERROR] The app exited with an error. See the traceback above.
    pause
)
