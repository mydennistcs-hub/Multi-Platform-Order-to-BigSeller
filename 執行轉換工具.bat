@echo off
chcp 65001 >nul
echo 正在檢查 Python 環境...

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [錯誤] 找不到 Python，請先安裝 Python 3.8 以上版本
    echo 下載網址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo 正在檢查相依套件...
python -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
    echo 正在安裝 openpyxl...
    pip install openpyxl
    if errorlevel 1 (
        echo [錯誤] 安裝失敗，請確認網路連線後重試
        pause
        exit /b 1
    )
)

echo 啟動轉換工具...
python "%~dp0converter.py"
