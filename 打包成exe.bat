@echo off
chcp 65001 >nul
echo ============================================
echo  打包 converter.py 為獨立 .exe 執行檔
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python
    pause
    exit /b 1
)

echo 正在安裝 PyInstaller...
pip install pyinstaller >nul 2>&1

echo 正在打包中，請稍候（約 1~2 分鐘）...
cd /d "%~dp0"
pyinstaller --noconfirm --clean --onefile --windowed --name "Multi-Platform-Order-to-BigSeller" ^
  --hidden-import openpyxl ^
  --hidden-import xlrd ^
  --hidden-import pdfplumber ^
  --hidden-import pypdf ^
  --hidden-import msoffcrypto ^
  --collect-all pdfplumber ^
  --collect-all pdfminer ^
  converter.py

if errorlevel 1 (
    echo.
    echo [錯誤] 打包失敗，請查看上方錯誤訊息
    pause
    exit /b 1
)

echo.
echo ============================================
echo  打包完成！
echo  執行檔位置: dist\Multi-Platform-Order-to-BigSeller.exe
echo ============================================
echo.

explorer "%~dp0dist"
pause
