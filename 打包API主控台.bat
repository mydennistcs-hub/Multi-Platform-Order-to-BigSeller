@echo off
rem -------------------------------------------------------------------
rem  ASCII ONLY. Do NOT put Chinese text or "chcp 65001" in this file.
rem
rem  cmd.exe tracks its position in a batch file by BYTE offset but
rem  decodes bytes using the current console code page. Any multi-byte
rem  character therefore makes the parser drift, and later lines get
rem  split mid-command ("'--hidden-import' is not recognized ...").
rem  Big5/cp950 is no safer: its trail bytes include | \ ^ and `.
rem
rem  All Chinese messages and all build logic live in
rem  build_api_console.py -- Python prints Unicode to the Windows
rem  console via WriteConsoleW, so it is immune to the code page.
rem  Full explanation: docstring at the top of build_api_console.py.
rem -------------------------------------------------------------------
setlocal
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python and add it to PATH.
    pause
    exit /b 1
)

python build_api_console.py
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
