r"""打包 converter.py 為 .exe 的建置腳本。

由 `打包成exe.bat` 呼叫，也可以直接 `python build_converter_exe.py` 執行。

**為什麼建置邏輯要寫在 Python 而不是 .bat**（2026-08-02，比照 build_api_console.py 的教訓修的）：

cmd.exe 讀批次檔是「用位元組定位檔案指標，再用當下字碼頁把位元組換算成字元」，
這在批次檔含有中文時有兩個各自獨立的坑：

1. **UTF-8 + `chcp 65001`**：每個中文字（3 bytes）都會讓檔案指標算錯，偏移量一路累積，
   讀到後面幾行就從行的中間切開。舊版 `打包成exe.bat` 就是這樣壞掉的——換一台電腦跑，
   畫面上出現「'??Python' 不是內部或外部命令」「'"D:\...\Multi-Platform-Order-to-BigSeller\"'
   不是內部或外部命令」這種把路徑、參數、甚至 echo 訊息尾巴當成指令執行的錯誤，
   `pyinstaller ... ^` 的多行續行更會放大這個問題（偏移量從第一個 `^` 續行開始累積出錯）。
2. **Big5/cp950**：Big5 的第二個位元組範圍是 0x40-0x7E 與 0xA1-0xFE，
   其中包含 `|`(0x7C)、`\`(0x5C)、`^`(0x5E)、`` ` ``(0x60) 這些 cmd 的特殊字元。
   只要主控台字碼頁不是 950（換一台電腦、遠端執行、使用者改過 chcp…），cmd 就會把中文字的
   第二個位元組當成管線符號，直接把該行切成兩段——連 `rem` 註解行都會被當指令執行。

Python 在 Windows 是透過 WriteConsoleW（Unicode API）輸出，不受主控台字碼頁影響，
所以中文訊息放在 Python 裡是安全的。結論：**.bat 一律只留純 ASCII 當薄殼**，長參數、中文訊息
都搬進這支腳本，用 list 組給 subprocess——不透過 cmd.exe 解析，也就不會有位元組偏移的問題。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "Multi-Platform-Order-to-BigSeller"
SPEC = ROOT / f"{APP_NAME}.spec"

# 建置需要的套件（pip 名稱）
REQUIREMENTS = [
    "pyinstaller",
    "openpyxl",
    "xlrd",
    "pdfplumber",
    "pypdf",
    "msoffcrypto-tool",
]

# 打包一定會用到、少了必定失敗的模組（import 名稱，跟上面的 pip 名稱不完全一樣，
# 例如 msoffcrypto-tool 的 import 名稱是 msoffcrypto）
CRITICAL_IMPORTS = ["openpyxl", "xlrd", "pdfplumber", "pypdf", "msoffcrypto", "PyInstaller"]


def log(msg: str = "") -> None:
    print(msg, flush=True)


def run(cmd: list[str]) -> int:
    """執行子行程，直接把輸出接到主控台（不吞掉錯誤訊息）。"""
    log(f"    > {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=ROOT)


def ensure_requirements() -> bool:
    log("[1/3] 檢查並安裝相依套件...")
    rc = run([sys.executable, "-m", "pip", "install", "-q", *REQUIREMENTS])
    if rc != 0:
        log()
        log("[錯誤] 相依套件安裝失敗，請看上方 pip 的錯誤訊息。")
        return False
    return True


def verify_imports() -> bool:
    log("[2/3] 驗證關鍵套件可以匯入...")
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
    log(f"[3/3] 開始打包（所有設定都在 {SPEC.name}，約 1~2 分鐘）...")
    if not SPEC.exists():
        log(f"[錯誤] 找不到 {SPEC.name}")
        return False
    started = time.monotonic()
    rc = run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)])
    elapsed = time.monotonic() - started
    if rc != 0:
        log()
        log(f"[錯誤] 打包失敗（耗時 {elapsed:.0f} 秒），請看上方錯誤訊息。")
        return False
    log(f"    打包耗時 {elapsed:.0f} 秒")
    return True


def main() -> int:
    log("=" * 52)
    log(" 打包 converter.py 為獨立 .exe 執行檔")
    log("=" * 52)
    log()

    if not ensure_requirements():
        return 1
    if not verify_imports():
        return 1
    if not build():
        return 1

    exe = ROOT / "dist" / f"{APP_NAME}.exe"
    log()
    log("=" * 52)
    log(" 打包完成")
    log(f" 執行檔位置：{exe.relative_to(ROOT)}")
    log("=" * 52)
    log()

    if sys.platform == "win32":
        import os

        os.startfile(ROOT / "dist")  # noqa: S606 — 只是開啟輸出資料夾給使用者看
    return 0


if __name__ == "__main__":
    sys.exit(main())
