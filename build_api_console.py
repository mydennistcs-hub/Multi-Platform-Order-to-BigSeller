r"""打包 app.py（API 管理主控台）為 .exe 的建置腳本。

由 `打包API主控台.bat` 呼叫，也可以直接 `python build_api_console.py` 執行。

**為什麼建置邏輯要寫在 Python 而不是 .bat**（2026-08-01，踩坑後改的，不要改回去）：

cmd.exe 讀批次檔是「用位元組定位檔案指標，再用當下字碼頁把位元組換算成字元」，
這在批次檔含有中文時有兩個各自獨立的坑：

1. **UTF-8 + `chcp 65001`**：每個中文字（3 bytes）都會讓檔案指標算錯，偏移量一路累積，
   讀到後面幾行就從行的中間切開。舊版 `打包API主控台.bat` 就是這樣壞掉的——
   畫面上出現「'--hidden-import' 不是內部或外部命令」「'-API-Console.exe' 不是內部或外部命令」
   這種把參數、甚至 echo 訊息尾巴當成指令執行的錯誤，`^` 續行更會放大這個問題。
2. **Big5/cp950**：Big5 的第二個位元組範圍是 0x40-0x7E 與 0xA1-0xFE，
   其中包含 `|`(0x7C)、`\`(0x5C)、`^`(0x5E)、`` ` ``(0x60) 這些 cmd 的特殊字元。
   只要主控台字碼頁不是 950（遠端執行、CI、使用者改過 chcp…），cmd 就會把中文字的
   第二個位元組當成管線符號，直接把該行切成兩段——連 `rem` 註解行都會被當指令執行。

Python 在 Windows 是透過 WriteConsoleW（Unicode API）輸出，不受主控台字碼頁影響，
所以中文訊息放在 Python 裡是安全的。結論：**.bat 一律只留純 ASCII 當薄殼**。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "Multi-Platform-API-Console.spec"
APP_NAME = "Multi-Platform-API-Console"

# 建置與執行都需要的套件（pip 名稱）
# xlrd / pdfplumber：2026-08-05 新增「訂單轉換」分頁重用 converter.py 的 convert_orders()，
# 這支 App 現在也真的用得到（讀 mo店+ 舊版 .xls、讀取裝箱明細/運單 PDF），比照
# Multi-Platform-Order-to-BigSeller.spec（Phase 1）的相依清單補上。
REQUIREMENTS = [
    "pyinstaller",
    "PySide6",
    "requests",
    "python-dotenv",
    "openpyxl",
    "msoffcrypto-tool",
    "pypdf",
    "xhtml2pdf",
    "reportlab",
    "xlrd",
    "pdfplumber",
    # 2026-08-23 新增：Coupang 全家/7-11 寄件單改用 QtWebEngine 轉 PDF，再用 PyMuPDF 把渲染
    # 結果等比例放大貼到 A4（見 api_sync/qt_html_pdf.py）。PyMuPDF 也是 repair_invoice_pdf.py
    # 檢查修復結果用的套件。
    "PyMuPDF",
]

# 打包一定會用到、少了必定失敗的模組（import 名稱）
CRITICAL_IMPORTS = [
    "PySide6", "xhtml2pdf", "reportlab", "pdfplumber", "PyInstaller",
    "PySide6.QtWebEngineCore",  # 寄件單 HTML 轉 PDF 用，少了 Coupang 超商寄件單會轉不出來
    "fitz",  # PyMuPDF
]

EXAMPLE_FILES = ["accounts.example.json", ".env.example"]


def log(msg: str = "") -> None:
    print(msg, flush=True)


def run(cmd: list[str]) -> int:
    """執行子行程，直接把輸出接到主控台（不吞掉錯誤訊息）。

    舊版 .bat 把 pip 的輸出導到 nul，結果 PySide6 沒裝成功也完全看不出來，
    只會在後面打包時噴莫名其妙的錯，所以這裡刻意不做任何輸出抑制。
    """
    log(f"    > {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=ROOT)


def ensure_requirements() -> bool:
    log("[1/4] 檢查並安裝相依套件...")
    rc = run([sys.executable, "-m", "pip", "install", "-q", *REQUIREMENTS])
    if rc != 0:
        log()
        log("[錯誤] 相依套件安裝失敗，請看上方 pip 的錯誤訊息。")
        return False
    return True


def verify_imports() -> bool:
    log("[2/4] 驗證關鍵套件可以匯入...")
    missing = []
    for name in CRITICAL_IMPORTS:
        rc = subprocess.call(
            [sys.executable, "-c", f"import {name}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if rc != 0:
            missing.append(name)
    if missing:
        log()
        log(f"[錯誤] 以下套件無法匯入，打包一定會失敗：{', '.join(missing)}")
        log(f"       請手動執行：{sys.executable} -m pip install {' '.join(REQUIREMENTS)}")
        return False
    log(f"    全部就緒（Python {sys.version.split()[0]}）")
    return True


def build() -> bool:
    log("[3/4] 開始打包（所有設定都在 Multi-Platform-API-Console.spec）...")
    log("      不加 --clean，第二次以後會走增量重建，明顯更快；")
    log("      只有換 Python/套件版本或出現詭異錯誤時才需要手動加 --clean。")
    if not SPEC.exists():
        log(f"[錯誤] 找不到 {SPEC.name}")
        return False
    started = time.monotonic()
    rc = run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)])
    elapsed = time.monotonic() - started
    if rc != 0:
        log()
        log(f"[錯誤] 打包失敗（耗時 {elapsed:.0f} 秒），請看上方錯誤訊息。")
        return False
    log(f"    打包耗時 {elapsed:.0f} 秒")
    return True


def output_dir() -> Path:
    """回傳實際產出位置：onedir 是資料夾，onefile 則退回 dist 本身。"""
    onedir = ROOT / "dist" / APP_NAME
    return onedir if onedir.is_dir() else ROOT / "dist"


def copy_examples(dest: Path) -> None:
    log("[4/4] 複製設定檔範本...")
    for name in EXAMPLE_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, dest / name)
            log(f"    {name} -> {dest.name}/")
        else:
            log(f"    [警告] 找不到 {name}，略過")


def folder_size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def main() -> int:
    log("=" * 52)
    log(" 打包 API 管理主控台（app.py）為 .exe")
    log("=" * 52)
    log()

    if not ensure_requirements():
        return 1
    if not verify_imports():
        return 1
    if not build():
        return 1

    dest = output_dir()
    copy_examples(dest)

    exe = dest / f"{APP_NAME}.exe"
    log()
    log("=" * 52)
    log(" 打包完成")
    log(f" 產出位置：{dest.relative_to(ROOT)}")
    if exe.exists():
        log(f" 執行檔：  {exe.relative_to(ROOT)}")
    log(f" 資料夾總大小：{folder_size_mb(dest):.0f} MB")
    log()
    log(" 第一次使用：在同一個資料夾把 accounts.example.json")
    log(" 複製一份改名為 accounts.json，填入各帳戶憑證後再執行 .exe。")
    log(" 要帶到別台電腦：整個資料夾一起複製（或壓成 zip），不能只複製 .exe。")
    log("=" * 52)
    log()

    if os.name == "nt":
        os.startfile(dest)  # noqa: S606 — 只是開啟輸出資料夾給使用者看
    return 0


if __name__ == "__main__":
    sys.exit(main())
