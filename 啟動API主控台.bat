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

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python and add it to PATH.
    pause
    exit /b 1
)

python -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies for first run, please wait ...
    python -m pip install -q PySide6 requests python-dotenv openpyxl msoffcrypto-tool pypdf xhtml2pdf reportlab
    if errorlevel 1 (
        echo [ERROR] Dependency install failed.
        pause
        exit /b 1
    )
)

python app.py
if errorlevel 1 (
    echo.
    echo [ERROR] The app exited with an error. See the traceback above.
    pause
)
